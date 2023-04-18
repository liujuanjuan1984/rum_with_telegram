from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Relation(Base):
    """the map between trx and messages"""

    __tablename__ = "relations"

    id = Column(Integer, primary_key=True)
    group_id = Column(String, default=None)
    trx_id = Column(String, unique=True, index=True, default=None)
    trx_type = Column(String, default=None)  # rum
    post_id = Column(String, default=None)  # rum
    chat_type = Column(String, default=None)
    chat_id = Column(Integer, index=True, default=None)
    message_type = Column(String, default=None)
    message_id = Column(Integer, index=True, default=None)
    post_url = Column(String, default=None)
    user_id = Column(String, default=None)  # telegram user id
    username = Column(String, default=None)  # telegram user name
    pubkey = Column(String, default=None)  # rum group pubkey
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("group_id", "trx_id"),
        UniqueConstraint("chat_type", "chat_id"),
        UniqueConstraint("message_type", "message_id"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, default=None)
    username = Column(String, index=True, default=None)
    pvtkey = Column(String, unique=True, default=None)
    pubkey = Column(String, unique=True, default=None)
    address = Column(String, unique=True, default=None)
    first_name = Column(String, default=None)
    last_name = Column(String, default=None)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
