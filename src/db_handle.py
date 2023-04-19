import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.module import Base, Relation

logger = logging.getLogger(__name__)


class DBHandle:
    def __init__(self, db_url: str, echo: bool = False):
        logger.info("db_url: %s", db_url)
        self.engine = create_engine(db_url, echo=echo)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def get_first(self, table, payload: dict, pk: str):
        logger.debug("start get_first:  %s\n%s", pk, payload)
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).first()

    def get_all(self, table, payload: dict, pk: str):
        logger.debug("start get_all:  %s\n%s", pk, payload)
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).all()

    def get_trx_sent(self, channel_message_id):
        logger.debug("start get_post_id:  %s", channel_message_id)
        with self.Session() as session:
            relatins = (
                session.query(Relation)
                .filter_by(channel_message_id=channel_message_id)
                .all()
            )
            for i in relatins:
                if i.trx_id:
                    return i
        return None

    def is_exist(self, table, payload: dict, pk: str):
        logger.debug("start is_exist: %s\n%s", pk, payload)
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).count() > 0

    def add_or_update(self, table, payload, pk):
        logger.debug("start add_or_update: %s\n%s", pk, payload)
        with self.Session() as session:
            obj = session.query(table).filter_by(**{pk: payload[pk]}).first()
            if obj:
                logger.debug("update to db:\n%s", payload)
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
