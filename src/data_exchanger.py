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

    def send_to_rum(self, text: str, userid, reply_id=None, origin: dict = None):
        """send text as trx to rum group chain"""
        if not text:
            logger.warning("text is empty")

        user = self.db.get_first(User, {"user_id": userid}, "user_id")
        if user:
            pvtkey = user.pvtkey
        else:
            pvtkey = None

        self.rum.change_account(pvtkey)
        if reply_id:
            data = feed.reply(content=text, reply_id=reply_id)
        else:
            data = feed.new_post(content=text)
        if origin:
            data["origin"] = origin
        resp = self.rum.api.post_content(data)
        if "trx_id" not in resp:
            raise ValueError(f"send to rum failed {resp}")
        trx_id = resp["trx_id"]
        rum_post_id = data["object"]["id"]
        origin_id = None
        if reply_id:
            origin_id = self._get_origin_post_id(reply_id)
        rum_post_url = f"{self.config.FEED_URL_BASE}{origin_id or rum_post_id }"
        logger.info("success: send_to_rum %s", trx_id)

        relation = {
            "group_id": self.rum.group.group_id,
            "trx_id": trx_id,
            "rum_post_id": rum_post_id,
            "rum_post_url": rum_post_url,
            "user_id": userid,
            "pubkey": self.rum.account.pubkey,
            "trx_type": "post" if not reply_id else "comment",
        }
        return relation

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
        resp = self.tg.send_message(
            chat_id=userid,
            text=reply,
            parse_mode="HTML",
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
        logger.debug("send reply done\n\n%s", resp)

    def _db_user(self, userid, username):
        payload = {
            "user_id": userid,
            "username": username,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, payload, "user_id")

    def _origin(self, channel_message_id):
        return {
            "type": "telegram",
            "name": self.config.TG_CHANNEL_NAME,
            "url": f"{self.config.TG_CHANNEL_URL}/{channel_message_id}",
        }

    def handle_private_chat(self, update, context):
        """send message to rum group and telegram channel"""
        logger.debug("handle_private_chat\n\n%s\n\n", update)
        message_id = update.message.message_id
        userid = update.message.from_user.id
        username = update.message.from_user.username
        _text = update.message.text
        text = f"{_text}\nFrom telegram user @{username} through bot {self.config.TG_BOT_NAME}"
        resp = self.tg.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)
        relation = self.send_to_rum(
            _text,
            userid,
            origin=self._origin(resp.message_id),
        )
        logger.debug("send_to_channel done\n\n%s\n\n", resp)

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
        logger.debug("handle_channel_post\n\n%s\n\n", update)
        # channel post to rum group chain
        userid = update.channel_post.chat.id
        username = update.channel_post.chat.username
        # send to rum
        relation = self.send_to_rum(
            update.channel_post.text,
            userid,
            origin=self._origin(update.channel_post.message_id),
        )
        relation.update(
            {
                "channel_message_id": update.channel_post.message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")
        self._db_user(userid, username)

    def handle_channel_message(self, update, context):
        """send message to rum group"""
        logger.debug("handle_channel_message\n\n%s\n\n", update)
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
        logger.debug("handle_reply_message \n\n%s\n\n", update)
        username = update.message.from_user.username
        userid = update.message.from_user.id
        reply_msg = update.message.reply_to_message
        channel_message_id = reply_msg.forward_from_message_id
        logger.debug("channel_message_id %s", channel_message_id)
        reply_chat_message_id = reply_msg.message_id
        reply_id = None
        logger.debug("reply_chat_message_id %s", reply_chat_message_id)
        if channel_message_id:
            reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
            logger.debug("channel_message_id to reply_id %s", reply_id)
        elif reply_chat_message_id:
            obj = self.db.get_first(
                Relation,
                {"chat_message_id": reply_chat_message_id},
                "chat_message_id",
            )
            reply_id = obj.rum_post_id
            logger.debug("chat_message_id to reply_id %s", reply_id)
            if obj and not channel_message_id:
                channel_message_id = obj.channel_message_id
                logger.debug("get channel_message_id from db %s", channel_message_id)

        if not channel_message_id and not reply_chat_message_id:
            # get pinned
            _pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
            logger.debug("pinned message\n\n%s\n\n", _pinned)
            channel_message_id = _pinned.forward_from_message_id
            logger.debug("get channel_message_id from pinned %s", channel_message_id)
            reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
            logger.debug("channel_message_id to reply_id %s", reply_id)

        relation = self.send_to_rum(
            update.message.text,
            userid,
            reply_id,
            self._origin(channel_message_id),
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
        logger.debug("handle_group_message without reply_to_messagen")

        username = update.message.from_user.username
        userid = update.message.from_user.id

        _pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
        logger.debug("pinned message\n\n%s\n\n", _pinned)
        channel_message_id = _pinned.forward_from_message_id
        logger.debug("get channel_message_id from pinned %s", channel_message_id)
        reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
        logger.debug("channel_message_id to reply_id %s", reply_id)

        relation = self.send_to_rum(
            update.message.text,
            userid,
            reply_id,
            self._origin(channel_message_id),
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
        # private chat message: send to tg channel and rum group as new post
        # and reply the url to user in private chat and the comment of the channel post
        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text & ~Filters.command & Filters.chat_type.private,
                self.handle_private_chat,
            )
        )
        # channel message: send to rum group as new post; and reply to user in group chat
        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text
                & ~Filters.command
                & Filters.sender_chat(self.config.TG_CHANNEL_ID),
                self.handle_channel_message,
            )
        )

        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text & ~Filters.command & Filters.chat_type.groups,
                self.handle_group_message,
            )
        )

        self.updater.start_polling()
        self.updater.idle()
