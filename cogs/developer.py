import traceback
import time
from io import BytesIO
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from main import Bot
from utils import formats
from utils.context import GuildContext


class Developer(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.hybrid_command()
    @app_commands.guilds(927189052531298384, 982641718119772200)  # DTT, Support Server
    @commands.is_owner()
    async def sync(
        self, ctx: GuildContext, guilds: commands.Greedy[discord.Object], spec: Literal["~", "*", "^"] | None = None
    ) -> None:
        if not guilds:
            if spec == "~":
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await ctx.bot.tree.sync()

            await ctx.send(
                f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

        ret = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1

        await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        return content.strip('` \n')

    @commands.command()
    @commands.is_owner()
    async def sql(self, ctx, *, query: str):
        """Run some SQL."""
        query = self.cleanup_code(query)

        is_multistatement = query.count(';') > 1
        if is_multistatement:
            # fetch does not support multiple statements
            strategy = self.bot.pool.execute
        else:
            strategy = self.bot.pool.fetch

        try:
            start = time.perf_counter()
            results = await strategy(query)
            dt = (time.perf_counter() - start) * 1000.0
        except Exception:
            return await ctx.send(f'```py\n{traceback.format_exc()}\n```')

        rows = len(results)
        if is_multistatement or rows == 0:
            return await ctx.send(f'`{dt:.2f}ms: {results}`')

        headers = list(results[0].keys())
        table = formats.TabularData()
        table.set_columns(headers)
        table.add_rows(list(r.values()) for r in results)
        render = table.render()

        fmt = f'\n{render}\n\n'
        fp = BytesIO(fmt.encode('utf-8'))
        await ctx.send(f'*Returned {formats.plural(rows):row} in {dt:.2f}ms*', file=discord.File(fp, 'results.txt'))

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, *, module: str):
        """Loads a module."""
        try:
            await self.bot.load_extension(f'cogs.{module}')
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, module: str):
        """Unloads a module."""
        try:
            await self.bot.unload_extension(f'cogs.{module}')
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx: GuildContext, *, module: str):
        """Reloads a module."""
        try:
            await self.bot.reload_extension(f'cogs.{module}')
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send('\N{OK HAND SIGN}')


async def setup(bot: Bot):
    await bot.add_cog(Developer(bot))
