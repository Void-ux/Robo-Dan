from __future__ import annotations

import tempfile
from io import BytesIO
from typing import TYPE_CHECKING

import discord
import wave
import whisper
import logging
from discord.ext import commands, voice_recv
from discord.ext.voice_recv import VoiceData, AudioSink, SilenceGeneratorSink
from discord.opus import Decoder as OpusDecoder

if TYPE_CHECKING:
    from bot import RoboDan
    from utils.context import GuildContext

log = logging.getLogger(__name__)


def transcribe(buff: BytesIO, model_name: str):
    model = whisper.load_model(model_name)
    with tempfile.NamedTemporaryFile('wb+') as file:
        buff.seek(0)
        file.write(buff.read())
        file.seek(0)
        return whisper.transcribe(model, file.name, language='English', fp16=False)


class DummySink(AudioSink):
    def __init__(self):
        super().__init__()

    def wants_opus(self) -> bool:
        return False

    def write(self, user: discord.User | discord.Member | None, data: VoiceData):
        ...

    def cleanup(self):
        ...

    def __repr__(self) -> str:
        return 'DummySink'


class RotatingWaveSink(SilenceGeneratorSink):
    """Endpoint AudioSink that generates a wav file.
    Best used in conjunction with a silence generating sink. (TBD)
    """

    CHANNELS = OpusDecoder.CHANNELS
    SAMPLE_WIDTH = OpusDecoder.SAMPLE_SIZE // OpusDecoder.CHANNELS
    SAMPLING_RATE = OpusDecoder.SAMPLING_RATE

    def __init__(self, bot: RoboDan, recorder: discord.Member, channel: discord.VoiceChannel | discord.StageChannel):
        super().__init__(DummySink())
        self.bot = bot
        self.recorder = recorder
        self.channel = channel

        self._wave_file = self._create_file()
        self._file_count: int = 1

    def wants_opus(self) -> bool:
        return False

    def _create_file(self) -> wave.Wave_write:
        self._file = BytesIO()

        file = wave.open(self._file, 'wb')
        file.setnchannels(self.CHANNELS)
        file.setsampwidth(self.SAMPLE_WIDTH)
        file.setframerate(self.SAMPLING_RATE)

        return file

    def _generate_transcript(self) -> None:
        self._wave_file.close()
        file_name = f'{self.channel.name}_transcript_{self._file_count}'
        self.bot.dispatch('transcript_complete', self.recorder, self._file, file_name)

    def write(self, user: discord.User | None, data: VoiceData):
        super().write(user, data)
        if self._wave_file.getnframes() / self._wave_file.getframerate() >= 8:
            # 8 secs
            self._generate_transcript()
            self._wave_file = self._create_file()
            self._file_count += 1

        self._wave_file.writeframes(data.pcm)

    @AudioSink.listener()
    def on_voice_member_disconnect(self, member: discord.Member, ssrc: int | None):
        self._generate_transcript()
        del self._wave_file

    def cleanup(self):
        super().cleanup()
        try:
            self._wave_file.close()
        except Exception:
            log.info("WaveSink got error closing file on cleanup", exc_info=True)


class STT(commands.Cog):
    def __init__(self, bot: RoboDan):
        self.bot = bot

    @commands.hybrid_command(aliases=['conn'])
    async def connect(self, ctx: GuildContext):
        if not ctx.author.voice:
            return await ctx.send("You need to be in a VC to use this command.")
        assert ctx.author.voice.channel is not None

        vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
        vc.listen(RotatingWaveSink(self.bot, ctx.author, ctx.author.voice.channel))

    @commands.hybrid_command(aliases=['dc'])
    async def disconnect(self, ctx: GuildContext):
        if not ctx.voice_client:
            return await ctx.send("I'm not recording anything in any VCs at the moment.")

        await ctx.voice_client.disconnect(force=False)

    @commands.Cog.listener()
    async def on_transcript_complete(self, recorder: discord.Member, buff: BytesIO, file_name: str):
        transcript = await self.bot.loop.run_in_executor(None, transcribe, buff, 'small.en')
        try:
            await recorder.send(f"Transcript of {file_name} produced:```{transcript['text']}```")
        except discord.Forbidden:
            return


async def setup(bot: RoboDan):
    await bot.add_cog(STT(bot))
