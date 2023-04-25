import logging

from quorum_mininode_py.crypto import account
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rum_with_telegram.module import Base, Relation, User

logger = logging.getLogger(__name__)


class DBHandle:
    def __init__(self, db_url: str, echo: bool = False):
        logger.info("db_url: %s", db_url)
        self.engine = create_engine(db_url, echo=echo)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def init_user(self, userid, username=None, pvtkey=None, is_cover=False):
        _user = self.get_first(User, {"user_id": userid}, "user_id")
        if _user and not is_cover:
            return _user
        pvtkey = pvtkey or account.create_private_key()

        try:
            pubkey = account.private_key_to_pubkey(pvtkey)
            address = account.private_key_to_address(pvtkey)
        except Exception as err:
            logger.error("init_user: %s", err)
            return None

        user = {
            "user_id": userid,
            "username": username,
            "pvtkey": pvtkey,
            "pubkey": pubkey,
            "address": address,
        }
        self.add_or_update(User, user, "user_id")
        return self.get_first(User, {"user_id": userid}, "user_id")

    def get_first(self, table, payload: dict, pk: str):
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).first()

    def get_all(self, table, payload: dict, pk: str):
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).all()

    def get_trx_sent(self, channel_message_id):
        with self.Session() as session:
            relatins = (
                session.query(Relation).filter_by(channel_message_id=channel_message_id).all()
            )
            for i in relatins:
                if i.trx_id:
                    return i
        return None

    def is_exist(self, table, payload: dict, pk: str):
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).count() > 0

    def add_or_update(self, table, payload, pk):
        with self.Session() as session:
            obj = session.query(table).filter_by(**{pk: payload[pk]}).first()
            if obj:
                session.query(table).filter_by(**{pk: payload[pk]}).update(payload)
                logger.info("update to db: %s %s", pk, payload[pk])
            else:
                obj = table(**payload)
                session.add(obj)
                logger.info("add to db: %s %s", pk, payload[pk])
            try:
                session.commit()
            except Exception as err:
                session.rollback()
                logger.info(err)
