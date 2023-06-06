import asyncio
import logging
import os
import sys

# sys.path.insert(0, "./rum_with_telegram")
from rum_with_telegram import DataExchanger

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

args = sys.argv[1:]
if args:
    config_file = args[0]
else:
    config_file = "config.json"

asyncio.run(DataExchanger(config_file).set_commands())
