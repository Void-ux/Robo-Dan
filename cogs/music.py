import discord
import humanize
import wavelink
import datetime
import logging
import random

from main import Bot
from utils import error_embed
from utils.context import GuildContext
from utils.emotes import ONLINE, IDLE, OFFLINE, ARROW_RIGHT, GREY_BIN, CHECK_EMOTE
from wavelink.ext import spotify
from discord.ext import commands


class Music(commands.Cog):
    """Music related commands for VCs."""

    def __init__(self, bot: Bot):
        self.bot = bot

        bot.loop.create_task(self.connect_nodes())

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name='🌴')

    async def connect_nodes(self):
        """Connect to our Lavalink nodes."""
        await self.bot.wait_until_ready()

        self.bot.node = await wavelink.NodePool.create_node(
            bot=self.bot,
            host='lavalink',
            port=2333,
            password='2PjaAiYo*6U@e*',
            spotify_client=spotify.SpotifyClient(
                client_id=self.bot.config['music']['client_id'],
                client_secret=self.bot.config['music']['client_secret']
            )
        )

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: wavelink.Node):
        """Event fired when a node has finished connecting."""
        print(f'Node: <{node.identifier}> is ready!')

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, player: wavelink.Player, track: wavelink.Track, reason):  # noqa
        if player.queue.is_empty:
            return

        next_song = player.queue.get()
        await player.play(next_song)

    @commands.command(aliases=['pl'])
    async def play(self, ctx: GuildContext, *, query: str):
        """Play a song by name or YouTube/Soundcloud/Spotify URL. Playlists and albums are supported too!"""

        # Put this in ctx.typing because it can take a very long time with large playlists.
        async with ctx.typing():
            decoded = spotify.decode_url(query)
            if decoded is None or decoded['type'] is spotify.SpotifySearchType.unusable:
                tracks = await wavelink.YouTubeTrack.search(query, return_first=True)
                if tracks is None:
                    return await ctx.send(embed=error_embed("That's not a valid song to play!"))
                logging.info(f'YouTube Track Playing: {tracks}')
            else:
                if decoded['type'] in (spotify.SpotifySearchType.track, spotify.SpotifySearchType.album):
                    tracks = await spotify.SpotifyTrack.search(query=decoded["id"], type=decoded["type"], return_first=True)
                elif decoded['type'] == spotify.SpotifySearchType.playlist:
                    tracks = []
                    async for track in spotify.SpotifyTrack.iterator(query=query, type=spotify.SpotifySearchType.playlist):
                        tracks.append(track)

                logging.info(f'Spotify Track Playing: {tracks}')

        if not ctx.voice_client:
            vc: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            vc: wavelink.Player = ctx.voice_client

        queue = False
        if vc.queue.is_empty and not vc.is_playing():
            if isinstance(tracks, list):
                for c, i in enumerate(tracks):
                    if c == 0:
                        await vc.play(i)
                    else:
                        await vc.queue.put_wait(i)
                return await ctx.send(f'**Added:** {c + 1} songs to the queue.')

            else:
                await vc.play(tracks)
        else:
            queue = True
            if isinstance(tracks, list):
                c = 0
                for i in tracks:
                    await vc.queue.put_wait(i)
                    c += 1
                return await ctx.send(f'**Added:** {c} songs to the queue.')
            else:
                await vc.queue.put_wait(tracks)

        e = discord.Embed(colour=0x8BC34A)
        e.add_field(
            name=f"{'Added to Queue' if queue else 'Playing'}: {tracks.title}",
            value=f'Duration: {humanize.precisedelta(datetime.timedelta(seconds=tracks.duration))}'
        )
        e.set_author(name=ctx.author, icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=e)

    @commands.command(aliases=['dc'])
    async def disconnect(self, ctx: GuildContext):
        """Disconnects the bot from the voice channel."""
        if not ctx.voice_client:
            return await ctx.reply(embed=error_embed("I'm not connected to a voice channel!"))

        vc: wavelink.Player = ctx.voice_client
        await vc.stop()
        vc.queue.reset()
        await ctx.reply(f'{OFFLINE} **Disconnected** from {vc.channel.mention}')
        await vc.disconnect()

    @commands.command()
    async def pause(self, ctx: GuildContext):
        """Pauses the player."""
        if not ctx.voice_client:
            return await ctx.reply(embed=error_embed("I'm not connected to a voice channel!"))
        vc: wavelink.Player = ctx.voice_client
        await ctx.reply(f'{IDLE} **Paused:** {vc.track.title}')  # type: ignore
        await vc.pause()

    @commands.command(aliases=['unpause'])
    async def resume(self, ctx: GuildContext):
        """Unpauses the player."""
        if not ctx.voice_client:
            return await ctx.reply(embed=error_embed("I'm not connected to a voice channel!"))

        vc: wavelink.Player = ctx.voice_client
        await ctx.reply(f'{ONLINE} **Resumed:** {vc.track.title}')  # type: ignore
        await vc.resume()

    @commands.command()
    async def skip(self, ctx: GuildContext):
        """Skips to the next song in the queue."""
        if not ctx.voice_client:
            return await ctx.reply(embed=error_embed("I'm not connected to a voice channel!"))

        vc: wavelink.Player = ctx.voice_client
        if not vc.is_playing():
            return await ctx.send(embed=error_embed('The queue must have at least one item in it to skip!'))

        await ctx.reply(f'{ARROW_RIGHT} **Skipped:** {vc.track.title}')  # type: ignore
        await vc.stop()

    @commands.command()
    async def queue(self, ctx: GuildContext):
        """Displays the current queue of songs for the VC."""
        if (queue := ctx.voice_client.queue) is None or queue.is_empty:
            return await ctx.reply(embed=error_embed('The queue is empty!'))

        e = discord.Embed(colour=0x8BC34A, timestamp=discord.utils.utcnow())
        songs = []
        for c, i in enumerate(queue):
            if i.duration is not None:
                songs.append(f'**{c + 1}.** {i.title} - {humanize.precisedelta(datetime.timedelta(seconds=i.duration))}')
            else:
                songs.append(f'**{c + 1}.** {i.title}')
        e.set_author(name=f'Now Playing: {ctx.voice_client.track}')
        e.description = '\n'.join(songs)

        await ctx.send(embed=e)

    @commands.command(aliases=['cq'])
    async def clearqueue(self, ctx: GuildContext):
        """Clears the entire queue of all of its songs."""
        if (queue := ctx.voice_client.queue) is None or queue.is_empty:
            return await ctx.reply(embed=error_embed('The queue is empty!'))

        songs = len(queue)
        queue.reset()
        await ctx.reply(f'{GREY_BIN} **Cleared** {songs} songs.')

    @commands.command()
    async def shuffle(self, ctx: GuildContext):
        """Shuffles the current queue of songs."""
        if not ctx.voice_client:
            return await ctx.send(embed=error_embed("I'm not connected to a voice channel!"))

        if (queue := ctx.voice_client.queue) is None or queue.count == 1:
            return await ctx.send(embed=error_embed('The queue must have at least one item in it to shuffle!'))

        random.shuffle(ctx.voice_client.queue._queue)
        await ctx.send(f'{CHECK_EMOTE} **Shuffled** {len(queue)} songs.')

    @commands.command()
    async def song(self, ctx: GuildContext):
        """Displays the currently playing song."""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send(embed=error_embed("I'm not playing anything at the moment!"))

        await ctx.reply(f"🎵 **Playing:** {ctx.voice_client.track}")


async def setup(bot):
    await bot.add_cog(Music(bot))
