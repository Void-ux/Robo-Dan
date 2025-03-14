from __future__ import annotations

import enum
import textwrap
import uuid
import time
import traceback
from pathlib import Path
from collections import namedtuple
from urllib.parse import quote
from typing import TYPE_CHECKING, Any

import discord
import humanize
import yarl
import yt_dlp
import ffmpeg
from aiob2 import File, LargeFile
from discord import app_commands
from discord.ext import commands
from jishaku.functools import executor_function

from utils import affirmation_embed
from utils.interaction import Interaction

if TYPE_CHECKING:
    from bot import RoboDan
    from utils.interaction import Interaction
    from utils.context import Context


class MediaFormat(str, enum.Enum):
    AUDIO = 'Audio'
    VIDEO = 'Audio and Video'


@executor_function
def download(url: str, file_name: str, format: MediaFormat):
    path = Path('/tmp/.ytdownloads')
    ydl_opts = {
        'concurrent_fragment_downloads': 2,
        'extract_flat': 'discard_in_playlist',
        'final_ext': 'mp4',
        'format': 'bv*+ba/b',
        'fragment_retries': 10,
        'merge_output_format': 'mp4',
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
                'preferedformat': 'mp4'
            },
            {
                'add_chapters': True,
                'add_infojson': False,
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

    if format == MediaFormat.VIDEO:
        # Download best format that contains video,
        # and if it doesn't already have an audio stream,
        # merge it with best audio-only format
        ydl_opts['format'] = 'bv*+ba/b'
    elif format == MediaFormat.AUDIO:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['prefer_ffmpg'] = True
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
        }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        ydl.download([url])

    return info


VideoInfo = namedtuple('VideoInfo', (
    'file_name',
    'duration',
    'size',
    'bit_rate',
    'format',
    'metadata'
))


def get_video_info(path: Path):
    probe: dict[str, Any] = ffmpeg.probe(str(path))
    try:
        return VideoInfo(
            probe['format']['filename'],
            humanize.precisedelta(probe['format']['duration'], format='%0.0f'),
            humanize.naturalsize(probe['format']['size']),
            f"{humanize.naturalsize(probe['format']['bit_rate']).replace(' ', '')}/s",
            probe['format']['format'],
            probe['format']['tags']
        )
    except KeyError:
        return


class DownloadControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Delete', style=discord.ButtonStyle.red, custom_id='downloadcontrols:delete')  # type: ignore
    async def callback(self, interaction: Interaction, button: discord.ui.Button):
        query = """SELECT file_name, file_id FROM files
                   WHERE message_id=$1
                """
        row = await interaction.client.pool.fetchrow(query, interaction.message.id)  # type: ignore

        if row is None:
            return await interaction.response.send_message('Sorry, there is no record of this media being stored')

        await interaction.client.bucket.delete_file(*row)

        button.disabled = True
        await interaction.message.edit(view=self)  # type: ignore

        await interaction.response.send_message(
            embed=affirmation_embed(
                "Your file has been successfully **deleted**\nYou may still be able view it using the link due to caching"
                )
        )


class YouTube(commands.Cog):
    def __init__(self, bot: RoboDan):
        self.bot = bot

    async def _store_file_ref(self, message_id: int, file: File | LargeFile) -> None:
        await self.bot.pool.execute(
            'INSERT INTO files (message_id, file_name, file_id) VALUES ($1, $2, $3)',
            message_id, file.name, file.id
        )

    @commands.hybrid_group(invoke_without_command=True, aliases=['yt'], extras={'id': 45}, fallback='help')
    @app_commands.allowed_installs(guilds=True, users=True)
    async def youtube(self, ctx: Context):
        pass

    @youtube.command(name='download', aliases=['dl'])
    @app_commands.rename(format='format')
    @app_commands.describe(url='The URL of the video you would like to download', format='The output video format')
    async def youtube_download(self, ctx: Context, url: str, format: MediaFormat = MediaFormat.VIDEO):
        """
        Downloads a video from one of thousands of hosts online such as YouTube, Reddit, TikTok, etc.

        `Audio and Video` will download the highest quality format with video, and if it doesn't have an audio
        stream, it'll merge it with the best audio-only format. It'll be returned as a `.mkv` so that the thumbnail can be
        embedded.
        `Audio` will download the best audio-only format. The format will not change to prevent data loss.
        """
        await ctx.typing()
        uuid_ = str(uuid.uuid4())

        start = time.perf_counter()
        info = await download(url, uuid_, format)
        end = time.perf_counter()
        download_time = end - start

        if info is None:
            title = uuid.uuid4()
            ext = 'mp4'
        else:
            title = info['title']
            ext = info['ext']

        file = [i for i in Path('/tmp/.ytdownloads').iterdir() if i.name.startswith(uuid_)][0]
        file_name = f"{title}.{ext}"
        file_size = file.stat().st_size
        probe = get_video_info(file)
        info = ''
        if probe:
            info = textwrap.dedent(f"""```
                Title: {probe.file_name}
                Duration: {probe.duration}
                Size: {probe.size}
                Bit Rate: {probe.bit_rate}
                Format: {probe.format}
                Metadata: {', '.join(k for k in probe.metadata.keys())}```
            """)

        # bots have a limit of 8mb per file
        try:
            start = time.perf_counter()
            if file_size <= 8_388_608:
                return await ctx.send(
                    f'Took `{download_time:.2f}` seconds to download.' + info,
                    file=discord.File(fp=file, filename=file_name)
                )
            elif file_size <= (self.bot.bucket._http._recommended_part_size or 100_000_000):  # 100mb
                file_ = await self.bot.bucket.upload_file(
                    file_name=f'downloads/{file_name}',
                    content_bytes=file.read_bytes(),
                    content_type='video/x-matroska',
                    bucket_id=self.bot.config.bz_bucket_id
                )
            elif await self.bot.is_owner(ctx.author) or file_size <= 1_000_000_000:
                # avoid overwriting the OS file defined above
                large_file = await self.bot.bucket.upload_large_file(
                    file_name=f'downloads/{file_name}',
                    content_type='video/x-matroska',
                    bucket_id=self.bot.config.bz_bucket_id
                )
                await large_file.chunk_file(str(file))
                file_ = await large_file.finish()
            else:
                return await ctx.send('File too large!')
            end = time.perf_counter()
        except Exception:
            tb = traceback.format_exc()
            e = discord.Embed(
                description=f'```py\n{tb}```'  ,
                timestamp=discord.utils.utcnow() 
            )
            e.set_author(name='Something went wrong...', icon_url=ctx.author.display_avatar)
            await ctx.send(embed=e, ephemeral=True)
            raise
        finally:
            file.unlink()

        upload_time = end - start
        link = str(yarl.URL(self.bot.config.cdn_url).joinpath(quote(file_name)))

        view = DownloadControls()
        view.add_item(discord.ui.Button(label='Go to video', url=link))

        msg = await ctx.send(
            f"Took `{download_time:.2f}` seconds to download and `{upload_time:.2f}` seconds to upload.\n"
            f"If there's no video embed below, click the URL to view it in your browser.\n{link}" + info,
            view=view
        )
        await self._store_file_ref(msg.id, file_)


async def setup(bot: RoboDan):
    await bot.add_cog(YouTube(bot))
