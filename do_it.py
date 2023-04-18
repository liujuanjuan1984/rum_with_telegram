import logging
import os

from src import DataExchanger

logging.basicConfig(
    level=logging.INFO, format="%(name)s - %(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


basedir = os.path.dirname(__file__)
logger.info("basedir: %s", basedir)


class Config:
    RUM_SEED = "rum://seed?v=1&e=0&n=0&c=qOh_wTyuoKDoXxxxxxIaH5sa9TCLPkHCnpnROM8"
    ETH_PVTKEY = "0x5ee77ca3...effaf"
    FEED_URL_BASE = "https://example/posts/"
    TG_USER_ID = 123456789
    TG_CHANNEL_NAME = "@my_channel"
    TG_BOT_TOKEN = "1234566767:mybotkey"  # bot token
    TG_BOT_NAME = "@MyBotName"
    TG_GROUP_NAME = "@my_group"
    TG_GROUP_ID = -10012345678
    DB_URL = f"sqlite3:///{basedir}/test_db.sqlite"
    DB_ECHO = False


if __name__ == "__main__":
    config = Config()
    DataExchanger(config).run()
