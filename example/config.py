import os

basedir = os.path.dirname(__file__)


class Config:
    RUM_SEED = "rum://seed?v=1&e=0&n=0&c=qOh_wTyuoKDoXxxxxxIaH5sa9TCLPkHCnpnROM8"
    ETH_PVTKEY = "0x5ee77ca3...effaf"
    FEED_URL_BASE = "https://example.com"
    FEED_TITLE = "My Feed"
    TG_USER_ID = 123456789
    TG_CHANNEL_NAME = "@my_channel"
    TG_CHANNEL_URL = "https://t.me/my_channel"
    TG_CHANNEL_ID = -100123456678
    TG_BOT_TOKEN = "1234566767:mybotkey"  # bot token
    TG_BOT_NAME = "@MyBotName"
    TG_GROUP_NAME = "@my_group"
    TG_GROUP_ID = -1001234567876
    DB_URL = f"sqlite3:///{basedir}/test_db.sqlite"
    DB_ECHO = False
    RUM_DELAY_HOURS = -1
    BLACK_LIST_PUBKEYS = []
    BLACK_LIST_TGIDS = []
