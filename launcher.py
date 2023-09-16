from __future__ import annotations

import os
import asyncio
import aiob2
import mystbin
import logging
import pathlib
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import aiohttp
import asyncpg
import toml
from colorama import Fore, Style

from utils.sonarr import Client as SonarrClient
from cogs import EXTENSIONS
from bot import Bot, Config

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.info(f'{Fore.GREEN} Successfully installed uvloop.{Style.RESET_ALL}')
except Exception as e:
    logging.info(f'{Fore.RED} Failed to install uvloop.{Style.RESET_ALL}\n{e}')
    pass

os.environ['JISHAKU_FORCE_PAGINATOR'] = 'True'
os.environ['JISHAKU_NO_UNDERSCORE'] = 'True'
os.environ['JISHAKU_NO_DM_TRACEBACK'] = 'True'
os.environ['JISHAKU_HIDE'] = 'True'


file_path = Path(__file__).resolve().parent / "config.toml"
with open(file_path, "r") as file:
    config: Config = toml.load(file)  # type: ignore


class RemoveNoise(logging.Filter):
    def __init__(self) -> None:
        super().__init__(name="discord.state")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelname == "WARNING" and "referencing an unknown" in record.msg:
            return False
        return True


class ColourFormatter(logging.Formatter):

    # ANSI codes are a bit weird to decipher if you're unfamiliar with them, so here's a refresher
    # It starts off with a format like \x1b[XXXm where XXX is a semicolon separated list of commands
    # The important ones here relate to colour.
    # 30-37 are black, red, green, yellow, blue, magenta, cyan and white in that order
    # 40-47 are the same except for the background
    # 90-97 are the same but "bright" foreground
    # 100-107 are the same as the bright ones but for the background.
    # 1 means bold, 2 means dim, 0 means reset, and 4 means underline.

    LEVEL_COLOURS = [
        (logging.DEBUG, '\x1b[40;1m'),
        (logging.INFO, '\x1b[32;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    FORMATS = {
        level: logging.Formatter(
            f'[\x1b[30;1m%(asctime)s\x1b[0m][ {colour}%(levelname)-8s\x1b[0m] \x1b[31m%(name)s\x1b[0m %(message)s',
            '%Y-%m-%d %H:%M:%S',
        )
        for level, colour in LEVEL_COLOURS
    }

    def format(self, record):
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        # Override the traceback to always print in red
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f'\x1b[31m{text}\x1b[0m'

        output = formatter.format(record)

        # Remove the cache layer
        record.exc_text = None
        return output


class SetupLogging:
    def __init__(self, *, stream: bool = True) -> None:
        self.log: logging.Logger = logging.getLogger()
        self.max_bytes: int = 32 * 1024
        self.logging_path = pathlib.Path("./logs/")
        self.logging_path.mkdir(exist_ok=True)
        self.stream: bool = stream

    def __enter__(self):
        logging.getLogger("discord").setLevel(logging.INFO)
        logging.getLogger("discord.http").setLevel(logging.WARNING)
        logging.getLogger('aiob2').setLevel(logging.DEBUG)
        logging.getLogger('utils.sonarr').setLevel(logging.DEBUG)
        logging.getLogger("discord.state").addFilter(RemoveNoise())

        self.log.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            filename=self.logging_path / "bot.log", encoding="utf-8", mode="w", maxBytes=self.max_bytes, backupCount=5
        )
        fmt = ColourFormatter()
        handler.setFormatter(fmt)
        self.log.addHandler(handler)

        if self.stream:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(fmt)
            self.log.addHandler(stream_handler)

        return self

    def __exit__(self, *args: Any) -> None:
        handlers = self.log.handlers[:]
        for hdlr in handlers:
            hdlr.close()
            self.log.removeHandler(hdlr)


def _encode_jsonb(value):
    return json.dumps(value)


def _decode_jsonb(value):
    return json.loads(value)


async def init(conn):
    await conn.set_type_codec(
        'jsonb',
        schema='pg_catalog',
        encoder=_encode_jsonb,
        decoder=_decode_jsonb,
        format='text'
    )


async def main():
    async with Bot(config) as bot:
        pool = await asyncpg.create_pool(**config['database'], init=init)

        if pool is None:
            # thanks asyncpg...
            raise RuntimeError("Could not connect to database.")
        bot.pool = pool

        session = aiohttp.ClientSession()
        bot.session = session

        bot.bucket = aiob2.Client(config['backblaze']['key_id'], config['backblaze']['key'], log_handler=None)
        bot.mystbin = mystbin.Client()
        bot.sonarr = SonarrClient(**config['sonarr'])

        await bot.load_extension("jishaku")
        for extension in EXTENSIONS:
            await bot.load_extension(extension)

        with SetupLogging(stream=False):
            asyncio.create_task(bot.startup_message())

            await bot.start(bot.config['token'])

if __name__ == '__main__':
    asyncio.run(main())