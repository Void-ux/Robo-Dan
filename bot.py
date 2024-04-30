from __future__ import annotations

import aiob2
import mystbin
import datetime
import logging
from collections import Counter
from typing import TYPE_CHECKING, TypedDict

import aiohttp
import asyncpg
import discord
from discord.ext import commands

from utils.context import Context
from utils.sonarr import Client as SonarrClient
from cogs.youtube import DownloadControls

if TYPE_CHECKING:
    from cogs.reminder import Reminder


class PostgresConfig(TypedDict):
    host: str
    user: str
    password: str
    database: str


class BackblazeConfig(TypedDict):
    key_id: str
    key: str
    bucket_id: str


class SonarrConfig(TypedDict):
    host: str
    api_key: str


class WebhookConfig(TypedDict):
    wh_id: int
    wh_token: str


class Config(TypedDict):
    token: str
    owner_ids: list[int]
    database: PostgresConfig
    backblaze: BackblazeConfig
    sonarr: SonarrConfig
    error: WebhookConfig


class RoboDan(commands.Bot):
    pool: asyncpg.Pool
    session: aiohttp.ClientSession
    bucket: aiob2.Client
    sonarr: SonarrClient
    mystbin: mystbin.Client
    command_stats: Counter[str]
    socket_stats: Counter[str]
    launch_time: datetime.datetime

    def __init__(self, config: Config):
        super().__init__(
            command_prefix=commands.when_mentioned_or('-'),
            intents=discord.Intents.all(),
            owner_ids=config['owner_ids'],
            chunk_guilds_at_startup=True
        )

        self.config = config
        self.add_check(self.ctx_check)
        self.add_view(DownloadControls())
        self.tree.interaction_check = self.interaction_check
        self.global_log = logging.getLogger('robodan')

    @discord.utils.cached_property
    def error_webhook(self):
        hook = discord.Webhook.partial(
            id=self.config['error']['wh_id'],
            token=self.config['error']['wh_token'],
            session=self.session
        )
        return hook

    @property
    def reminder(self) -> Reminder | None:
        return self.get_cog('Reminder')  # type: ignore

    async def ctx_check(self, ctx: Context) -> bool:
        return ctx.author.id == 723943620054614047

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == 723943620054614047

    async def get_context(self, message, *, cls=Context):
        return await super().get_context(message, cls=cls)

    async def startup_message(self):
        await self.wait_until_ready()

        self.global_log.info('Bot is ready with a populated cache')

    async def setup_hook(self) -> None:
        self.launch_time = datetime.datetime.utcnow()

    async def start(self, *, reconnect: bool = True) -> None:
        await super().start(self.config['token'], reconnect=reconnect)

    async def close(self) -> None:
        await super().close()
        if hasattr(self, 'pool') and self.pool is not None:
            await self.pool.close()
        if hasattr(self, 'session') and self.session is not None:
            await self.session.close()
