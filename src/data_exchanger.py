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

    def send_to_rum(self, text: str, userid, reply_id=None):
        """send text as trx to rum group chain"""
        if not text:
            logger.warning("text is empty")

        user = self.db.get_first(User, {"user_id": userid}, "user_id")
        if user:
            pvtkey = user.pvtkey
        else:
            pvtkey = None

        logger.info("account before %s", self.rum.account.pvtkey)
        self.rum.change_account(pvtkey)
        logger.info("account after %s", self.rum.account.pvtkey)
        if reply_id:
            data = feed.reply(content=text, reply_id=reply_id)
        else:
            data = feed.new_post(content=text)
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
        return trx_id, rum_post_id, rum_post_url

    def handle_private_chat(self, update, context):
        """send message to rum group and telegram channel"""
        logger.debug("handle_private_chat\n\n%s\n\n", update)
        message_id = update.message.message_id
        userid = update.message.from_user.id
        username = update.message.from_user.username
        text = update.message.text
        text = f"{text}\nFrom telegram user @{username} through bot {self.config.TG_BOT_NAME}"
        trx_id, rum_post_id, rum_post_url = self.send_to_rum(text, userid)
        resp = self.tg.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)
        logger.debug("send_to_channel done\n\n%s\n\n", resp)

        payload = {
            "group_id": self.rum.group.group_id,
            "trx_id": trx_id,
            "trx_type": "post",
            "rum_post_id": rum_post_id,
            "chat_type": "private",
            "chat_message_id": message_id,
            "channel_message_id": resp.message_id,
            "rum_post_url": rum_post_url,
            "user_id": userid,
            "pubkey": self.rum.account.pubkey,
        }
        self.db.add_or_update(Relation, payload, "trx_id")

        payload = {
            "user_id": userid,
            "username": username,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, payload, "user_id")

        # reply to user
        reply = f"Success to telegram channel {self.config.TG_CHANNEL_NAME} and rum group blockchain"
        reply_markup = {
            "inline_keyboard": [[{"text": "Click here to view", "url": rum_post_url}]]
        }
        resp = self.tg.send_message(
            chat_id=userid,
            text=reply,
            parse_mode="HTML",
            reply_markup=reply_markup,
            reply_to_message_id=message_id,
        )
        logger.debug("send reply done\n\n%s", resp)

    def handle_channel_message(self, update, context):
        """send message to rum group"""
        logger.debug("handle_channel_message\n\n%s\n\n", update)
        # channel post to rum group chain
        if update.channel_post:
            logger.info("channel_post")
            userid = update.channel_post.chat.id
            username = update.channel_post.chat.username
            if username != self.config.TG_CHANNEL_NAME.lstrip("@"):
                logger.warning(
                    "%s message not from channel %s",
                    username,
                    self.config.TG_CHANNEL_NAME,
                )

            # send to rum
            text = f"{update.channel_post.text}\nFrom telegram channel @{username}"
            trx_id, rum_post_id, rum_post_url = self.send_to_rum(text, userid)

            # update db
            payload = {
                "group_id": self.rum.group.group_id,
                "trx_id": trx_id,
                "trx_type": "post",
                "rum_post_id": rum_post_id,
                "channel_message_id": update.channel_post.message_id,
                "rum_post_url": rum_post_url,
                "user_id": userid,
                "pubkey": self.rum.account.pubkey,
            }
            self.db.add_or_update(Relation, payload, "trx_id")

            payload = {
                "user_id": userid,
                "username": username,
                "pvtkey": self.rum.account.pvtkey,
                "pubkey": self.rum.account.pubkey,
                "address": self.rum.account.address,
            }
            self.db.add_or_update(User, payload, "user_id")

        elif update.message:
            logger.info("message")
            message_id = update.message.forward_from_message_id

            # send reply to user in group chat
            obj = self.db.get_first(
                Relation,
                {"channel_message_id": message_id},
                "channel_message_id",
            )
            if obj:
                # leave a comment with post_url to channel post
                rum_post_url = obj.rum_post_url
                reply = f"Success to rum group blockchain"
                reply_markup = {
                    "inline_keyboard": [
                        [{"text": "Click here to view", "url": rum_post_url}]
                    ]
                }
                resp = self.tg.send_message(
                    chat_id=update.message.chat.id,
                    text=reply,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_to_message_id=update.message.message_id,
                )
                logger.debug("send reply done\n\n%s\n\n", resp)

                payload = {
                    "chat_message_id": update.message.message_id,
                    "chat_type": update.message.chat.type,
                    "channel_message_id": message_id,
                }
                self.db.add_or_update(Relation, payload, "channel_message_id")
            else:
                logger.warning("!!!! Todo: unknown message \n\n%s\n", update)
        else:
            logger.warning("!!!! Todo: unknown update \n\n%s\n", update)

    def handle_group_message(self, update, context):
        logger.debug("handle_group_message \n\n%s\n\n", update)

        username = update.message.from_user.username
        userid = update.message.from_user.id
        # send to rum group
        text = f"{update.message.text}\nFrom telegram chat {self.config.TG_GROUP_NAME}"
        reply_id = None
        if update.message.reply_to_message:
            obj = self.db.get_first(
                Relation,
                {"chat_message_id": update.message.reply_to_message.message_id},
                "chat_message_id",
            )
            if obj is None:
                obj = self.db.get_first(
                    Relation,
                    {
                        "channel_message_id": update.message.reply_to_message.forward_from_message_id
                    },
                    "channel_message_id",
                )
            if obj:
                reply_id = obj.rum_post_id
        else:
            _pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
            logger.debug("pinned message\n\n%s\n\n", _pinned)
            reply_id = self.db.get_first(
                Relation,
                {"channel_message_id": _pinned.forward_from_message_id},
                "channel_message_id",
            ).rum_post_id

        trx_id, rum_post_id, rum_post_url = self.send_to_rum(text, userid, reply_id)
        # update db
        payload = {
            "group_id": self.rum.group.group_id,
            "trx_id": trx_id,
            "trx_type": "post" if not reply_id else "comment",
            "rum_post_id": rum_post_id,
            "rum_post_url": rum_post_url,
            "chat_message_id": update.message.message_id,
            "chat_type": update.message.chat.type,
            "user_id": userid,
            "pubkey": self.rum.account.pubkey,
        }
        self.db.add_or_update(Relation, payload, "trx_id")

        payload = {
            "user_id": userid,
            "username": username,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, payload, "user_id")
        # send reply
        if reply_id is None:
            reply = f"Success to rum group blockchain"
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "Click here to view", "url": rum_post_url}]
                ]
            }
            resp = self.tg.send_message(
                chat_id=update.message.chat.id,
                text=reply,
                parse_mode="HTML",
                reply_markup=reply_markup,
                reply_to_message_id=update.message.message_id,
            )
            logger.debug("send reply done\n\n%s\n", resp)

    def run(self):
        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text & ~Filters.command & Filters.chat_type.private,
                self.handle_private_chat,
            )
        )

        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text & ~Filters.command & Filters.sender_chat.channel,
                self.handle_channel_message,
            )
        )

        self.dispatcher.add_handler(
            MessageHandler(
                Filters.text & ~Filters.command & Filters.sender_chat.super_group,
                self.handle_group_message,
            )
        )

        self.updater.start_polling()
        self.updater.idle()
