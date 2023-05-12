from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Relation(Base):
    """the map between trx and messages"""

    __tablename__ = "relations"

    id = Column(Integer, primary_key=True)
    group_id = Column(String, default=None)  # rum
    trx_id = Column(String, index=True, default=None)  # rum
    trx_type = Column(String, default=None)  # rum
    rum_post_id = Column(String, default=None)
    rum_post_url = Column(String, default=None)
    chat_type = Column(String, default=None)  # tg
    chat_message_id = Column(Integer, index=True, default=None)  # tg
    channel_message_id = Column(Integer, index=True, default=None)  # tg
    user_id = Column(String, default=None)  # tg
    pubkey = Column(String, default=None)  # rum
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    __table_args__ = (UniqueConstraint("chat_type", "chat_message_id"),)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, default=None)
    username = Column(String, index=True, default=None)
    pvtkey = Column(String, unique=True, default=None)
    pubkey = Column(String, unique=True, default=None)
    address = Column(String, unique=True, default=None)
    export_at = Column(DateTime, default=None)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class UsedKey(Base):
    __tablename__ = "used_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    pvtkey = Column(String)
