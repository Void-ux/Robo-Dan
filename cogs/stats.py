from __future__ import annotations

import asyncio
import datetime
import gc
import io
import logging
import os
import re
import textwrap
from collections import Counter, defaultdict
from typing import TypedDict, Any, Annotated, Optional

import asyncpg
import discord
import psutil
from discord import app_commands
from discord.ext import commands, tasks

from main import Bot
from utils import formats
from utils.context import GuildContext
from utils.emotes import LEADERBOARD_EMOTES
from utils.time import format_dt

log = logging.getLogger(__name__)


class DataBatchEntry(TypedDict):
    guild: int | None
    channel: int
    author: int
    used: str
    prefix: str
    command: str
    failed: bool


class GatewayHandler(logging.Handler):
    def __init__(self, cog: Stats):
        self.cog: Stats = cog
        super().__init__(logging.INFO)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == 'discord.gateway' or 'Shard ID' in record.msg or 'Websocket closed ' in record.msg

    def emit(self, record: logging.LogRecord) -> None:
        self.cog.add_record(record)


_INVITE_REGEX = re.compile(r'(?:https?:\/\/)?discord(?:\.gg|\.com|app\.com\/invite)?\/[A-Za-z0-9]+')  # noqa


def hex_value(arg: str) -> int:
    return int(arg, base=16)


def censor_invite(obj: Any, *, _regex=_INVITE_REGEX) -> str:
    return _regex.sub('[censored-invite]', str(obj))


def object_at(addr: int) -> Any | None:
    for o in gc.get_objects():
        if id(o) == addr:
            return o
    return None


class Stats(commands.Cog):
    """Bot usage statistics."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.process = psutil.Process()
        self._batch_lock = asyncio.Lock()
        self._data_batch: list[DataBatchEntry] = []
        self.bulk_insert_loop.add_exception_type(asyncpg.PostgresConnectionError)
        self.bulk_insert_loop.start()
        self._gateway_queue = asyncio.Queue()
        self.gateway_worker.start()

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name='\N{BAR CHART}')

    async def bulk_insert(self) -> None:
        query = """
            INSERT INTO commands (guild_id, channel_id, author_id, used, prefix, command, slash, failed)
            SELECT x.guild, x.channel, x.author, x.used, x.prefix, x.command, x.slash, x.failed
            FROM jsonb_to_recordset($1::jsonb) AS
            x(guild BIGINT, channel BIGINT, author BIGINT, used TIMESTAMP, prefix TEXT, slash BOOLEAN, command TEXT, failed BOOLEAN)
        """

        if self._data_batch:
            await self.bot.pool.execute(query, self._data_batch)
            total = len(self._data_batch)
            if total > 1:
                log.info('Registered %s commands to the database.', total)
            self._data_batch.clear()

    def cog_unload(self):
        self.bulk_insert_loop.stop()
        self.gateway_worker.cancel()

    @tasks.loop(seconds=10.0)
    async def bulk_insert_loop(self):
        async with self._batch_lock:
            await self.bulk_insert()

    @tasks.loop(seconds=0.0)
    async def gateway_worker(self):
        record = await self._gateway_queue.get()
        await self.notify_gateway_status(record)

    async def register_command(self, ctx: GuildContext) -> None:
        if ctx.command is None:
            return

        command = ctx.command.qualified_name
        self.bot.command_stats[command] += 1
        message = ctx.message
        if ctx.guild is None:
            destination = 'Private Message'
            guild_id = None
        else:
            destination = f'#{message.channel} ({message.guild})'
            guild_id = ctx.guild.id

        log.info(f'{message.created_at}: {message.author} in {destination}: {message.content}')
        async with self._batch_lock:
            self._data_batch.append(
                {
                    'guild': guild_id,
                    'channel': ctx.channel.id,
                    'author': ctx.author.id,
                    'used': message.created_at.isoformat(),
                    'prefix': ctx.prefix,
                    'command': command,
                    'slash': bool(ctx.interaction),
                    'failed': ctx.command_failed,
                }
            )

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: GuildContext):
        await self.register_command(ctx)

    @commands.Cog.listener()
    async def on_socket_event_type(self, event_type: str):
        self.bot.socket_stats[event_type] += 1

    @discord.utils.cached_property
    def webhook(self) -> discord.Webhook:
        wh_id, wh_token = 1016171507401097377, '-5vfdy2UHhUvZ2-vzZHsxhM0UPKdxY_wD25Lo6K6RLUpeLJtqO35Onb6ohmxamUhDGbo'
        hook = discord.Webhook.partial(id=wh_id, token=wh_token, session=self.bot.session)
        return hook

    def add_record(self, record: logging.LogRecord) -> None:
        # if self.bot.config.debug:
        #     return
        self._gateway_queue.put_nowait(record)

    async def notify_gateway_status(self, record: logging.LogRecord) -> None:
        attributes = {'INFO': '\N{INFORMATION SOURCE}', 'WARNING': '\N{WARNING SIGN}'}

        emoji = attributes.get(record.levelname, '\N{CROSS MARK}')
        dt = datetime.datetime.utcfromtimestamp(record.created)
        msg = textwrap.shorten(f'{emoji} [{format_dt(dt)}] `{record.message}`', width=1990)
        await self.webhook.send(msg, username='Gateway', avatar_url='https://i.imgur.com/4PnCKB3.png')

    @commands.hybrid_command()
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Serv
    @commands.is_owner()
    async def commandstats(self, ctx: GuildContext, limit: int = 20):
        """Shows command stats.
        Use a negative number for bottom instead of top.
        This is only for the current session.
        """
        counter = self.bot.command_stats
        width = len(max(counter, key=len))

        if limit > 0:
            common = counter.most_common(limit)
        else:
            common = counter.most_common()[limit:]

        output = '\n'.join(f'{k:<{width}}: {c}' for k, c in common)

        await ctx.send(f'```\n{output}\n```')

    @commands.hybrid_command()
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def socketstats(self, ctx: GuildContext):
        delta = datetime.datetime.utcnow() - self.bot.launch_time
        minutes = delta.total_seconds() / 60
        total = sum(self.bot.socket_stats.values())
        cpm = total / minutes
        await ctx.send(
            f'{total} socket events observed ({cpm:.2f}/minute):\n{self.bot.socket_stats}'
        )

    async def show_guild_stats(self, ctx: GuildContext) -> None:
        lookup = (
            LEADERBOARD_EMOTES[0],
            LEADERBOARD_EMOTES[1],
            LEADERBOARD_EMOTES[2],
            LEADERBOARD_EMOTES[3],
            LEADERBOARD_EMOTES[4],
        )

        embed = discord.Embed(title='Server Command Stats', colour=discord.Colour.blurple())

        # total command uses
        query = "SELECT COUNT(*), MIN(used) FROM commands WHERE guild_id=$1;"
        count: tuple[int, datetime.datetime] = await self.bot.pool.fetchrow(query, ctx.guild.id)

        embed.description = f'{count[0]} commands used.'
        if count[1]:
            timestamp = count[1].replace(tzinfo=datetime.timezone.utc)
        else:
            timestamp = discord.utils.utcnow()

        embed.set_footer(text='Tracking command usage since').timestamp = timestamp

        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   WHERE guild_id=$1
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id)

        value = (
            '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
            or 'No Commands'
        )

        embed.add_field(name='Top Commands', value=value, inline=True)

        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   WHERE guild_id=$1
                   AND used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id)

        value = (
            '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
            or 'No Commands.'
        )
        embed.add_field(name='Top Commands Today', value=value, inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=True)

        query = """SELECT author_id,
                          COUNT(*) AS "uses"
                   FROM commands
                   WHERE guild_id=$1
                   GROUP BY author_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id)

        value = (
            '\n'.join(
                f'{lookup[index]}: <@!{author_id}> ({uses} bot uses)' for (index, (author_id, uses)) in enumerate(records)
            )
            or 'No bot users.'
        )

        embed.add_field(name='Top Command Users', value=value, inline=True)

        query = """SELECT author_id,
                          COUNT(*) AS "uses"
                   FROM commands
                   WHERE guild_id=$1
                   AND used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY author_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id)

        value = (
            '\n'.join(
                f'{lookup[index]}: <@!{author_id}> ({uses} bot uses)' for (index, (author_id, uses)) in enumerate(records)
            )
            or 'No command users.'
        )

        embed.add_field(name='Top Command Users Today', value=value, inline=True)
        await ctx.send(embed=embed)

    async def show_member_stats(self, ctx: GuildContext, member: discord.Member) -> None:
        lookup = (
            LEADERBOARD_EMOTES[0],
            LEADERBOARD_EMOTES[1],
            LEADERBOARD_EMOTES[2],
            LEADERBOARD_EMOTES[3],
            LEADERBOARD_EMOTES[4],
        )

        embed = discord.Embed(title='Command Stats', colour=member.colour)
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)

        # total command uses
        query = "SELECT COUNT(*), MIN(used) FROM commands WHERE guild_id=$1 AND author_id=$2;"
        count: tuple[int, datetime.datetime] = await self.bot.pool.fetchrow(query, ctx.guild.id, member.id)

        embed.description = f'{count[0]} commands used.'
        if count[1]:
            timestamp = count[1].replace(tzinfo=datetime.timezone.utc)
        else:
            timestamp = discord.utils.utcnow()

        embed.set_footer(text='First command used').timestamp = timestamp

        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   WHERE guild_id=$1 AND author_id=$2
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id, member.id)

        value = (
            '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
            or 'No Commands'
        )

        embed.add_field(name='Most Used Commands', value=value, inline=False)

        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   WHERE guild_id=$1
                   AND author_id=$2
                   AND used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query, ctx.guild.id, member.id)

        value = (
            '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
            or 'No Commands'
        )

        embed.add_field(name='Most Used Commands Today', value=value, inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_group(invoke_without_command=True)
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def cstats(self, ctx: GuildContext, member: discord.Member | None = None):
        """Parent command for a cluster of statistics related commands."""
        async with ctx.typing():
            if member is None:
                await self.show_guild_stats(ctx)
            else:
                await self.show_member_stats(ctx, member)

    @cstats.command(name='global')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def stats_global(self, ctx: GuildContext):
        """Global all time command statistics."""

        await ctx.typing()
        query = "SELECT COUNT(*) FROM commands;"
        total: tuple[int] = await self.bot.pool.fetchrow(query)

        e = discord.Embed(title='Command Stats', colour=discord.Colour.blurple())
        e.description = f'{total[0]} commands used.'

        lookup = (
            LEADERBOARD_EMOTES[0],
            LEADERBOARD_EMOTES[1],
            LEADERBOARD_EMOTES[2],
            LEADERBOARD_EMOTES[3],
            LEADERBOARD_EMOTES[4],
        )

        query = """SELECT command, COUNT(*) AS "uses"
                   FROM commands
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
        e.add_field(name='Top Commands', value=value, inline=False)

        query = """SELECT guild_id, COUNT(*) AS "uses"
                   FROM commands
                   GROUP BY guild_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = []
        for (index, (guild_id, uses)) in enumerate(records):
            if guild_id is None:
                guild = 'Private Message'
            else:
                guild = censor_invite(self.bot.get_guild(guild_id) or f'<Unknown {guild_id}>')

            emoji = lookup[index]
            value.append(f'{emoji}: {guild} ({uses} uses)')

        e.add_field(name='Top Guilds', value='\n'.join(value), inline=False)

        query = """SELECT author_id, COUNT(*) AS "uses"
                   FROM commands
                   GROUP BY author_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = []
        for (index, (author_id, uses)) in enumerate(records):
            user = censor_invite(self.bot.get_user(author_id) or f'<Unknown {author_id}>')
            emoji = lookup[index]
            value.append(f'{emoji}: {user} ({uses} uses)')

        e.add_field(name='Top Users', value='\n'.join(value), inline=False)
        await ctx.send(embed=e)

    @cstats.command(name='today')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def stats_today(self, ctx: GuildContext):
        """Global command statistics for the day."""

        await ctx.defer()
        query = "SELECT failed, COUNT(*) FROM commands WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day') GROUP BY failed;"
        total = await self.bot.pool.fetch(query)
        failed = 0
        success = 0
        question = 0
        for state, count in total:
            if state is False:
                success += count
            elif state is True:
                failed += count
            else:
                question += count

        e = discord.Embed(title='Last 24 Hour Command Stats', colour=discord.Colour.blurple())
        e.description = (
            f'{failed + success + question} commands used today. '
            f'({success} succeeded, {failed} failed, {question} unknown)'
        )

        lookup = (
            LEADERBOARD_EMOTES[0],
            LEADERBOARD_EMOTES[1],
            LEADERBOARD_EMOTES[2],
            LEADERBOARD_EMOTES[3],
            LEADERBOARD_EMOTES[4],
        )

        query = """SELECT command, COUNT(*) AS "uses"
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = '\n'.join(f'{lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
        e.add_field(name='Top Commands', value=value, inline=False)

        query = """SELECT guild_id, COUNT(*) AS "uses"
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY guild_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = []
        for (index, (guild_id, uses)) in enumerate(records):
            if guild_id is None:
                guild = 'Private Message'
            else:
                guild = censor_invite(self.bot.get_guild(guild_id) or f'<Unknown {guild_id}>')
            emoji = lookup[index]
            value.append(f'{emoji}: {guild} ({uses} uses)')

        e.add_field(name='Top Guilds', value='\n'.join(value), inline=False)

        query = """SELECT author_id, COUNT(*) AS "uses"
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY author_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await self.bot.pool.fetch(query)
        value = []
        for (index, (author_id, uses)) in enumerate(records):
            user = censor_invite(self.bot.get_user(author_id) or f'<Unknown {author_id}>')
            emoji = lookup[index]
            value.append(f'{emoji}: {user} ({uses} uses)')

        e.add_field(name='Top Users', value='\n'.join(value), inline=False)
        await ctx.send(embed=e)

    async def send_guild_stats(self, e: discord.Embed, guild: discord.Guild):
        e.add_field(name='Name', value=guild.name)
        e.add_field(name='ID', value=guild.id)
        e.add_field(name='Shard ID', value=guild.shard_id or 'N/A')
        e.add_field(name='Owner', value=f'{guild.owner} (ID: {guild.owner_id})')

        bots = sum(m.bot for m in guild.members)
        total = guild.member_count or 1
        e.add_field(name='Members', value=str(total))
        e.add_field(name='Bots', value=f'{bots} ({bots/total:.2%})')

        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        if guild.me:
            e.timestamp = guild.me.joined_at

        await self.webhook.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        e = discord.Embed(colour=0x53DDA4, title='New Guild')  # green colour
        await self.send_guild_stats(e, guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        e = discord.Embed(colour=0xDD5F53, title='Left Guild')  # red colour
        await self.send_guild_stats(e, guild)

    @commands.hybrid_command()
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def bothealth(self, ctx: GuildContext):
        """Various bot health monitoring tools."""

        # This uses a lot of private methods because there is no
        # clean way of doing this otherwise.

        HEALTHY = discord.Colour(value=0x43B581)  # noqa
        UNHEALTHY = discord.Colour(value=0xF04947)  # noqa
        WARNING = discord.Colour(value=0xF09E47)  # noqa
        total_warnings = 0

        embed = discord.Embed(title='Bot Health Report', colour=HEALTHY)

        # Check the connection pool health.
        pool = self.bot.pool
        total_waiting = len(pool._queue._getters)  # type: ignore
        current_generation = pool._generation

        description = [
            f'Total `Pool.acquire` Waiters: {total_waiting}',
            f'Current Pool Generation: {current_generation}',
            f'Connections In Use: {len(pool._holders) - pool._queue.qsize()}',  # type: ignore
        ]

        questionable_connections = 0
        connection_value = []
        for index, holder in enumerate(pool._holders, start=1):
            generation = holder._generation
            in_use = holder._in_use is not None
            is_closed = holder._con is None or holder._con.is_closed()
            display = f'gen={holder._generation} in_use={in_use} closed={is_closed}'
            questionable_connections += any((in_use, generation != current_generation))
            connection_value.append(f'<Holder i={index} {display}>')

        joined_value = '\n'.join(connection_value)
        embed.add_field(name='Connections', value=f'```py\n{joined_value}\n```', inline=False)

        description.append(f'Questionable Connections: {questionable_connections}')

        total_warnings += questionable_connections

        try:
            task_retriever = asyncio.Task.all_tasks  # type: ignore
        except AttributeError:
            # future proofing for 3.9 I guess
            task_retriever = asyncio.all_tasks

        all_tasks = task_retriever(loop=self.bot.loop)

        event_tasks = [t for t in all_tasks if 'Client._run_event' in repr(t) and not t.done()]

        cogs_directory = os.path.dirname(__file__)
        tasks_directory = os.path.join('discord', 'ext', 'tasks', '__init__.py')
        inner_tasks = [t for t in all_tasks if cogs_directory in repr(t) or tasks_directory in repr(t)]

        bad_inner_tasks = ", ".join(hex(id(t)) for t in inner_tasks if t.done() and t._exception is not None)
        total_warnings += bool(bad_inner_tasks)
        embed.add_field(name='Inner Tasks', value=f'Total: {len(inner_tasks)}\nFailed: {bad_inner_tasks or "None"}')
        embed.add_field(name='Events Waiting', value=f'Total: {len(event_tasks)}', inline=False)

        command_waiters = len(self._data_batch)
        is_locked = self._batch_lock.locked()
        description.append(f'Commands Waiting: {command_waiters}, Batch Locked: {is_locked}')

        memory_usage = self.process.memory_full_info().uss / 1024**2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        embed.add_field(name='Process', value=f'{memory_usage:.2f} MiB\n{cpu_usage:.2f}% CPU', inline=False)

        global_rate_limit = not self.bot.http._global_over.is_set()
        description.append(f'Global Rate Limit: {global_rate_limit}')

        if command_waiters >= 8:
            total_warnings += 1
            embed.colour = WARNING

        if global_rate_limit or total_warnings >= 9:
            embed.colour = UNHEALTHY

        embed.set_footer(text=f'{total_warnings} warning(s)')
        embed.description = '\n'.join(description)
        await ctx.send(embed=embed)

    async def tabulate_query(self, ctx: GuildContext, query: str, *args: Any):
        records = await self.bot.pool.fetch(query, *args)

        if len(records) == 0:
            return await ctx.send('No results found.')

        headers = list(records[0].keys())
        table = formats.TabularData()
        table.set_columns(headers)
        table.add_rows(list(r.values()) for r in records)
        render = table.render()

        fmt = f'```\n{render}\n```'
        if len(fmt) > 2000:
            fp = io.BytesIO(fmt.encode('utf-8'))
            await ctx.send('Too many results...', file=discord.File(fp, 'results.txt'))
        else:
            await ctx.send(fmt)

    @commands.hybrid_group(invoke_without_command=True)
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history(self, ctx: GuildContext):
        """Parent command for a cluster of command history related commands."""
        """Command history."""
        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN command || ' [!]'
                            ELSE command
                        END AS "command",
                        to_char(used, 'Mon DD HH12:MI:SS AM') AS "invoked",
                        author_id,
                        guild_id
                   FROM commands
                   ORDER BY used DESC
                   LIMIT 15;
                """
        await self.tabulate_query(ctx, query)

    @command_history.command(name='all')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_all(self, ctx: GuildContext):
        """Command history."""

        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN command || ' [!]'
                            ELSE command
                        END AS "command",
                        to_char(used, 'Mon DD HH12:MI:SS AM') AS "invoked",
                        author_id,
                        guild_id
                   FROM commands
                   ORDER BY used DESC
                   LIMIT 15;
                """
        await self.tabulate_query(ctx, query)

    @command_history.command(name='for')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_for(self, ctx: GuildContext, days: Annotated[int, Optional[int]] = 7, *, command: str):  # noqa
        """Command history for a command."""

        query = """SELECT *, t.success + t.failed AS "total"
                   FROM (
                       SELECT guild_id,
                              SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                              SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                       FROM commands
                       WHERE command=$1
                       AND used > (CURRENT_TIMESTAMP - $2::interval)
                       GROUP BY guild_id
                   ) AS t
                   ORDER BY "total" DESC
                   LIMIT 30;
                """

        await self.tabulate_query(ctx, query, command, datetime.timedelta(days=days))

    @command_history.command(name='guild')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_guild(self, ctx: GuildContext, guild_id: int):
        """Command history for a guild."""

        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN command || ' [!]'
                            ELSE command
                        END AS "command",
                        channel_id,
                        author_id,
                        used
                   FROM commands
                   WHERE guild_id=$1
                   ORDER BY used DESC
                   LIMIT 15;
                """
        await self.tabulate_query(ctx, query, guild_id)

    @command_history.command(name='user')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_user(self, ctx: GuildContext, user_id: int):
        """Command history for a user."""

        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN command || ' [!]'
                            ELSE command
                        END AS "command",
                        guild_id,
                        used
                   FROM commands
                   WHERE author_id=$1
                   ORDER BY used DESC
                   LIMIT 20;
                """
        await self.tabulate_query(ctx, query, user_id)

    @command_history.command(name='log')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_log(self, ctx: GuildContext, days: int = 7):
        """Command history log for the last N days."""

        query = """SELECT command, COUNT(*)
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - $1::interval)
                   GROUP BY command
                   ORDER BY 2 DESC
                """

        all_commands = {c.qualified_name: 0 for c in self.bot.walk_commands()}

        records = await self.bot.pool.fetch(query, datetime.timedelta(days=days))
        for name, uses in records:
            if name in all_commands:
                all_commands[name] = uses

        as_data = sorted(all_commands.items(), key=lambda t: t[1], reverse=True)
        table = formats.TabularData()
        table.set_columns(['Command', 'Uses'])
        table.add_rows(tup for tup in as_data)
        render = table.render()

        embed = discord.Embed(title='Summary', colour=discord.Colour.green())
        embed.set_footer(text='Since').timestamp = discord.utils.utcnow() - datetime.timedelta(days=days)

        top_ten = '\n'.join(f'{command}: {uses}' for command, uses in records[:10])
        bottom_ten = '\n'.join(f'{command}: {uses}' for command, uses in records[-10:])
        embed.add_field(name='Top 10', value=top_ten)
        embed.add_field(name='Bottom 10', value=bottom_ten)

        unused = ', '.join(name for name, uses in as_data if uses == 0)
        if len(unused) > 1024:
            unused = 'Way too many...'

        embed.add_field(name='Unused', value=unused, inline=False)

        await ctx.send(embed=embed, file=discord.File(io.BytesIO(render.encode()), filename='full_results.txt'))

    @command_history.command(name='cog')
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def command_history_cog(self, ctx: GuildContext, days: Annotated[int, Optional[int]] = 7, cog_name: str | None = None):  # noqa
        """Command history for a cog or grouped by a cog."""
        interval = datetime.timedelta(days=days)
        if cog_name is not None:
            cog = self.bot.get_cog(cog_name)
            if cog is None:
                return await ctx.send(f'Unknown cog: {cog_name}')

            query = """SELECT *, t.success + t.failed AS "total"
                       FROM (
                           SELECT command,
                                  SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                                  SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                           FROM commands
                           WHERE command = any($1::text[])
                           AND used > (CURRENT_TIMESTAMP - $2::interval)
                           GROUP BY command
                       ) AS t
                       ORDER BY "total" DESC
                       LIMIT 30;
                    """
            return await self.tabulate_query(ctx, query, [c.qualified_name for c in cog.walk_commands()], interval)

        # A more manual query with a manual grouper.
        query = """SELECT *, t.success + t.failed AS "total"
                   FROM (
                       SELECT command,
                              SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                              SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                       FROM commands
                       WHERE used > (CURRENT_TIMESTAMP - $1::interval)
                       GROUP BY command
                   ) AS t;
                """

        class Count:
            __slots__ = ('success', 'failed', 'total')

            def __init__(self):
                self.success = 0
                self.failed = 0
                self.total = 0

            def add(self, record):  # noqa
                self.success += record['success']
                self.failed += record['failed']
                self.total += record['total']

        data = defaultdict(Count)
        records = await self.bot.pool.fetch(query, interval)
        for record in records:
            command = self.bot.get_command(record['command'])
            if command is None or command.cog is None:
                data['No Cog'].add(record)
            else:
                data[command.cog.qualified_name].add(record)

        table = formats.TabularData()
        table.set_columns(['Cog', 'Success', 'Failed', 'Total'])
        data = sorted([(cog, e.success, e.failed, e.total) for cog, e in data.items()], key=lambda t: t[-1], reverse=True)

        table.add_rows(data)
        render = table.render()
        await ctx.send(f'```\n{render}\n```')


async def setup(bot: Bot):
    if not hasattr(bot, 'command_stats'):
        bot.command_stats = Counter()

    if not hasattr(bot, 'socket_stats'):
        bot.socket_stats = Counter()

    cog = Stats(bot)
    await bot.add_cog(cog)
    bot.gateway_handler = handler = GatewayHandler(cog)  # type: ignore
    logging.getLogger().addHandler(handler)
