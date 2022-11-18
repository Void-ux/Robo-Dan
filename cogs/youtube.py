from __future__ import annotations

import functools
import tempfile
from typing import Literal, TYPE_CHECKING
from pathlib import Path

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from utils import affirmation_embed
from utils.context import GuildContext
if TYPE_CHECKING:
    from main import Bot
    from utils.interaction import Interaction


def download(url: str, temp: tempfile._TemporaryFileWrapper, _format: Literal['mp3', 'mp4']) -> None:
    ydl_opts = {
        'outtmpl': temp.name,
        'updatetime': False,
        'overwrites': True
    }
    if _format == 'mp4':
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4'
    else:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        ydl_opts['prefer_ffmpg'] = True

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    temp.seek(0)


class DownloadControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Delete', style=discord.ButtonStyle.red, custom_id='downloadcontrols:delete')
    async def callback(self, interaction: Interaction, button: discord.ui.Button):
        query = """SELECT file_name, file_id FROM files
                   WHERE message_id=$1
                """
        file_name, file_id = await interaction.client.pool.fetchrow(query, interaction.message.id)

        await interaction.client.bucket.delete_file(file_name, file_id)

        button.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            embed=affirmation_embed("Your file has been successfully **deleted**\n"
                                    "You may still be able view it using the link due to caching")
        )


class YouTube(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.hybrid_command(aliases=['dl'])
    @commands.is_owner()
    @app_commands.rename(_format='format')
    async def download(self, ctx: GuildContext, query: str, _format: Literal['mp4', 'mp3'] = 'mp4'):
        await ctx.typing()

        with tempfile.NamedTemporaryFile(dir=Path(__file__).resolve().parent.parent, suffix=f'.{_format}') as temp:
            # We use partial to make the code look cleaner, even though we
            # could technically pass it in to run_in_executor
            partial = functools.partial(download, query, temp, _format)

            await self.bot.loop.run_in_executor(None, partial)
            path = Path(temp.name)
            try:
                await ctx.send(file=discord.File(fp=path, filename=f'output.{_format}'))
            except discord.HTTPException:
                file = await self.bot.bucket.upload_file(
                    content_bytes=path.read_bytes(),
                    content_type='video/webm',
                    file_name=f'downloads/{path.name}',
                    bucket_id=self.bot.config['backblaze']['bucket_id'],
                )
                link = f'https://cdn.overseer.tech/file/imooog/{file.name}'

                view = DownloadControls()
                # we want to add the link here as passing it into the __init__ would cause problems
                # with bot.add_view in main.py
                view.add_item(discord.ui.Button(label='Go to video', url=link))

                msg = await ctx.send(f'Your file has exceeded 8mb, therefore it has been uploaded here:\n{link}', view=view)
                await self.bot.pool.execute('INSERT INTO files (message_id, file_name, file_id) VALUES ($1, $2, $3)',
                                            msg.id, file.name, file.id)


async def setup(bot: Bot):
    await bot.add_cog(YouTube(bot))
