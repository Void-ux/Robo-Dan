from __future__ import annotations

import asyncio
import aiob2
import mystbin
import datetime
import json
import logging
import os
import pathlib
from collections import Counter
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import aiohttp
import asyncpg
import discord
import toml
from colorama import Fore, Style
from discord.ext import commands

from utils.context import Context
from cogs import EXTENSIONS
from cogs.youtube import DownloadControls

try:
    import uvloop  # type: ignore
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.info(f'{Fore.GREEN} Successfully installed uvloop.{Style.RESET_ALL}')
except Exception as e:
    logging.info(f'{Fore.RED} Failed to install uvloop.{Style.RESET_ALL}\n{e}')
    pass


file_path = Path(__file__).resolve().parent / "config.toml"
with open(file_path, "r") as file:
    config_file = toml.load(file)

os.environ['JISHAKU_FORCE_PAGINATOR'] = "True"
os.environ['JISHAKU_NO_UNDERSCORE'] = "True"
os.environ['JISHAKU_NO_DM_TRACEBACK'] = "True"
os.environ['JISHAKU_HIDE'] = "True"

LOGGER = logging.getLogger("robo_dan")


class RemoveNoise(logging.Filter):
    def __init__(self) -> None:
        super().__init__(name="discord.state")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelname == "WARNING" and "referencing an unknown" in record.msg:
            return False
        return True


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
        logging.getLogger("discord.state").addFilter(RemoveNoise())

        self.log.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            filename=self.logging_path / "bot.log", encoding="utf-8", mode="w", maxBytes=self.max_bytes, backupCount=5
        )
        dt_fmt = "%Y-%m-%d %H:%M:%S"
        fmt = logging.Formatter("[{asctime}] [{levelname:<7}] {name}: {message}", dt_fmt, style="{")
        handler.setFormatter(fmt)
        self.log.addHandler(handler)

        if self.stream:
            stream_handler = logging.StreamHandler()
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
    await conn.set_type_codec('jsonb',
                              schema='pg_catalog',
                              encoder=_encode_jsonb,
                              decoder=_decode_jsonb,
                              format='text')

intents = discord.Intents.all()


class Bot(commands.Bot):
    pool: asyncpg.Pool
    session: aiohttp.ClientSession
    bucket: aiob2.Client
    mystbin: mystbin.Client
    command_stats: Counter[str]
    socket_stats: Counter[str]
    launch_time: datetime.datetime

    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(config_file['startup']['prefix']),
            intents=intents,
            owner_ids=tuple(config_file['startup']['owner_ids']),
            chunk_guilds_at_startup=True
        )

        self.config = config_file
        self.add_check(self.ctx_check)
        self.add_view(DownloadControls())
        self.tree.interaction_check = self.interaction_check
        self.global_log = logging.getLogger()

    @staticmethod
    async def get_or_fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
        """Looks up a member in cache or fetches if not found.
        Parameters
        -----------
        guild: Guild
            The guild to look in.
        user_id: int
            The user ID to search for.
        Returns
        ---------
        Optional[discord.Member]
            The member or None if not found.
        """

        member = guild.get_member(user_id)
        if member is not None:
            return member

        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            return None
        else:
            return member

    async def get_or_fetch_user(self, user_id: int) -> discord.User | None:
        """Looks up a user in cache or fetches if not found.
        Parameters
        -----------
        user_id: int
            The user ID to search for.
        Returns
        ---------
        Optional[discord.User]
            The member or None if not found.
        """

        user = self.get_user(user_id)
        if user is not None:
            return user

        try:
            user = await self.fetch_user(user_id)
        except discord.HTTPException:
            return None
        else:
            return user

    @discord.utils.cached_property
    def error_webhook(self):
        hook = discord.Webhook.partial(
            id=self.config['error']['wh_id'],
            token=self.config['error']['wh_token'],
            session=self.session
        )
        return hook

    async def ctx_check(self, ctx: Context) -> bool:
        return ctx.author.id == 723943620054614047

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == 723943620054614047

    async def get_context(self, message, *, cls=Context):
        return await super().get_context(message, cls=cls)

    async def startup_message(self):
        await self.wait_until_ready()

        c = self.get_channel(self.config['startup']['startup_messages'])
        await c.send('Internal cache is ready.')

    async def setup_hook(self) -> None:
        self.launch_time = datetime.datetime.utcnow()

    def run(self, token: str = None) -> None:
        return super().run(
            token or self.config['startup']['token']
        )

    async def start(self, token: str = None, *, reconnect: bool = True) -> None:
        await super().start(
            token or self.config['startup']['token'],
            reconnect=reconnect
        )

    async def close(self) -> None:
        await super().close()
        if hasattr(self, 'pool') and self.pool is not None:
            await self.pool.close()
        if hasattr(self, 'session') and self.session is not None:
            await self.session.close()


async def main():
    async with Bot() as bot:
        pool = await asyncpg.create_pool(**config_file['database'], init=init)

        if pool is None:
            # thanks asyncpg...
            raise RuntimeError("Could not connect to database.")
        bot.pool = pool

        session = aiohttp.ClientSession()
        bot.session = session

        bot.bucket = aiob2.Client(
            config_file['backblaze']['key'], config_file['backblaze']['key_id']
        )
        bot.mystbin = mystbin.Client()

        with SetupLogging(stream=False):
            await bot.load_extension("jishaku")
            for extension in EXTENSIONS:
                await bot.load_extension(extension)

            asyncio.create_task(bot.startup_message())

            await bot.start()

if __name__ == '__main__':
    asyncio.run(main())
