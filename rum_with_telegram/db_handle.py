import logging

from quorum_mininode_py import RumAccount
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from rum_with_telegram.module import Base, Relation, UsedKey, User

logger = logging.getLogger(__name__)


class DBHandle:
    def __init__(self, db_url: str, echo: bool = False):
        logger.info("db_url: %s", db_url)
        self.engine = create_engine(db_url, echo=echo)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def init_user(self, userid, username=None, pvtkey=None, is_cover=False):
        _user = self.get_first_user(userid)
        if _user:
            if not is_cover:
                return _user
            used = {"user_id": userid, "pvtkey": _user.pvtkey}
            self.add_or_update(UsedKey, used, "user_id")
        account = RumAccount(pvtkey=pvtkey)
        user = {
            "user_id": userid,
            "username": username,
            "pvtkey": account.pvtkey,
            "pubkey": account.pubkey,
            "address": account.address,
        }
        self.add_or_update(User, user, "user_id")
        return self.get_first_user(userid)

    def get_first(self, table, payload: dict, pk: str):
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).first()

    def get_first_user(self, userid):
        return self.get_first(User, {"user_id": userid}, "user_id")

    def get_all(self, table, payload: dict, pk: str):
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).all()

    def get_trx_sent_by(self, channel_message_id, chat_type):
        with self.Session() as session:
            relations = (
                session.query(Relation)
                .filter_by(channel_message_id=channel_message_id, chat_type=chat_type)
                .all()
            )
            for relation in relations:
                if relation and relation.trx_id:
                    return relation
            return None

    def get_trx_sent(self, channel_message_id):
        relation = self.get_trx_sent_by(channel_message_id, None)
        if not relation:
            relation = self.get_trx_sent_by(channel_message_id, "private")
        if not relation:
            relation = self.get_trx_sent_by(channel_message_id, "supergroup")
        return relation

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

    def update_user_export_at(self, userid):
        return self.add_or_update(User, {"user_id": userid, "export_at": func.now()}, "user_id")
