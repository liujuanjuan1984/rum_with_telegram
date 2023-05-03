import asyncio
import base64
import datetime
import logging

from quorum_data_py import feed, get_trx_type, util
from quorum_mininode_py import MiniNode
from quorum_mininode_py.crypto import account
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from rum_with_telegram.config import get_config
from rum_with_telegram.db_handle import DBHandle
from rum_with_telegram.module import Relation

logger = logging.getLogger(__name__)


class DataExchanger:
    """the data exchanger between telegram bot/channel/chat-group and rum group-chain"""

    def __init__(self, config: dict = None, json_config_file: str = None):
        if isinstance(config, str):
            json_config_file = config
            config = None
        self.config = config or get_config(json_config_file)
        if not self.config:
            raise Exception("config is None")
        self.rum = MiniNode(self.config.RUM_SEED, self.config.ETH_PVTKEY)
        self.app = Application.builder().token(self.config.TG_BOT_TOKEN).build()
        self.db = DBHandle(self.config.DB_URL, echo=self.config.DB_ECHO)
        self.start_trx = None

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

    async def send_to_rum(
        self,
        context,
        message,
        userid,
        username=None,
        reply_id=None,
        origin=None,
    ):
        """send text as trx to rum group chain"""
        logger.info("start send_to_rum")
        user = self.db.init_user(userid, username)
        self.rum.change_account(user.pvtkey)

        text = message.text or message.caption or ""
        if message.photo:
            image = await context.bot.get_file(message.photo[-1].file_id)
            image = bytes(await image.download_as_bytearray())
        else:
            image = None
        images = [image] if image else None
        if reply_id:
            data = feed.reply(content=text, images=images, reply_id=reply_id)
        else:
            text += f" {self.config.RUM_POST_FOOTER}"
            data = feed.new_post(content=text, images=images)
        if origin:
            data["origin"] = {
                "type": "telegram",
                "name": self.config.TG_CHANNEL_NAME,
                "url": f"{self.config.TG_CHANNEL_URL}/{origin}",
            }

        resp = self.rum.api.post_content(data)
        post_id = self._get_origin_post_id(reply_id) or data["object"]["id"]
        rum_post_url = f"{self.config.FEED_URL_BASE}/posts/{post_id}"
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

    async def _comment_with_feedurl(
        self,
        context,
        extend_text: str,
        userid,
        reply_to_message_id,
        rum_post_url,
    ):
        """reply to user with rum post url"""
        if not self.config.TG_REPLY_POSTURL:
            return
        reply = f"⚜️ Success to blockchain.\n👉[{self.config.FEED_TITLE}]({rum_post_url})" + (
            extend_text or ""
        )
        await context.bot.send_message(
            chat_id=userid,
            text=reply,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_to_message_id=reply_to_message_id,
        )
        logger.info("send reply done")

    async def handle_rum(self):
        if self.start_trx is None:
            trxs = self.rum.api.get_content(num=20, reverse=True)
            if trxs:
                self.start_trx = trxs[-1]["TrxId"]
        _trx_id = self.start_trx
        while True:
            if self.start_trx != _trx_id:
                logger.info("handle_rum %s", self.start_trx)
                _trx_id = self.start_trx
            start_trx = await self._handle_rum(self.start_trx)
            if start_trx == self.start_trx:
                await asyncio.sleep(5)
            self.start_trx = start_trx

    async def _handle_rum(self, start_trx):
        trxs = self.rum.api.get_content(num=20, start_trx=start_trx)
        for trx in trxs:
            start_trx = trx["TrxId"]
            if trx["SenderPubkey"] in self.config.BLACK_LIST_PUBKEYS:
                continue
            if get_trx_type(trx) != "post":
                continue
            trx_dt = util.get_published_datetime(trx)
            if trx_dt < datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                hours=self.config.RUM_DELAY_HOURS
            ):
                continue
            origin_url = trx["Data"].get("origin", {}).get("url", "")
            if self.config.TG_CHANNEL_URL in origin_url:
                continue
            _text = trx["Data"]["object"].get("content", "")
            _images = trx["Data"]["object"].get("image", [])
            if not _text and not _images:
                continue
            if self.db.is_exist(Relation, {"trx_id": trx["TrxId"]}, "trx_id"):
                continue
            post_url = f'{self.config.FEED_URL_BASE}/posts/{trx["Data"]["object"]["id"]}'
            logger.info("new post from rum %s", post_url)
            relation = {
                "group_id": self.rum.group.group_id,
                "trx_id": trx["TrxId"],
                "rum_post_id": trx["Data"]["object"]["id"],
                "rum_post_url": post_url,
                "user_id": self.config.TG_CHANNEL_ID,
                "pubkey": trx["SenderPubkey"],
                "trx_type": "post",
            }
            if _images:
                if isinstance(_images, dict):
                    _images = [_images]
                for i, _image in enumerate(_images):
                    resp = await self.app.bot.send_photo(
                        chat_id=self.config.TG_CHANNEL_NAME,
                        photo=base64.b64decode(_image["content"].encode("utf-8")),
                        caption=f"{i+1}/{len(_images)} {_text}",
                    )
                    relation.update(
                        {
                            "channel_message_id": resp.message_id,
                        }
                    )
                    self.db.add_or_update(Relation, relation, "trx_id")
            elif _text:
                resp = await self.app.bot.send_message(
                    chat_id=self.config.TG_CHANNEL_NAME,
                    text=_text,
                )
                relation.update(
                    {
                        "channel_message_id": resp.message_id,
                    }
                )
                self.db.add_or_update(Relation, relation, "trx_id")
            await asyncio.sleep(1)
        return start_trx

    async def handle_private_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """send message to rum group and telegram channel"""
        message_id = update.message.message_id
        logger.info("handle_private_chat %s", message_id)
        userid = update.message.from_user.id
        if userid in self.config.BLACK_LIST_TGIDS:
            await context.bot.send_message(
                chat_id=userid,
                text="You are in the blacklist.",
                reply_to_message_id=update.message.message_id,
            )
            return
        _first_name = update.message.from_user.first_name
        _last_name = update.message.from_user.last_name
        _fullname = f"{_first_name} {_last_name}" if _last_name else _first_name
        _text = update.message.text or update.message.caption or ""
        if _text.startswith("/profile"):
            await self.command_profile(update, context)
            return
        text = f"{_text}\n\nFrom {_fullname} through {self.config.TG_BOT_NAME}"
        _photo = update.message.photo
        if _photo:
            image = await context.bot.get_file(_photo[-1].file_id)
            image = bytes(await image.download_as_bytearray())
            resp = await context.bot.send_photo(
                chat_id=self.config.TG_CHANNEL_NAME, photo=image, caption=text
            )
        else:
            image = None
            text = f"{_text}\nFrom {_fullname} through {self.config.TG_BOT_NAME}"
            resp = await context.bot.send_message(chat_id=self.config.TG_CHANNEL_NAME, text=text)

        relation = await self.send_to_rum(
            context,
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
        await self._comment_with_feedurl(
            context,
            f" and to [{self.config.TG_CHANNEL_NAME}]({self.config.TG_CHANNEL_URL}/{resp.message_id})",
            userid,
            message_id,
            relation.get("rum_post_url"),
        )

    async def _handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """send message to rum group"""
        logger.info("handle_channel_post %s", update.channel_post.message_id)
        # channel post to rum group chain
        userid = update.channel_post.chat.id
        # send to rum
        relation = await self.send_to_rum(
            context,
            update.channel_post,
            userid,
            update.channel_post.chat.username,
            origin=update.channel_post.message_id,
        )
        relation.update(
            {
                "channel_message_id": update.channel_post.message_id,
            }
        )
        self.db.add_or_update(Relation, relation, "trx_id")

    async def handle_channel_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """send message to rum group"""
        # channel post to rum group chain
        if update.channel_post:
            await self._handle_channel_post(update, context)
            return
        logger.info("handle_channel_message %s", update.message.message_id)
        channel_message_id = update.message.forward_from_message_id
        chat_message_id = update.message.message_id

        # send reply to user in group chat
        for i in range(5):
            obj = self.db.get_trx_sent(channel_message_id)
            if not obj:
                await asyncio.sleep(0.5)
                continue
            rum_post_url = obj.rum_post_url
            if not rum_post_url:
                await asyncio.sleep(0.5)
            else:
                break
        if not rum_post_url:
            logger.warning("%s not found channel_message_id %s", i, channel_message_id)
            return
        logger.info("found rum_post_url %s", rum_post_url)
        await self._comment_with_feedurl(
            context, "", update.message.chat.id, chat_message_id, rum_post_url
        )
        payload = {
            "chat_message_id": chat_message_id,
            "chat_type": update.message.chat.type,
            "channel_message_id": channel_message_id,
        }
        self.db.add_or_update(Relation, payload, "chat_message_id")

    async def _handle_reply_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start handle_reply_message %s", update.message.message_id)
        username = update.message.from_user.username
        userid = update.message.from_user.id
        reply_msg = update.message.reply_to_message
        channel_message_id = reply_msg.forward_from_message_id
        reply_chat_message_id = reply_msg.message_id
        reply_id = None
        if channel_message_id:
            obj = self.db.get_trx_sent(channel_message_id)
            reply_id = obj.rum_post_id if obj else None
        elif reply_chat_message_id:
            obj = self.db.get_first(
                Relation,
                {"chat_message_id": reply_chat_message_id},
                "chat_message_id",
            )
            reply_id = obj.rum_post_id if obj else None
            if obj and not channel_message_id:
                channel_message_id = obj.channel_message_id

        if not channel_message_id and not reply_chat_message_id:
            bot = Bot(token=context.bot.token)
            _pinned = await bot.get_chat(self.config.TG_GROUP_ID)
            _pinned = _pinned.pinned_message
            channel_message_id = _pinned.forward_from_message_id
            logger.info("get channel_message_id from pinned %s", channel_message_id)
            reply_id = self.db.get_trx_sent(channel_message_id).rum_post_id
            logger.info("channel_message_id to reply_id %s", reply_id)

        relation = await self.send_to_rum(
            context,
            update.message,
            userid,
            username,
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

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """handle group message"""
        userid = update.message.from_user.id
        if userid in self.config.BLACK_LIST_TGIDS:
            await context.bot.send_message(
                chat_id=userid,
                text="You are in the blacklist.",
                reply_to_message_id=update.message.message_id,
            )
            return

        if update.message.reply_to_message:
            await self._handle_reply_message(update, context)
            return
        logger.info(
            "handle_group_message %s without reply_to_message",
            update.message.message_id,
        )
        username = update.message.from_user.username
        userid = update.message.from_user.id
        bot = Bot(token=context.bot.token)
        _pinned = await bot.get_chat(self.config.TG_GROUP_ID)
        _pinned = _pinned.pinned_message
        channel_message_id = _pinned.forward_from_message_id
        obj = self.db.get_trx_sent(channel_message_id)
        if obj:
            reply_id = obj.rum_post_id
        else:
            reply_id = None

        relation = await self.send_to_rum(
            context,
            update.message,
            userid,
            username,
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

    async def command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start command handler"""
        logger.info("start command_start %s", update.message.message_id)
        username = update.message.from_user.username or ""
        text = f"Hello {username}! I'm {self.config.TG_BOT_NAME}. \nI can send your message (such as text, photo) as a new microblog from telgram to the blockchain of RUM network. \nTry to say something to me."
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            reply_to_message_id=update.message.message_id,
        )

    async def command_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/profile command handler, change user name or avatar for the blockchain of rum network"""
        logger.info("start command_name %s", update.message.message_id)
        _text = update.message.text or update.message.caption or ""
        name = _text.replace("/profile", "").strip(" '\"")
        reply = f"Enter name: ```{name}```\n"

        if len(name) > 32 or len(name) < 2:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text="Change your nickname or avatar for blockchian of rum group.\nUse command as `/profile your-nickname` , nickname should be 2-32 characters, and you can add a picture as avatar.",
                reply_to_message_id=update.message.message_id,
            )
            return
        _photo = update.message.photo
        if _photo:
            image = await context.bot.get_file(_photo[-1].file_id)
            avatar = bytes(await image.download_as_bytearray())
        else:
            avatar = None

        if name or avatar:
            user = self.db.init_user(update.message.from_user.id, update.message.from_user.username)
            address = user.address
            data = feed.profile(name, avatar, address)
            self.rum.change_account(user.pvtkey)
            resp = self.rum.api.post_content(data)
            if "trx_id" in resp:
                reply += f"Profile updated. View {self.config.FEED_URL_BASE}/users/{address}"
            else:
                reply += "Profile update failed. Please try again later."

        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=reply,
            reply_to_message_id=update.message.message_id,
        )

    async def command_show_pvtkey(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start command_show_pvtkey")
        userid = update.message.from_user.id
        username = update.message.from_user.username
        chat_id = update.message.chat_id
        message_id = update.message.message_id
        user = self.db.init_user(userid, username)
        if user:
            text = f"Your private key (please keep it safe) is: \n```\n{user.pvtkey}\n```\nYour Address (can show to others) is:\n```\n{user.address}\n```"
        else:
            text = f"show_key error {userid}"
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id,
            parse_mode="Markdown",
        )

    async def command_new_pvtkey(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start command_new_pvtkey")
        userid = update.message.from_user.id
        username = update.message.from_user.username
        chat_id = update.message.chat_id
        message_id = update.message.message_id
        user = self.db.init_user(userid, username, is_cover=True)
        if user:
            text = f"Your private key (please keep it safe) is: \n```\n{user.pvtkey}\n```\nYour Address (can show to others) is:\n```\n{user.address}\n```"
        else:
            text = f"new_key error {userid}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id,
            parse_mode="Markdown",
        )

    async def command_import_pvtkey(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start command_import_pvtkey")
        userid = update.message.from_user.id
        username = update.message.from_user.username
        chat_id = update.message.chat_id
        message_id = update.message.message_id
        _text = update.message.text or update.message.caption or ""
        pvtkey = _text.replace("/import_pvtkey", "").strip(" '\"")
        text = f"Try to import private key: \n```\n{pvtkey}\n```\n"
        try:
            account.private_key_to_pubkey(pvtkey)
            user = self.db.init_user(userid, username, pvtkey=pvtkey, is_cover=True)
            if user:
                text += "Success. Please keep it safe."
            else:
                text += "Something wrong. Please try again later."
        except Exception as err:
            logger.error(err)
            text += "Please Use command as `/import_key 0x5ee77ca3c261cdd...adeffaf` . Please check your private key and try again."

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id,
            parse_mode="Markdown",
        )

    async def command_my_nft(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start command_my_nft")
        # TODO

    async def command_grant_nft(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("start command_grant_nft")
        userid = update.message.from_user.id
        if userid not in self.config.ADMIN_USERIDS:
            reply = "You are not admin."
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=reply,
                reply_to_message_id=update.message.message_id,
            )
            return
        # TODO

    def run(self):
        self.app.add_handler(CommandHandler("start", self.command_start))
        self.app.add_handler(CommandHandler("profile", self.command_profile))
        self.app.add_handler(CommandHandler("show_pvtkey", self.command_show_pvtkey))
        # TODO: add logs to map userid and pvtkey
        self.app.add_handler(CommandHandler("new_pvtkey", self.command_new_pvtkey))
        self.app.add_handler(CommandHandler("import_pvtkey", self.command_import_pvtkey))
        # TODO:
        self.app.add_handler(CommandHandler("my_nft", self.command_my_nft))
        self.app.add_handler(CommandHandler("grant_nft", self.command_grant_nft))

        content_filter = (filters.TEXT | filters.PHOTO) & ~filters.COMMAND
        # private chat message:
        # send to tg channel and rum group as new post
        # reply the feed_post_url to user in private chat and the comment of the channel post
        self.app.add_handler(
            MessageHandler(
                content_filter & filters.ChatType.PRIVATE,
                self.handle_private_chat,
            )
        )
        # channel message:
        # send to rum group as new post; and reply to user in group chat
        self.app.add_handler(
            MessageHandler(
                content_filter & filters.SenderChat(self.config.TG_CHANNEL_ID),
                self.handle_channel_message,
            )
        )
        # group message:
        # send to rum group as comment of the pinned post or the reply-to post
        self.app.add_handler(
            MessageHandler(
                content_filter & (filters.ChatType.SUPERGROUP | filters.SenderChat.SUPER_GROUP),
                self.handle_group_message,
            )
        )

        self.app.run_polling()
