from __future__ import annotations

import datetime
import textwrap
import time
import logging
import asyncio
import re
from urllib.parse import quote
from typing import TYPE_CHECKING, Literal

import aiohttp
import humanize
import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import find
from bs4 import BeautifulSoup

from utils.context import GuildContext
from utils.interaction import Interaction
from utils.sonarr import Client as SonarrClient
from utils.models.sonarr import SeriesPayload, EpisodePayload, EpisodeFilePayload

if TYPE_CHECKING:
    from bot import RoboDan

log = logging.getLogger(__name__)


class EpisodeSelectorModal(discord.ui.Modal, title='Choose your episodes'):
    season = discord.ui.TextInput(label='Season Number', placeholder='1', max_length=2, style=discord.TextStyle.short)

    episode_range = discord.ui.TextInput(label='Episode(s)', placeholder='e.g. 1-5, 7, 3-6', style=discord.TextStyle.short)

    async def on_submit(self, itx: Interaction):
        try:
            self.season_number = int(str(self.season))
        except ValueError:
            return await itx.response.send_message('The season number must be a... number, you silly goose!')

        try:
            episode = int(str(self.episode_range))
            self.episodes = range(episode, episode + 1)
        except ValueError:
            bounds = str(self.episode_range).split('-')
            if len(bounds) != 2:
                return await itx.response.send_message(textwrap.dedent("""
                    Please provide a valid episode range. This could be in the format of:
                    - `1-5`, `3-6`, etc. meaning "download episodes 1, 2, 3, 4, 5", and download episodes "3, 4, 5, 6"
                    respectively.
                    - `1`, `6`, `15`, etc. meaning "download just episode 1", etc.
                """))

            lb, ub = bounds
            try:
                lb, ub = int(lb), int(ub)
            except ValueError:
                return await itx.response.send_message('Episode ranges must be numbers!')

            self.episodes = range(lb, ub + 1)  # make the upper bound inclusive

        await itx.response.defer()
        self.stop()


class SeriesSelector(discord.ui.Select):
    def __init__(self, tv_shows: list[SeriesPayload]):
        self.tv_shows = tv_shows
        options = [
            discord.SelectOption(
                label=f"{textwrap.shorten(i['title'], width=100, placeholder='...')} ({i['year']})",
                value=str(i['tvdbId'])
            ) for i in tv_shows
        ]
        options[0].default = True

        super().__init__(placeholder=tv_shows[0]['title'], options=options, row=0)

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()
        assert interaction.message is not None
        assert self.view is not None

        series = find(lambda x: str(x['tvdbId']) == self.values[0], self.tv_shows)
        assert series is not None
        e = await series_embed(series, interaction.client.session)

        series_exists_locally = bool(await interaction.client.sonarr.get_series(series['tvdbId']))
        if series_exists_locally:
            self.view.add_series.disabled = True
            self.view.exists = True
        else:
            self.view.exists = False

        self.view.placeholder = None
        await interaction.message.edit(embed=e, view=self.view)
        # updates the view instance for when the download/bookmark
        # button is pressed
        self.view.series = series


class DownloadPanel(discord.ui.View):
    def __init__(self, tv_shows: list[SeriesPayload], author_id: int, *, bot: RoboDan):
        super().__init__(timeout=60)
        self.add_item(SeriesSelector(tv_shows))

        self.author_id = author_id
        self.bot = bot
        self.message: discord.Message | None = None

        self.series: SeriesPayload = tv_shows[0]
        self.action: Literal['add_series', 'episode'] | Literal[False] | None = None
        self.episodes: range | None = None
        self.season: int | None = None
        self.exists: bool | None = None

    async def prepare(self):
        self.exists = bool(await self.bot.sonarr.get_series(self.series['tvdbId']))

    async def interaction_check(self, interaction: Interaction) -> bool:
        assert interaction.message is not None
        if interaction.user.id == self.author_id:
            return True
        else:
            await interaction.response.send_message('Sorry, this is not your prompt to repond to')
            return False

    async def disable_buttons(self):
        assert self.message is not None

        for i in self.children:
            i.disabled = True  # type: ignore

        await self.message.edit(view=self)

    async def on_timeout(self) -> None:
        await self.disable_buttons()

    @discord.ui.button(label='Bookmark Series', style=discord.ButtonStyle.green, row=1)  # type: ignore
    async def add_series(self, itx: Interaction, _: discord.ui.Button):
        await self.disable_buttons()
        self.action = 'add_series'
        await itx.response.defer()
        self.stop()

    @discord.ui.button(label='Download Episodes', style=discord.ButtonStyle.green, row=1)  # type: ignore
    async def download_episode(self, itx: Interaction, _: discord.ui.Button):
        modal = EpisodeSelectorModal()
        await itx.response.send_modal(modal)
        await modal.wait()

        self.action = 'episode'
        self.episodes = modal.episodes
        self.season = modal.season_number
        await self.disable_buttons()
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.red, row=1)  # type: ignore
    async def cancel(self, itx: Interaction, _: discord.ui.Button):
        await self.disable_buttons()
        assert itx.message is not None
        self.action = False

        e = itx.message.embeds[0].copy()
        e.colour = 0xDB515A
        await itx.response.edit_message(embed=e)
        self.stop()


def chunk_file(file, chunk_size: int) -> bytes:
    return file.read(chunk_size)


async def monitor_download(
    ctx: GuildContext,
    episode: EpisodePayload,
    keep: bool = True
) -> tuple[EpisodeFilePayload, str] | None:
    """Returns a link to the episode if it is downloaded within 10 minutes.

    This will check if it has been downloaded every 10 seconds.
    """
    start = time.perf_counter()
    while not episode['hasFile']:
        await asyncio.sleep(10)
        episode = await ctx.bot.sonarr.get_episode(episode['id'])
    end = time.perf_counter()

    episode_file = await ctx.bot.sonarr.get_episode_file(f"{episode['episodeFileId']}")  # type: ignore
    log.info('Sonarr downloaded %s in ~%.2f seconds', episode_file['size'], end-start)

    ext = episode_file['path'].split('.')[-1]
    file_name = f"{episode['series']['title']}/S{episode['seasonNumber']:02}/{episode['title']}.{ext}"

    large_file = await ctx.bot.bucket.upload_large_file(
        ctx.bot.config['backblaze']['bucket_id'],
        f'sonarr/{file_name}'
    )
    start = time.perf_counter()
    with open(episode_file['path'], 'rb') as file:
        while True:
            start_ = time.perf_counter()
            chunk = await ctx.bot.loop.run_in_executor(None, chunk_file, file, large_file.recommended_part_size)
            end_ = time.perf_counter()
            log.debug('Reading chunk of %s took %.2f seconds', humanize.naturalsize(len(chunk)), end_-start_)

            if len(chunk) == 0:
                break
            await large_file.upload_part(chunk)
    end = time.perf_counter()
    log.info('%s took %s seconds to chunk and upload', episode['title'], end-start)

    if not keep:
        start = time.perf_counter()
        await ctx.bot.sonarr.delete_episode(episode_file)
        end = time.perf_counter()
        log.info(
            'Deleting %s with size %s took %.2f seconds',
            episode_file['path'],
            humanize.naturalsize(episode_file['size']),
            end-start
        )

    file = await large_file.finish()
    return episode_file, f'https://cdn.void-ux.com/file/imooog/sonarr/{quote(file_name)}'


async def get_rotten_tomatoes_rating(series_name: str, session: aiohttp.ClientSession) -> tuple[int, int] | None:
    series_name = series_name.replace(' ', '_').lower()
    async with session.get(f'https://rottentomatoes.com/tv/{series_name}') as response:
        content = await response.text()

    soup = BeautifulSoup(content, features='lxml')
    tomatometer = soup.find('span', {'data-qa': 'tomatometer'})
    audience_score = soup.find('span', {'data-qa': 'audience-score'})
    if tomatometer is not None and audience_score is not None:
        reg = re.compile(r'[0-9]+')
        tomatometer = reg.search(tomatometer.text).group(0)  # type: ignore
        audience_score = reg.search(audience_score.text).group(0)  # type: ignore
        return int(tomatometer), int(audience_score)


async def series_embed(series: SeriesPayload, session: aiohttp.ClientSession) -> discord.Embed:
    first_aired = datetime.datetime.fromisoformat(series['firstAired'][:-1])
    start = time.perf_counter()
    rotten_tomatoes = await get_rotten_tomatoes_rating(series['title'], session)
    end = time.perf_counter()
    log.info('Fetched Rotten Tomatoes rating in %.2f seconds' % (end-start, ))

    e = discord.Embed(
        colour=0x8BC34A,
        title=series['title'],
        description=textwrap.shorten(series['overview'], 250, placeholder='...')
    )
    for image in series['images']:
        if image['coverType'] == 'fanart':
            e.set_image(url=image['remoteUrl'])
        elif image['coverType'] == 'poster':
            e.set_thumbnail(url=image['remoteUrl'])

    e.add_field(name='Status', value=series['status'].title())
    e.add_field(name='Network', value=series['network'])
    e.add_field(name='First Aired', value=first_aired.strftime('%b %-d, %Y'))

    e.add_field(name='Number of Seasons', value=len(series['seasons']))
    if rotten_tomatoes is not None:
        if rotten_tomatoes[0] < 60:
            tomato = '<:splat:1066627064289054790>'
        else:
            tomato = '<:tomato:1066627222175227935>'
        if rotten_tomatoes[1] < 60:
            popcorn = '<:spilled_popcorn:1066627062590341200>'
        else:
            popcorn = '<:popcorn:1066627067023724576>'

        e.add_field(name='Rating', value=f'{tomato} {rotten_tomatoes[0]}% {popcorn} {rotten_tomatoes[1]}%')

    e.set_footer(text=', '.join(series['genres']).title())

    return e


class Sonarr(commands.Cog):
    def __init__(self, bot: RoboDan):
        self.bot = bot

    async def get_imdb_rating(self, imdb_id: str) -> float | None:
        # IMDb returns a 403 Forbidden when a User-Agent isn't given
        async with self.bot.session.get(f'https://imdb.com/title/{imdb_id}', headers={'User-Agent': ''}) as response:
            content = await response.text()

        soup = BeautifulSoup(content, features="html5lib")
        rating = soup.find(class_='sc-7ab21ed2-1 eUYAaq')
        if rating is not None:
            rating = float(rating.text)

        return rating        

    async def monitor_episode(
        self,
        episode: EpisodePayload,
        ctx: GuildContext
    ) -> None:
        """Handles the monitoring of an episode's download and sends it to the Discord channel upon it completeing successfully."""

        e = discord.Embed(
            colour=0xFF9800,
            title=episode['title'],
            description=textwrap.shorten(episode['overview'], 250, placeholder='...')
        )
        e.set_image(url=episode['images'][0].get('url') or episode['images'][0].get('remoteUrl'))
        e.set_footer(text='Once an episode is downloaded, the link to it will be edited into this embed')
        m = await ctx.send(embed=e)

        try:
            task = await asyncio.wait_for(monitor_download(ctx, episode), timeout=900)
        except asyncio.TimeoutError:
            e.description = "Downloading episode(s) timed out, this is most likely because the requested quality and language couldn't be found"
            e.colour = 0xDB515A
            await m.edit(embed=e)
            return
        else:
            if task is None:
                e.description = 'Episode(s) failed to download...'
                e.colour = 0xDB515A
                await m.edit(embed=e)
                return
            episode_file, url = task

            e.url = url
            e.colour = 0x8BC34A
            e.remove_footer()

            e.add_field(name='Resolution', value=episode_file['mediaInfo']['resolution'])
            e.add_field(name='Video Codec', value=episode_file['mediaInfo']['videoCodec'])
            e.add_field(name='Audio Codec', value=episode_file['mediaInfo']['audioCodec'])
            
            if len(time := episode_file['mediaInfo']['runTime'].split(':')) == 2:
                minutes, seconds = time
                time = humanize.precisedelta(datetime.timedelta(minutes=int(minutes), seconds=int(seconds)))
            elif len(time) == 3:
                hours, minutes, seconds = time
                time = humanize.precisedelta(
                    datetime.timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds))
                )
            else:
                time = 'Unknown'
            e.add_field(
                name='Length',
                value=time
            )
            e.add_field(name='FPS', value=episode_file['mediaInfo']['videoFps'])
            e.add_field(name='Size', value=humanize.naturalsize(episode_file['size']))

            await m.edit(embed=e)
            await self.bot.sonarr.delete_episode(await self.bot.sonarr.get_episode_file(episode['id']))


    @commands.hybrid_command(aliases=['dl'])
    @app_commands.choices(quality_profile=[
        app_commands.Choice(name='Ultra-HD', value=5),
        app_commands.Choice(name='HD-1080p', value=4),
        app_commands.Choice(name='HD-720p/1080p', value=6)
    ])
    @app_commands.describe(
        search_phrase='The TV show to look up',
        quality_profile='The quality at which to download the TV show at'
    )
    async def download(
        self,
        ctx: GuildContext,
        *,
        search_phrase: str,
        quality_profile: int = 4
    ):
        """Add a TV show to Sonarr

        Quality profiles dictate what quality each episode can be, the existing ones are:
        - Ultra-HD
        > Bluray-2160p Remux
        > Bluray-2160p
        > WEB 2160p
        > HDTV-2160p
        - HD-1080p
        > Bluray-1080p Remux
        > Bluray-1080p
        > WEB 1080p
        > HDTV-1080p
        - HD-720p/1080p
        > Bluray-1080p Remux
        > Bluray-1080p
        > WEB 1080p
        > Bluray-720p
        > WEB 720p
        > Raw-HD
        > HDTV-1080p
        > HDTV-720p

        The specific quality specifications per profile are in preferential order.
        """
        await ctx.typing()

        tv_shows = await self.bot.sonarr.look_up_series(search_phrase)
        if len(tv_shows) == 0:
            return await ctx.send(f'Sorry, nothing was found for {search_phrase}...')

        view = DownloadPanel(tv_shows[:25], ctx.author.id, bot=self.bot)
        await view.prepare()
        e = await series_embed(tv_shows[0], self.bot.session)
        prompt = view.message = await ctx.send(embed=e, view=view)
        await view.wait()

        if not view.action:
            return

        assert view.series is not None
        assert view.exists is not None
        series = view.series
        series_exists_locally = view.exists

        # this'll handle add_series/bookmark and ensure
        # adding episodes doesn't break
        if not series_exists_locally:
            series = await self.bot.sonarr.add_series(
                tvdb_id=series['tvdbId'],
                quality_profile_id=quality_profile,
                root_dir='/data/media',
                monitored=False
            )
            await asyncio.sleep(3)

        if view.action == 'episode':
            assert view.season is not None
            assert view.episodes is not None
                
            episodes = await self.bot.sonarr.get_episodes(series['id'], view.season, view.episodes)
            await self.bot.sonarr.download_episodes([i['id'] for i in episodes])

            links = "[The TVDB]({tvdb}) / [Trakt]({trakt}) / [IMDb]({imdb})"

            e.clear_fields()
            e.timestamp = discord.utils.utcnow()
            e.add_field(
                name='Quality',
                value={1: 'Any', 4: 'HD-1080p', 6: 'HD - 720p/1080p', 5: 'Ultra-HD'}.get(quality_profile)
            )
            e.add_field(name='Number of Episodes', value=len(view.episodes))
            e.add_field(name='Language', value='English')
            e.add_field(
                name='Links',
                value=links.format(
                    tvdb=f"https://thetvdb.com/?tab=series&id={series['tvdbId']}",
                    trakt=f"https://trakt.tv/search/tvdb/{series['tvdbId']}?id_type=show",
                    imdb=f"https://www.imdb.com/title/{series['imdbId']}"
                )
            )
            await prompt.edit(embed=e, view=None)

            for episode in episodes:
                episode = await self.bot.sonarr.get_episode(episode['id'])
                await self.monitor_episode(episode, ctx)

async def setup(bot: RoboDan):
    if not hasattr(bot, 'sonarr'):
        bot.sonarr = SonarrClient(bot.config['sonarr']['api_key'], host=bot.config['sonarr']['host'])

    await bot.add_cog(Sonarr(bot))
