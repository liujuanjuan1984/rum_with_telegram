import json
import logging
import os

import telegram
from quorum_data_py import feed
from quorum_mininode_py import MiniNode
from telegram.ext import Filters, MessageHandler, Updater

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
        self.updater = Updater(token=self.config.TG_BOT_TOKEN, use_context=True)
        self.data = read_datafile(self.config.DATA_FILE)
        self.dispatcher = self.updater.dispatcher

    def send_to_rum(self, text: str, reply_id=None, pvtkey=None):
        """send text as trx to rum group chain"""
        if not text:  # 不处理空消息
            raise ValueError("text is empty")
        if pvtkey:
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
            raise ValueError("send to rum failed %s", resp)
        trx_id = resp["trx_id"]
        post_id = data["object"]["id"]
        # TODO:对回复的回复，需要找到最原始的 post_id .. 所以要对 post_id 生成映射表
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
        trx_id, post_id, post_url = self.send_to_rum(
            text
        )  # TODO:为 telegram id 映射 pvtkey
        resp = self.tg.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)
        # update datafile
        self.data["channel"][str(resp.message_id)] = {
            "trx_id": trx_id,
            "post_id": post_id,
            "post_url": post_url,
        }
        with open(self.config.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)
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
                logger.warn(
                    "%s message not from channel %s",
                    from_user,
                    self.config.TG_CHANNEL_NAME,
                )
            text = f"{update.channel_post.text}\nFrom tg channel @{from_user}"
            # TODO:如果该消息没有发送到 rum group 时才发送。需要检查。
            trx_id, post_id, post_url = self.send_to_rum(text)  # todo:pvtkey
            self.data["channel"][str(update.channel_post.message_id)] = {
                "trx_id": trx_id,
                "post_id": post_id,
                "post_url": post_url,
            }
            with open(self.config.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        elif update.message:
            logger.info("message")
            mid = str(update.message.forward_from_message_id)
            mid2 = str(update.message.message_id)
            # message from channel to chat-group
            if mid in self.data["channel"] and mid2 not in self.data["chat"]:
                reply = f"Success: to rum group {self.data['channel'][mid]['post_url']}"
                resp = self.tg.send_message(
                    chat_id=update.message.chat.id,
                    text=reply,
                    reply_to_message_id=update.message.message_id,
                )
                logger.info("send_message done %s", resp)
                self.data["chat"][mid2] = self.data["channel"][mid]
        else:
            logger.info("!!!! Todo: unknown update %s", update)

    def handle_group_message(self, update, context):
        logger.info("handle_group_message %s", update)
        text = f"{update.message.text}\nFrom tg user @{update.message.from_user.username} through group {self.config.TG_GROUP_NAME}"

        reply_id = None
        if update.message.reply_to_message:
            _mid = str(update.message.reply_to_message.message_id)
            reply_id = self.data["chat"].get(_mid, {}).get("post_id")
        else:
            pinned = self.tg.get_chat(self.config.TG_GROUP_ID).pinned_message
            logger.info("pinned message %s", pinned)
            _mid = str(pinned.forward_from_message_id)
            if pinned:
                reply_id = self.data["channel"].get(_mid, {}).get("post_id")

        trx_id, post_id, post_url = self.send_to_rum(text, reply_id)
        self.data["chat"][str(update.message.message_id)] = {
            "trx_id": trx_id,
            "post_id": post_id,
            "post_url": post_url,
        }
        with open(self.config.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

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