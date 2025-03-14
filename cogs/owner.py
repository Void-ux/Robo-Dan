import random
import string
import traceback
import time
from io import BytesIO
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
import yarl

from bot import RoboDan
from utils import formats
from utils.context import GuildContext
from utils.formats import plural


class Owner(commands.Cog):
    def __init__(self, bot: RoboDan):
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

    @commands.command(aliases=['ae'])
    @commands.guild_only()
    @commands.is_owner()
    async def addemoji(self, ctx: GuildContext, *emojis: discord.PartialEmoji | str):
        """Adds any given emotes to the server (the name remains the same)."""
        ordinal = lambda n: "%d%s" % (n, "tsnrhtdd"[(n//10 % 10 != 1)*(n % 10 < 4) * n % 10::4])  # noqa
        def is_url(a):
            return isinstance(a, str) and bool(formats.URL_REGEX.match(a))

        created_emojis = []
        for c, emoji in enumerate(emojis):
            if isinstance(emoji, discord.PartialEmoji):
                created_emojis.append(await self.bot.create_emoji(
                    name=emoji.name,
                    image_url=emoji.url
                ))
            elif is_url(emoji):
                urls = list(filter(lambda x: is_url(x), emojis))

                async with self.bot.session.get(emoji) as res:
                    if not res.ok:
                        return await ctx.send(
                            f'Sorry, received a HTTP {res.status} when retrieving the {urls.index(emoji)}'
                        )

                url = yarl.URL(emoji)
                if url.name.endswith(('.png', '.webp', '.gif', '.jpg', '.jpeg')):
                    file_name = url.name.split('/')[-2]
                else:
                    file_name = random.shuffle(list(string.ascii_lowercase) + list(string.digits))[:5]  # pyright: ignore

                try:
                    created_emojis.append(await ctx.guild.create_custom_emoji(
                        name=file_name,
                        image=await res.read(),
                        reason=f'{ctx.author} used addemote.'
                    ))
                except discord.HTTPException:
                    text = '\n'.join(str(i) for i in created_emojis)
                    await ctx.deny(
                        f'Created {plural(len(created_emojis)):emoji}. '
                        f'Unable to convert the <{ordinal(c)}> URL to an emoji.\n```\n' + text + '```'
                    )
        text = '\n'.join(f'<:{i['name']}:{i['id']}>' for i in created_emojis)
        await ctx.send(f'Created {plural(len(created_emojis)):emoji}.\n```' + text + '```')


async def setup(bot: RoboDan):
    await bot.add_cog(Owner(bot))
