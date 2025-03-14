from __future__ import annotations

import aiob2
import datetime
import logging
from collections import Counter
from typing import TYPE_CHECKING

import aiohttp
import asyncpg
import discord
from discord.ext import commands
from discord.types.emoji import Emoji as EmojiPayload

from cogs.hot_reload import LazyHotReload
from utils.context import Context
from utils.sonarr import Client as SonarrClient
from cogs.youtube import DownloadControls

import config

if TYPE_CHECKING:
    from cogs.reminder import Reminder


class RoboDan(commands.Bot):
    pool: asyncpg.Pool
    session: aiohttp.ClientSession
    bucket: aiob2.Client
    sonarr: SonarrClient
    command_stats: Counter[str]
    socket_stats: Counter[str]
    launch_time: datetime.datetime

    def __init__(self):
        super().__init__(
            command_prefix=lambda bot, msg: \
                config.prefixes + ['-'] if getattr(msg.guild, 'id') == config.guild_id else config.prefixes,
            intents=discord.Intents.all(),
            owner_ids=config.owner_ids,
            chunk_guilds_at_startup=True
        )

        self.config = config
        self.add_check(self.ctx_check)
        self.add_view(DownloadControls())
        self.tree.interaction_check = self.interaction_check
        self.global_log = logging.getLogger('robodan')

    @discord.utils.cached_property
    def error_webhook(self):
        hook = discord.Webhook.partial(*config.error_webhook, session=self.session)
        return hook

    @property
    def reminder(self) -> Reminder:
        return self.get_cog('Reminder')  # pyright: ignore

    @property
    def hot_reloader(self) -> LazyHotReload:
        return self.get_cog('LazyHotReload')  # pyright: ignore

    @property
    def user(self) -> discord.User:  # pyright: ignore
        return super().user  # pyright: ignore

    async def create_emoji(self, name: str, image_url: str) -> EmojiPayload:
        async with self.session.get(image_url) as res:
            if not res.ok:
                raise commands.BadArgument('Sorry, your image URL does not point to a valid image.')
            data = discord.utils._bytes_to_base64_data(await res.read())

        async with self.session.post(
            f'https://discord.com/api/v10/applications/{self.user.id}/emojis',
            headers={'Authorization': f'Bot {config.token}'},
            json={'name': name, 'image': data},
        ) as res:
            data = await res.json()

        return data

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

    async def start(self, *, reconnect: bool = True) -> None:  # pyright: ignore
        await super().start(config.token, reconnect=reconnect)

    async def close(self) -> None:
        await super().close()
        if hasattr(self, 'pool') and self.pool is not None:
            await self.pool.close()
        if hasattr(self, 'session') and self.session is not None:
            await self.session.close()
