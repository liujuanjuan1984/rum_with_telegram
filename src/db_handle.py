import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.module import Base

logger = logging.getLogger(__name__)


class DBHandle:
    def __init__(self, db_url: str, echo: bool = False):
        logger.info("db_url: %s", db_url)
        self.engine = create_engine(db_url, echo=echo)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def get_first(self, table, payload: dict, pk: str):
        logger.info("start get_first:  %s %s", pk, payload[pk])
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).first()

    def get_all(self, table, payload: dict, pk: str):
        logger.info("start get_all:  %s %s", pk, payload[pk])
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).all()

    def is_exist(self, table, payload: dict, pk: str):
        logger.info("start is_exist: %s %s", pk, payload[pk])
        with self.Session() as session:
            return session.query(table).filter_by(**{pk: payload[pk]}).count() > 0

    def add_or_update(self, table, payload, pk):
        logger.info("start add_or_update: %s %s", pk, payload[pk])
        with self.Session() as session:
            obj = session.query(table).filter_by(**{pk: payload[pk]}).first()
            if obj:
                logger.info("update to db:\n%s", payload)
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
