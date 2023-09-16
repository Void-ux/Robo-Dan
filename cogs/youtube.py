from __future__ import annotations

import functools
import os
import uuid
import time
from urllib.parse import quote
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


def download(url: str, file_name: str, _format: Literal['audio', 'all']) -> dict | None:
    path = Path(__file__).parent / 'downloads'
    ydl_opts = {
        'concurrent_fragment_downloads': 2,
        'extract_flat': 'discard_in_playlist',
        'final_ext': 'mkv',
        'format': 'bv*+ba/b',
        'fragment_retries': 10,
        'ignoreerrors': 'only_download',
        'merge_output_format': 'mkv',
        'outtmpl': {
            'default': f'{str(path)}/{file_name}.%(ext)s',
            'pl_thumbnail': ''
        },
        'postprocessors': [
            {
                'format': 'png',
                'key': 'FFmpegThumbnailsConvertor',
                'when': 'before_dl'
            },
            {
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': 'mkv'
            },
            {
                'add_chapters': True,
                'add_infojson': True,
                'add_metadata': True,
                'key': 'FFmpegMetadata'
            },
            {
                'already_have_thumbnail': False,
                'key': 'EmbedThumbnail'
            },
            {
                'key': 'FFmpegConcat',
                'only_multi_video': True,
                'when': 'playlist'
            }
        ],
        'retries': 10,
        'writethumbnail': True
    }

    if _format == 'all':
        # Download best format that contains video,
        # and if it doesn't already have an audio stream,
        # merge it with best audio-only format
        ydl_opts['format'] = 'bv*+ba/b'
    elif _format == 'audio':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['prefer_ffmpg'] = True
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
        }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url)
        ydl.download([url])

    return info


class DownloadControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Delete', style=discord.ButtonStyle.red, custom_id='downloadcontrols:delete')  # type: ignore
    async def callback(self, interaction: Interaction, button: discord.ui.Button):
        query = """SELECT file_name, file_id FROM files
                   WHERE message_id=$1
                """
        file_name, file_id = await interaction.client.pool.fetchrow(query, interaction.message.id)  # type: ignore

        await interaction.client.bucket.delete_file(file_name, file_id)

        button.disabled = True
        await interaction.message.edit(view=self)  # type: ignore

        await interaction.response.send_message(
            embed=affirmation_embed(
                "Your file has been successfully **deleted**\nYou may still be able view it using the link due to caching"
                )
        )


class YouTube(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.hybrid_command(aliases=['yt'])
    @commands.is_owner()
    @app_commands.rename(_format='format')
    @app_commands.choices(
        _format=[
            app_commands.Choice(name='Audio and Video', value='all'),
            app_commands.Choice(name='Audio', value='audio')
        ]
    )
    async def yt_download(self, ctx: GuildContext, query: str, _format: Literal['audio', 'all'] = 'all'):
        """
        Downloads a video from one of thousands of hosts online such as YouTube, Reddit, TikTok, etc.

        `Audio and Video` will download the highest quality format with video, and if it doesn't have an audio
        stream, it'll merge it with the best audio-only format. It'll be returned as a `.mkv` so that the thumbnail can be
        embedded.
        `Audio` will download the best audio-only format. The format will not change to prevent data loss.
        """
        await ctx.typing()
        uuid_ = str(uuid.uuid4())

        # We use partial to make the code look cleaner, even though we
        # could technically pass it in to run_in_executor
        partial = functools.partial(download, query, uuid_, _format)

        start = time.perf_counter()
        info = await self.bot.loop.run_in_executor(None, partial)
        end = time.perf_counter()
        download_time = end - start
        if info is None:
            title = uuid.uuid4()
            ext = 'mkv'
        else:
            title = info['title']
            ext = info['ext']

        file = [i for i in (Path(__file__).parent / 'downloads').iterdir() if i.name.startswith(uuid_)][0]
        file_name = f"{title}.{ext}"

        # bots have a limit of 8mb per file
        try:
            if len(file.read_bytes()) <= 8_388_608:
                await ctx.reply(
                    f'Took `{download_time:.2f}` seconds to download.',
                    file=discord.File(fp=file, filename=file_name)
                )
            else:
                # avoid overwriting the OS file defined above
                start = time.perf_counter()
                file_ = await self.bot.bucket.upload_file(
                    content_bytes=file.read_bytes(),
                    content_type='video/x-matroska',
                    file_name=f'downloads/{file_name}',
                    bucket_id=self.bot.config['backblaze']['bucket_id'],
                )
                end = time.perf_counter()
                upload_time = end - start
                link = f'https://cdn.void-ux.com/file/imooog/downloads/{quote(file_name)}'

                view = DownloadControls()
                # we want to add the link here as passing it into the __init__ would cause problems
                # with bot.add_view in main.py
                view.add_item(discord.ui.Button(label='Go to video', url=link))

                msg = await ctx.reply(
                    f"Took `{download_time:.2f}` seconds to download and `{upload_time:.2f}` seconds to upload.\n"
                    f"If there's no video embed below, click the URL to view it in your browser.\n{link}",
                    view=view
                )
                await self.bot.pool.execute(
                    'INSERT INTO files (message_id, file_name, file_id) VALUES ($1, $2, $3)',
                    msg.id, file_.name, file_.id
                )
        finally:
            os.remove(str(file))


async def setup(bot: Bot):
    await bot.add_cog(YouTube(bot))
