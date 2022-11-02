import asyncio
import functools
import tempfile
from typing import Literal
from pathlib import Path

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from main import Bot
from utils.context import GuildContext


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


class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(aliases=['dl'])
    @app_commands.rename(_format='format')
    async def download(self, ctx: GuildContext, query: str, _format: Literal['mp4', 'mp3']):
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
                    file_name=path.name,
                    bucket_id=self.bot.config['backblaze']['bucket_id'],
                )
                link = f'https://cdn.overseer.tech/file/imooog/{file.name}'
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label='Go to video', url=link))
                await ctx.send((
                    'Your file has exceeded 8mb, therefore it has been uploaded here **(expires in 5 minutes)**:\n'
                    f'{link}'), view=view
                )
                await asyncio.sleep(300)
                await self.bot.bucket.delete_file(file.name, file.id)


async def setup(bot: Bot):
    await bot.add_cog(YouTube(bot))
