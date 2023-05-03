import json
import os
from dataclasses import dataclass


@dataclass
class Config:
    BLACK_LIST_PUBKEYS: list
    BLACK_LIST_TGIDS: list
    ADMIN_USERIDS: list
    RUM_SEED: str
    ETH_PVTKEY: str
    FEED_URL_BASE: str
    FEED_TITLE: str
    TG_CHANNEL_NAME: str
    TG_CHANNEL_URL: str
    TG_BOT_TOKEN: str
    TG_BOT_NAME: str
    TG_GROUP_NAME: str
    DB_URL: str
    DB_ECHO: bool
    RUM_DELAY_HOURS: int
    RUM_POST_FOOTER: str
    TG_REPLY_POSTURL: bool
    TG_USER_ID: int
    TG_CHANNEL_ID: int = None
    TG_GROUP_ID: int = None


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
