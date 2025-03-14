import asyncio
import os
import logging
import importlib.util
import time
from pathlib import Path

import discord
from discord.ext import commands
from colorama import Fore

from utils.interaction import Interaction
from utils.context import Context

__all__ = ('ignore_hot_reload', )
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

IGNORE_EXTENSIONS = ('jishaku', 'cogs.hot_reload')


def ignore_hot_reload(cls):
    """Block `cogs.hot_reload` from reloading commands in this cog.
    
    This is useful when your cogs begins relying upon state, like:
    - db connections
    - Complex object refs

    Example
    >>> ...
    >>> from .hot_reload import ignore_hot_reload
    >>> 
    >>> @ignore_hot_reload
    >>> class MyCog(commands.Cog)
    >>>     def __init__(self, bot: Bot):
    """
    cls._hot_reload_ignored = True
    return cls


def colour_format(m) -> str:
    return Fore.GREEN + m + Fore.RESET


def get_last_modified(ext: Path | str) -> float | None:
    if isinstance(ext, Path):
        ext = f'{__name__}.{ext.name}'
    spec = importlib.util.find_spec(ext, None)
    if spec is None:
        raise commands.BadArgument(f'Unable to find extension: {ext}')

    if spec.origin is None:  # eg builtins
        raise commands.BadArgument(f'Unknown error occured finding origin of {ext}')
    return os.path.getmtime(spec.origin)


class LazyHotReload(commands.Cog):
    """Reloads your command's extension just before it gets invoked,
    to ensure the latest code is actively ran.

    TL:DR; saves you from having to `-reload` during development.

    Warning
    -------
    - This does NOT *load* modules when placed into `cogs/`, duh.
    - This extension excludes itself from reloads
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_modified_times: dict[str, float] = {}
        self.bot.add_check(self.lazy_reload)
        self._old_tree_check = self.bot.tree.interaction_check
        self.bot.tree.interaction_check = self.interaction_check  # pyright: ignore

    async def _populate(self):
        await self.bot.wait_until_ready()

        for ext in self.bot.extensions.keys():
            if ext in IGNORE_EXTENSIONS:
                continue

            last_modified = get_last_modified(ext)
            if last_modified is None:
                continue
            self.last_modified_times[ext] = last_modified

    async def reload_extension(self, extension: str) -> bool:
        """Reload a single extension.
        
        Returns
        -------
        :class:`bool` True if successful, False otherwise"""
        last_modified = get_last_modified(extension)
        
        if last_modified is None:  # builtins
            return False

        try:
            log.info('Found an update to %s; performing update', extension)
            await self.bot.reload_extension(extension)
        except commands.ExtensionError:
            log.error('Unable to load %s', extension)
            return False
        else:
            self.last_modified_times[extension] = last_modified
            log.info('Reloaded extension: %s', extension)
            return True

    async def _process_command(self, ctx: Context) -> bool:
        """Checks a command's module for pending updates, and if yes, applies them and then re-invokes.
        
        Returns
        -------
        :class:`bool`
            True if command execution is to proceed, False when reload is required.
        """
        ext = ctx.command.module
        if ext not in self.bot.extensions:
           log.info('%s is not being tracked.', ext)
           return True

        last_modified = get_last_modified(ext)
        if self.last_modified_times.get(ext) is None:
            log.info('Unknown module %s; will continue to monitor.', ext)
            return True

        cog = ctx.cog
        if cog and hasattr(cog.__class__, '_hot_reload_ignored') and cog.__class__._hot_reload_ignored:  # pyright: ignore
            log.debug('Skipping %s; _hot_reload_ignored flag set to True', ext)
            return True

        if last_modified is None or last_modified <= self.last_modified_times[ext]:
            log.debug('Skipping %s; already up to date.', ext)
            return True

        success = await self.reload_extension(ext)
        if not success:
            return True

        command = self.bot.get_command(ctx.command.qualified_name)
        if command is None:
            log.info('Command %s in updated %s not found.', command, ext)
            return True

        ctx.command = command
        self.last_modified_times[ext] = last_modified
        log.debug('Re-invoking command with updated callback.')
        await self.bot.invoke(ctx)
        if discord.utils.is_docker():
            await asyncio.create_task(
                ctx.message.add_reaction(discord.PartialEmoji.from_str('<:restart:1349890490149113896>'))
            )
        return False

    async def lazy_reload(self, ctx: Context) -> bool:
        """Handles hot reloading prior to text invokation."""
        return await self._process_command(ctx)

    async def interaction_check(
        self,
        interaction: Interaction,
        /
    ) -> bool:
        """Serves to block command invcation until its module/cog is up to date.

        Wraps around other pre-defined `interaction_check` to facilitate reloading, even when invoked via app command.
        """
        failure = await self._old_tree_check(interaction)  # pyright: ignore
        if failure:
            return False

        if interaction.type != discord.InteractionType.application_command:
            return True

        ctx = await Context.from_interaction(interaction)
        return await self._process_command(ctx)

    @commands.hybrid_command()
    @commands.is_owner()
    async def load(self, ctx, *, module: str):
        """Loads a module."""
        try:
            await self.bot.load_extension(f'cogs.{module}')
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.hybrid_command()
    @commands.is_owner()
    async def unload(self, ctx, module: str):
        """Unloads a module."""
        try:
            await self.bot.unload_extension(f'cogs.{module}')
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.hybrid_group()
    @commands.is_owner()
    async def reload(self, ctx: Context, *, module: str):
        """Reloads a module. Set to 'all' to reload all outdated modules."""
        try:
            start = time.perf_counter()
            await self.bot.reload_extension(f'cogs.{module}')
            end = time.perf_counter()
        except commands.ExtensionError as e:
            await ctx.send(f'{e.__class__.__name__}: {e}')
        else:
            await ctx.send(f'\N{OK HAND SIGN} *(in {round((end - start) * 100, 2)}ms)*')

    @reload.command(name='all')
    @commands.is_owner()
    async def reload_all(self, ctx: Context):
        """Displays information for all the currently online modules."""
        rows = []
        for ext in Path('cogs').iterdir():
            if not ext.name.endswith('.py') or ext.name.startswith('__'):
                continue

            if f'cogs.{(ext := ext.name.replace('.py', ''))}' in self.bot.extensions:
                text = f'<:Tick:857994584198086666> **Active** `cogs.{ext}`'
            else:
                text = f'<:Cross:941933851096285225> **Inactive** `cogs.{ext}`'

            rows.append(text)
            
        e = discord.Embed(colour=0xC0C0C0, description='\n'.join(rows))
        e.set_author(name='Modules', icon_url=self.bot.user.display_avatar)  # pyright: ignore
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(cog := LazyHotReload(bot))
    asyncio.create_task(cog._populate())
