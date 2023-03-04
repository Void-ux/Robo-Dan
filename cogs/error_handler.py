import sys
import textwrap
import traceback
from typing import Any

import discord
from discord.ext import commands

from main import Bot
from utils import error_embed
from utils.context import Context


class ErrorEmbed(discord.Embed):
    def __init__(self, *, author: discord.Member | discord.User, **kwargs):
        kwargs.setdefault('colour', 0xFF872B)
        super().__init__(**kwargs)

        self._author = author
        self.set_thumbnail(url=(
            'https://cdn.discordapp.com/attachments/927190003061256224/960178856843702322/unknown.png?size=4096'
            )
        )

        self.set_author(name=self._author, icon_url=self._author.display_avatar.url)


IGNORED = (
    commands.CommandNotFound,
    commands.CommandOnCooldown,
    commands.NotOwner,
    commands.MissingRole
)


def get_command_signature(command):
    parent = command.full_parent_name
    if len(command.aliases) > 0:
        aliases = '|'.join(command.aliases)
        fmt = f'[{command.name} | {aliases}]'
        if parent:
            fmt = f'{parent} {fmt}'
        alias = fmt
    else:
        alias = command.name if not parent else f'{parent} {command.name}'
    return f"{alias} {command.signature.replace('=', '')}"


def get_help(command):
    embed = discord.Embed(colour=discord.Colour(0xA8B9CD))
    embed.title = get_command_signature(command)
    if command.description:
        embed.description = f'{command.description}\n\n{command.help}'
    else:
        embed.description = command.help or 'No help found...'

    return embed


class ErrorHandler(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        bot.on_error = self.on_error

    @commands.Cog.listener()
    async def on_command_error(self, ctx: Context, error: commands.CommandError):
        # This prevents any commands with local handlers being handled here in on_command_error.
        if hasattr(ctx.command, 'on_error'):
            return

        # This prevents any cogs with an overwritten cog_command_error from being handled here.
        if ctx.cog:
            if ctx.cog._get_overridden_method(ctx.cog.cog_command_error) is not None:
                return

        error = getattr(error, 'original', error)

        if isinstance(error, IGNORED):
            return

        elif isinstance(error, commands.MemberNotFound):
            return await ctx.send(embed=ErrorEmbed(
                author=ctx.author,
                description='\n'.join([
                    '**Please provide a valid member for that command. Ensure that:**',
                    '> The member is currently in the server',
                    '> The ID / name was copied correctly',
                    '> You have the right ID / name'
                ])
                )
            )

        elif isinstance(error, commands.UserNotFound):
            return await ctx.send(embed=ErrorEmbed(
                author=ctx.author,
                description=(
                    '**Please provide a valid Discord user.**\n'
                    '(Ensure that the ID / mention is valid, and no typos have occurred!)'
                    )
                )
            )

        elif isinstance(error, commands.BotMissingPermissions):
            return await ctx.send(embed=ErrorEmbed(
                author=ctx.author,
                description=f'Overseer {str(error)[4:]}'
            ))

        elif isinstance(error, commands.CheckFailure):
            if not ctx.interaction:
                return

            return await ctx.send(
                embed=error_embed('You do not have the required permissions to use this command.'),
                ephemeral=True
            )

        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            return await ctx.send(embed=get_help(ctx.command))

        e = discord.Embed(title='Command Error', colour=0xCC3366, timestamp=discord.utils.utcnow())
        assert isinstance(ctx.command, (commands.Command, commands.HybridCommand))
        e.add_field(name='Name', value=ctx.command.qualified_name)
        e.add_field(name='Author', value=f'{ctx.author} (ID: {ctx.author.id})')

        fmt = f'Channel: {ctx.channel} (ID: {ctx.channel.id})'
        if ctx.guild:
            fmt = f'{fmt}\nGuild: {ctx.guild} (ID: {ctx.guild.id})'

        e.add_field(name='Location', value=fmt, inline=False)
        if not ctx.interaction:
            e.add_field(name='Content', value=textwrap.shorten(ctx.message.content, width=512))

        exc = ''.join(traceback.format_exception(error))
        e.description = f'```py\n{exc}\n```'
        await self.bot.error_webhook.send(
            embed=e,
            username='Errors',
            avatar_url='https://cdn.discordapp.com/attachments/927190003061256224/1001615278616092722/error.png'
        )

        raise error

    async def on_error(self, event: str, *args: Any, **_: Any) -> None:
        (exc_type, exc, tb) = sys.exc_info()
        # Silence command errors that somehow get bubbled up far enough here
        if isinstance(exc, commands.CommandInvokeError) or event in ('on_command_error', 'on_app_command_error'):
            return

        e = discord.Embed(title='Event Error', colour=0xA32952, timestamp=discord.utils.utcnow())
        trace = ''.join(traceback.format_exception(exc_type, exc, tb))
        e.description = f'```py\n{trace}\n```'

        args_str = ['```py']
        for index, arg in enumerate(args):
            args_str.append(f'[{index}]: {arg!r}')
        args_str.append('```')

        e.add_field(name='Event', value=event)
        e.add_field(name='Args', value='\n'.join(args_str), inline=False)

        await self.bot.error_webhook.send(
            embed=e,
            username='Errors',
            avatar_url='https://cdn.discordapp.com/attachments/927190003061256224/1001615278616092722/error.png'
        )


async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
