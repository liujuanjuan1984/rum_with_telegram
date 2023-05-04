import json
import os
from dataclasses import dataclass


@dataclass
class Config:
    # database url
    DB_URL: str
    # the base url of feed
    FEED_URL_BASE: str
    # the title of feed
    FEED_TITLE: str
    RUM_SEED: str
    TG_BOT_TOKEN: str
    TG_BOT_NAME: str
    TG_CHANNEL_NAME: str
    TG_GROUP_NAME: str
    # list of telegram userid who is admin for this service
    ADMIN_USERIDS: list = None
    # blacklist of public keys of rum group, whos trxs cannot be packed to block
    BLACK_LIST_PUBKEYS: list = None
    # blacklist of telegram userids who cannot use this service
    BLACK_LIST_TGIDS: list = None
    # whether to print sql statements
    DB_ECHO: bool = False
    # the default private key of this service to send trx
    ETH_PVTKEY: str = None
    RUM_DELAY_HOURS: int = -3
    RUM_POST_FOOTER: str = ""
    RUM_TO_TG_TAG: str = ""
    RUM_TO_TG: bool = True
    TG_REPLY_POSTURL: bool = True
    TG_USER_ID: int = None
    TG_CHANNEL_URL: str = None  # the url of telegram url
    TG_CHANNEL_ID: int = None
    TG_GROUP_ID: int = None

    def __post_init__(self):
        if self.TG_CHANNEL_URL is None:
            name = self.TG_CHANNEL_NAME.replace("@", "")
            self.TG_CHANNEL_URL = f"https://t.me/{name}"
        self.ADMIN_USERIDS = self.ADMIN_USERIDS or []
        self.BLACK_LIST_PUBKEYS = self.BLACK_LIST_PUBKEYS or []
        self.BLACK_LIST_TGIDS = self.BLACK_LIST_TGIDS or []


def read_json(json_file: str):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def write_json(json_file: str, data: dict):
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return data


def get_config(json_file: str):
    if not os.path.exists(json_file):
        raise FileNotFoundError(f"Config file not found: {json_file}")
    data = read_json(json_file)
    config = Config(**data)
    return config
