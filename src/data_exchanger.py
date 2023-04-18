import json
import logging
import os

import telegram
from quorum_data_py import feed
from quorum_mininode_py import MiniNode
from telegram.ext import Filters, MessageHandler, Updater

from src.db_handle import DBHandle
from src.module import Relation, User

logger = logging.getLogger(__name__)


def read_datafile(datafile: str):
    if os.path.exists(datafile):
        with open(datafile, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"channel": {}, "chat": {}}
        with open(datafile, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    return data


class DataExchanger:
    """the data exchanger between telegram bot/channel/chat-group and rum group-chain"""

    def __init__(self, config):
        self.config = config
        self.rum = MiniNode(self.config.RUM_SEED, self.config.ETH_PVTKEY)
        self.tg = telegram.Bot(token=self.config.TG_BOT_TOKEN)
        self.db = DBHandle(self.config.DB_URL, echo=self.config.DB_ECHO)
        self.updater = Updater(token=self.config.TG_BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher

    def send_to_rum(self, text: str, reply_id=None, pvtkey=None):
        """send text as trx to rum group chain"""
        if not text:
            raise ValueError("text is empty")
        self.rum.change_account(pvtkey)
        logger.info(
            "rum account changed from %s to %s", self.rum.account.pvtkey, pvtkey
        )
        if reply_id:
            data = feed.reply(content=text, reply_id=reply_id)
        else:
            data = feed.new_post(content=text)
        resp = self.rum.api.post_content(data)
        if "trx_id" not in resp:
            raise ValueError(f"send to rum failed {resp}")
        trx_id = resp["trx_id"]
        post_id = data["object"]["id"]
        post_url = f"{self.config.FEED_URL_BASE}{reply_id or post_id}"
        logger.info("success: send_to_rum %s", trx_id)
        return trx_id, post_id, post_url

    def send_to_channel(self, text: str, chat_id=None):
        """send text to telegram channel"""
        chat_id = chat_id or self.config.TG_CHANNEL_NAME
        resp = self.tg.send_message(chat_id=chat_id, text=text)
        logger.info("send_to_channel %s", resp)
        return resp

    def handle_private_chat(self, update, context):
        """send message to rum group and telegram channel"""
        logger.info("handle_private_chat %s", update)
        message = update.message
        text = f"{message.text}\nFrom tg user @{ message.from_user.username} through bot {self.config.TG_BOT_NAME}"
        user = self.db.get_first(
            User, {"username": message.from_user.username}, "username"
        )
        if user:
            pvtkey = user.pvtkey
        else:
            pvtkey = None
        trx_id, post_id, post_url = self.send_to_rum(text, None, pvtkey)
        resp = self.tg.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)
        relation = {
            "group_id": self.rum.group.group_id,
            "trx_id": trx_id,
            "trx_type": "post",
            "post_id": post_id,
            "chat_type": "private",
            "chat_id": message.message_id,
            "message_id": resp.message_id,
            "message_type": "channel",
            "post_url": post_url,
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "pubkey": self.rum.account.pubkey,
        }
        self.db.add_or_update(Relation, relation, "trx_id")

        user = {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, user, "user_id")

        # reply to user
        reply = f"Success: to rum group {post_url} and telegram channel {self.config.TG_CHANNEL_NAME}"
        resp = self.tg.send_message(
            chat_id=message.from_user.id,
            text=reply,
            reply_to_message_id=message.message_id,
        )
        logger.info("send_message done %s", resp)

    def handle_channel_message(self, update, context):
        """send message to rum group"""
        logger.info("handle_channel_message %s", update)
        # channel post to rum group chain
        if update.channel_post:
            logger.info("channel_post")
            from_user = update.channel_post.chat.username
            if from_user != self.config.TG_CHANNEL_NAME.lstrip("@"):
                logger.warning(
                    "%s message not from channel %s",
                    from_user,
                    self.config.TG_CHANNEL_NAME,
                )
            text = f"{update.channel_post.text}\nFrom tg channel @{from_user}"
            user = self.db.get_first(User, {"username": from_user}, "username")
            if user:
                pvtkey = user.pvtkey
            else:
                pvtkey = None
            trx_id, post_id, post_url = self.send_to_rum(text, None, pvtkey)

            relation = {
                "group_id": self.rum.group.group_id,
                "trx_id": trx_id,
                "trx_type": "post",
                "post_id": post_id,
                "message_id": update.channel_post.message_id,
                "message_type": "channel",
                "post_url": post_url,
                "username": from_user,
                "pubkey": self.rum.account.pubkey,
            }
            self.db.add_or_update(Relation, relation, "trx_id")

            user = {
                "username": from_user,
                "pvtkey": self.rum.account.pvtkey,
                "pubkey": self.rum.account.pubkey,
                "address": self.rum.account.address,
            }
            self.db.add_or_update(User, user, "username")

        elif update.message:
            logger.info("message")
            # message from channel to chat-group
            post_url = self.db.get_first(
                Relation,
                {"message_id": update.message.forward_from_message_id},
                "message_id",
            ).post_url
            reply = f"Success: to rum group {post_url}"
            resp = self.tg.send_message(
                chat_id=update.message.chat.id,
                text=reply,
                reply_to_message_id=update.message.message_id,
            )
            logger.info("send_message done %s", resp)

            relation = {
                "chat_id": update.message.message_id,
                "chat_type": "group",
                "message_id": update.message.forward_from_message_id,
                "message_type": "channel",
            }
            self.db.add_or_update(Relation, relation, "message_id")
        else:
            logger.warning("!!!! Todo: unknown update %s", update)

    def handle_group_message(self, update, context):
        logger.info("handle_group_message %s", update)
        text = f"{update.message.text}\nFrom tg user @{update.message.from_user.username} through group {self.config.TG_GROUP_NAME}"

        reply_id = None
        if update.message.reply_to_message:
            _chat_id = update.message.reply_to_message.message_id
            reply_id = self.db.get_first(
                Relation, {"chat_id": _chat_id}, "chat_id"
            ).post_id
        else:
            _pinned_id = self.tg.get_chat(
                self.config.TG_GROUP_ID
            ).pinned_message.forward_from_message_id

            reply_id = self.db.get_first(
                Relation, {"message_id": _pinned_id}, "message_id"
            ).post_id

        user = self.db.get_first(
            User, {"user_id": update.message.from_user.id}, "user_id"
        )
        if user:
            pvtkey = user.pvtkey
        else:
            pvtkey = None
        trx_id, post_id, post_url = self.send_to_rum(text, reply_id, pvtkey)

        relation = {
            "group_id": self.rum.group.group_id,
            "trx_id": trx_id,
            "trx_type": "post" if not reply_id else "comment",
            "post_id": post_id,
            "post_url": post_url,
            "chat_id": update.message.message_id,
            "chat_type": "group",
            "username": update.message.from_user.username,
            "pubkey": self.rum.account.pubkey,
        }
        self.db.add_or_update(Relation, relation, "trx_id")

        user = {
            "user_id": update.message.from_user.id,
            "username": update.message.from_user.username,
            "pvtkey": self.rum.account.pvtkey,
            "pubkey": self.rum.account.pubkey,
            "address": self.rum.account.address,
        }
        self.db.add_or_update(User, user, "user_id")

        reply = f"Success: to rum group {post_url}"
        resp = self.tg.send_message(
            chat_id=update.message.chat.id,
            text=reply,
            reply_to_message_id=update.message.message_id,
        )
        logger.info("send_message done %s", resp)

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
