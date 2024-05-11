from __future__ import annotations
from typing import TYPE_CHECKING, Callable, TypeVar, Generic, Any

import discord
from discord.ext import commands

from .emotes import CROSS_EMOTE, CHECK_EMOTE
if TYPE_CHECKING:
    from bot import RoboDan

T = TypeVar('T')


class ConfirmationView(discord.ui.View):
    def __init__(self, *, timeout: float, author_id: int, disable: bool, delete_after: bool) -> None:
        super().__init__(timeout=timeout)
        self.value: bool | None = None
        self.delete_after: bool = delete_after
        self.disable: bool = disable
        self.author_id: int = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.author_id:
            return True
        else:
            await interaction.response.send_message('This confirmation dialog is not for you.', ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        if self.delete_after and self.message:
            await self.message.delete()

    async def disable_buttons(self, interaction: discord.Interaction) -> None:
        for i in self.children:
            i.disabled = True  # type: ignore
        await interaction.message.edit(view=self)  # type: ignore

    @discord.ui.button(label='Confirm', emoji=CHECK_EMOTE, style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_response()
        if not self.delete_after and self.disable:
            await self.disable_buttons(interaction)
        self.stop()

    @discord.ui.button(label='Cancel', emoji=CROSS_EMOTE, style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_response()
        if not self.delete_after and self.disable:
            await self.disable_buttons(interaction)
        self.stop()


class DisambiguatorView(discord.ui.View, Generic[T]):
    message: discord.Message
    selected: T

    def __init__(self, ctx: Context, data: list[T], entry: Callable[[T], Any]):
        super().__init__()
        self.ctx: Context = ctx
        self.data: list[T] = data

        options = []
        for i, x in enumerate(data):
            opt = entry(x)
            if not isinstance(opt, discord.SelectOption):
                opt = discord.SelectOption(label=str(opt))
            opt.value = str(i)
            options.append(opt)

        select = discord.ui.Select(options=options)

        select.callback = self.on_select_submit
        self.select = select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message('This select menu is not meant for you, sorry.', ephemeral=True)
            return False
        return True

    async def on_select_submit(self, interaction: discord.Interaction):
        index = int(self.select.values[0])
        self.selected = self.data[index]
        await interaction.response.defer()
        if not self.message.flags.ephemeral:
            await self.message.delete()

        self.stop()


class Context(commands.Context):
    bot: RoboDan

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def prompt(
        self,
        message: str | None = None,
        *,
        timeout: float = 60.0,
        delete_after: bool = True,
        disable: bool = False,
        author_id: int | None = None,
        embed: discord.Embed | None = None
    ) -> bool | None:
        """An interactive reaction confirmation dialog.
        Parameters
        -----------
        message: str
            The message to show along with the prompt.
        timeout: float
            How long to wait before returning.
        delete_after: bool
            Whether to delete the confirmation message after we're done.
        disable: bool
            Whether to disable the buttons or not after an interaction.
        author_id: Optional[int]
            The member who should respond to the prompt. Defaults to the author of the
            Context's message.
        embed: Optional[discord.Embed]
            An embed to send instead of the content, if provided.
        Returns
        --------
        PromptResponse
            status: bool
                ``True`` if explicit confirm,
                ``False`` if explicit deny,
                ``None`` if deny due to timeout``
            message: discord.Message
                The message that the prompt view is attached to
        """

        author_id = author_id or self.author.id
        view = ConfirmationView(
            timeout=timeout,
            delete_after=delete_after,
            disable=disable,
            author_id=author_id,
        )
        if embed:
            view.message = await self.channel.send(embed=embed, view=view)
        else:
            view.message = await self.channel.send(message, view=view)
        await view.wait()
        return view.value

    async def disambiguate(self, matches: list[T], entry: Callable[[T], Any], *, ephemeral: bool = False) -> T:
        if len(matches) == 0:
            raise ValueError('No results found.')

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 25:
            raise ValueError('Too many results... sorry.')

        view = DisambiguatorView(self, matches, entry)
        view.message = await self.send(
            'There are too many matches... Which one did you mean?', view=view, ephemeral=ephemeral
        )
        await view.wait()
        return view.selected

    async def affirm(self, message: str, /):
        await self.send(embed=discord.Embed(colour=0x8BC34A, description=message))

    async def deny(self, message: str, /):
        await self.send(embed=discord.Embed(colour=0xF44336, description=message))


class GuildContext(Context):
    author: discord.Member
    guild: discord.Guild
    channel: discord.VoiceChannel | discord.TextChannel | discord.Thread
    me: discord.Member
    prefix: str
