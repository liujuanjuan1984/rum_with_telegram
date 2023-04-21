import logging

import telegram
from quorum_data_py import feed
from quorum_mininode_py import MiniNode
from telegram.ext import Filters, MessageHandler, Updater

from src.db_handle import DBHandle
from src.module import Relation, User

logger = logging.getLogger(__name__)


class DataExchanger:
    """the data exchanger between telegram bot/channel/chat-group and rum group-chain"""

    def __init__(self, config):
        self.config = config
        self.rum = MiniNode(self.config.RUM_SEED, self.config.ETH_PVTKEY)
        self.tg = telegram.Bot(token=self.config.TG_BOT_TOKEN)
        self.db = DBHandle(self.config.DB_URL, echo=self.config.DB_ECHO)
        self.updater = Updater(token=self.config.TG_BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher

    def _get_origin_post_id(self, rum_post_id: str):
        """get the origin post id for trx"""
        logger.info("get origin post id for %s", rum_post_id)
        if not rum_post_id:
            return None
        obj = self.db.get_first(Relation, {"rum_post_id": rum_post_id}, "rum_post_id")
        if obj:
            if obj.trx_type == "post":
                return obj.rum_post_id
            if obj.trx_type == "comment":
                trx = self.rum.api.trx(obj.trx_id)
                rum_post_id = trx["Data"]["object"]["inreplyto"]["id"]
                return self._get_origin_post_id(rum_post_id)
        logger.warning("failed!!! get origin post id for %s", rum_post_id)
        return None

    def send_to_rum(self, message, userid, reply_id=None, origin=None):
        """send text as trx to rum group chain"""
        user = self.db.get_first(User, {"user_id": userid}, "user_id")
        if user:
            pvtkey = user.pvtkey
        else:
            pvtkey = None
        self.rum.change_account(pvtkey)

        text = message.text or message.caption
        _photo = message.photo
        if _photo:
            image = bytes(_photo[-1].get_file().download_as_bytearray())
        else:
            image = None
        images = [image] if image else None

        if reply_id:
            data = feed.reply(content=text, images=images, reply_id=reply_id)
        else:
            data = feed.new_post(content=text, images=images)
        if origin:
            data["origin"] = {
                "type": "telegram",
                "name": self.config.TG_CHANNEL_NAME,
                "url": f"{self.config.TG_CHANNEL_URL}/{origin}",
            }

        resp = self.rum.api.post_content(data)
        post_id = self._get_origin_post_id(reply_id) or data["object"]["id"]
        rum_post_url = f"{self.config.FEED_URL_BASE}{post_id}"
        logger.info("success: send_to_rum %s", resp["trx_id"])
        return {
            "group_id": self.rum.group.group_id,
            "trx_id": resp["trx_id"],
            "rum_post_id": data["object"]["id"],
            "rum_post_url": rum_post_url,
            "user_id": userid,
            "pubkey": self.rum.account.pubkey,
            "trx_type": "post" if not reply_id else "comment",
        }

    def _comment_with_feedurl(
        self, extend_text: str, userid, reply_to_message_id, rum_post_url
    ):
        """reply to user with rum post url"""
        reply = "⚜️ 数据已上链 Success to rum group blockchain" + (extend_text or "")
        reply_markup = {
            "inline_keyboard": [
                [{"text": "Click here to view 点击查看", "url": rum_post_url}]
            ]
        }
        self.tg.send_message(
            chat_id=userid,
            text=reply,
            parse_mode="HTML",
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
        logger.info("send reply done")

    def _db_user(self, userid, username):
        payload = {
            "user_id": userid,
            "username": username,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, payload, "user_id")

    def handle_private_chat(self, update, context):
        """send message to rum group and telegram channel"""
        logger.info("handle_private_chat")
        message_id = update.message.message_id
        userid = update.message.from_user.id
        username = update.message.from_user.username
        _text = update.message.text or update.message.caption or ""
        text = f"{_text}\n\nFrom telegram user @{username} through bot {self.config.TG_BOT_NAME}"
        _photo = update.message.photo
        if _photo:
            image = bytes(_photo[-1].get_file().download_as_bytearray())
            resp = self.tg.send_photo(
                chat_id=self.config.TG_CHANNEL_NAME, photo=image, caption=text
            )
        else:
            image = None
            text = f"{_text}\nFrom telegram user @{username} through bot {self.config.TG_BOT_NAME}"
            resp = self.tg.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)

        relation = self.send_to_rum(
            update.message,
            userid,
            origin=resp.message_id,
        )
        relation.update(
            {
                "chat_type": "private",
                "chat_message_id": message_id,
                "channel_message_id": resp.message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")
        self._db_user(userid, username)
        self._comment_with_feedurl(
            f" and to channel {self.config.TG_CHANNEL_NAME}",
            userid,
            message_id,
            relation.get("rum_post_url"),
        )

    def _handle_channel_post(self, update, context):
        """send message to rum group"""
        logger.info("handle_channel_post")
        # channel post to rum group chain
        userid = update.channel_post.chat.id
        # send to rum
        relation = self.send_to_rum(
            update.channel_post,
            userid,
            origin=update.channel_post.message_id,
        )
        relation.update(
            {
                "channel_message_id": update.channel_post.message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")
        self._db_user(userid, update.channel_post.chat.username)

    def handle_channel_message(self, update, context):
        """send message to rum group"""
        logger.info("handle_channel_message")
        # channel post to rum group chain
        if update.channel_post:
            self._handle_channel_post(update, context)
            return
        channel_message_id = update.message.forward_from_message_id
        chat_message_id = update.message.message_id

        # send reply to user in group chat
        rum_post_url = self.db.get_trx_sent(channel_message_id).rum_post_url
        if not rum_post_url:
            logger.warning("not found channel_message_id %s", channel_message_id)
            return
        self._comment_with_feedurl(
            "", update.message.chat.id, chat_message_id, rum_post_url
        )
        payload = {
            "chat_message_id": chat_message_id,
            "chat_type": update.message.chat.type,
            "channel_message_id": channel_message_id,
        }
        self.db.add_or_update(Relation, payload, "chat_message_id")

    def _handle_reply_message(self, update, context):
        logger.info("start handle_reply_message")
        username = update.message.from_user.username
        userid = update.message.from_user.id
        reply_msg = update.message.reply_to_message
        channel_message_id = reply_msg.forward_from_message_id
        reply_chat_message_id = reply_msg.message_id
        reply_id = None
        if channel_message_id:
            reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
        elif reply_chat_message_id:
            obj = self.db.get_first(
                Relation,
                {"chat_message_id": reply_chat_message_id},
                "chat_message_id",
            )
            reply_id = obj.rum_post_id
            if obj and not channel_message_id:
                channel_message_id = obj.channel_message_id

        if not channel_message_id and not reply_chat_message_id:
            # get pinned
            _pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
            channel_message_id = _pinned.forward_from_message_id
            logger.info("get channel_message_id from pinned %s", channel_message_id)
            reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
            logger.info("channel_message_id to reply_id %s", reply_id)

        relation = self.send_to_rum(
            update.message, userid, reply_id, channel_message_id
        )
        relation.update(
            {
                "chat_message_id": update.message.message_id,
                "chat_type": update.message.chat.type,
                "channel_message_id": channel_message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")
        self._db_user(userid, username)

    def handle_group_message(self, update, context):
        """handle group message"""

        if update.message.reply_to_message:
            self._handle_reply_message(update, context)
            return
        logger.info("handle_group_message without reply_to_message")
        username = update.message.from_user.username
        userid = update.message.from_user.id
        _pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
        channel_message_id = _pinned.forward_from_message_id
        logger.info("get channel_message_id from pinned %s", channel_message_id)
        reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
        logger.info("channel_message_id to reply_id %s", reply_id)

        relation = self.send_to_rum(
            update.message,
            userid,
            reply_id,
            channel_message_id,
        )
        relation.update(
            {
                "chat_message_id": update.message.message_id,
                "chat_type": update.message.chat.type,
                "channel_message_id": channel_message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")
        self._db_user(userid, username)

    def run(self):
        # private chat message:
        # send to tg channel and rum group as new post
        # reply the feed_post_url to user in private chat and the comment of the channel post
        self.dispatcher.add_handler(
            MessageHandler(
                (Filters.text | Filters.photo)
                & ~Filters.command
                & Filters.chat_type.private,
                self.handle_private_chat,
            )
        )
        # channel message:
        # send to rum group as new post; and reply to user in group chat
        self.dispatcher.add_handler(
            MessageHandler(
                (Filters.text | Filters.photo)
                & ~Filters.command
                & Filters.sender_chat(self.config.TG_CHANNEL_ID),
                self.handle_channel_message,
            )
        )
        # group message:
        # send to rum group as comment of the pinned post or the reply-to post
        self.dispatcher.add_handler(
            MessageHandler(
                (Filters.text | Filters.photo)
                & ~Filters.command
                & Filters.chat_type.groups,
                self.handle_group_message,
            )
        )

        self.updater.start_polling()
        self.updater.idle()
