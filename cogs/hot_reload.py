import os
import logging
import importlib.util
from pathlib import Path

from discord.ext import commands

from utils.interaction import Interaction
from utils.context import Context

log = logging.getLogger(__name__)
IGNORE_EXTENSIONS = ('Jishaku', )


def get_last_modified(extension: str) -> int:
    spec = importlib.util.find_spec(extension, None)
    return os.path.getmtime(spec.origin)  # pyright: ignore


class LazyHotReload(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_modified_times: dict[str, float | None] = {}
        self.bot.add_check(self.lazy_reload)
        self._old_interaction_check = self.bot.tree.interaction_check
        self.bot.tree.interaction_check = self.interaction_check  # pyright: ignore

    async def _reload_extension(self, extension: str) -> int:
        try:
            await self.bot.reload_extension(extension)
        except commands.ExtensionError:
            log.error("\x1b[31mCouldn't reload extension: %s\x1b[0m", extension)
            return 1
        else:
            log.info('\x1b[32m✔ Reloaded extension: %s\x1b[0m', extension)
            return 0

    async def interaction_check(  # pyright: ignore
        self,
        interaction: Interaction,
        /
    ) -> bool:
        failure = await self._old_interaction_check(interaction)  # pyright: ignore
        if failure:
            return True

        extension = __name__
        last_modified = get_last_modified(extension)

        if last_modified > self.last_modified_times[extension]:
            failure = await self._reload_extension(extension)
            if not failure:
                self.last_modified_times[extension] = last_modified
                ctx = await Context.from_interaction(interaction)
                command = self.bot.get_command(ctx.command.qualified_name)  # pyright: ignore 
                ctx.command = command

                await self.bot.invoke(ctx)
                return False

        return True

    async def populate_last_modified_times(self) -> None:
        await self.bot.wait_until_ready()

        for extension in self.bot.extensions.keys():
            if extension in IGNORE_EXTENSIONS:
                continue

            last_modified = get_last_modified(extension)
            self.last_modified_times[extension] = last_modified

    async def lazy_reload(self, ctx: commands.Context) -> bool:
        assert ctx.command is not None

        if ctx.command.cog_name and ctx.command.cog_name in IGNORE_EXTENSIONS:
            return True

        if self.last_modified_times == {}:
            await self.populate_last_modified_times()
            return True

        extension = ctx.command.module
        last_modified = get_last_modified(extension)

        if self.last_modified_times[extension] and last_modified > self.last_modified_times[extension]:
            failure = await self._reload_extension(extension)
            if not failure:
                self.last_modified_times[extension] = last_modified
                command = self.bot.get_command(ctx.command.qualified_name)
                ctx.command = command

                await self.bot.invoke(ctx)
                return False

        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(LazyHotReload(bot))
