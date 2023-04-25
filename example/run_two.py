import asyncio
import logging

from config import Config

from rum_with_telegram import DataExchanger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


config = Config()
asyncio.run(DataExchanger(config).handle_rum())
