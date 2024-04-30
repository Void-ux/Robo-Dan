from __future__ import annotations

from typing import TYPE_CHECKING, IO

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


def transcribe(file: str, model_name: str):
    model = whisper.load_model(model_name)
    return whisper.transcribe(model, file, language='English', fp16=False)


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

    def __init__(self, bot: RoboDan):
        super().__init__(DummySink())
        self.bot = bot

        self._file = self._create_file('0_audio')
        self._file_count: int = 1

    def wants_opus(self) -> bool:
        return False

    def _create_file(self, name: str) -> wave.Wave_write:
        file = wave.open(name, 'wb')
        file.setnchannels(self.CHANNELS)
        file.setsampwidth(self.SAMPLE_WIDTH)
        file.setframerate(self.SAMPLING_RATE)
        return file

    def write(self, user: discord.User | None, data: VoiceData):
        super().write(user, data)
        if self._file.getnframes() / self._file.getframerate() >= 8:
            # 10 secs
            self._file.close()
            self.bot.dispatch('transcript_complete', f'{self._file_count}_audio')
            self._file = self._create_file(f'{self._file_count}_audio')
            self._file_count += 1
        self._file.writeframes(data.pcm)

    def cleanup(self):
        super().cleanup()
        try:
            self._file.close()
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
        vc.listen(RotatingWaveSink(self.bot))

    @commands.hybrid_command(aliases=['dc'])
    async def disconnect(self, ctx: GuildContext):
        if not ctx.voice_client:
            return await ctx.send("I'm not recording anything in any VCs at the moment.")

        await ctx.voice_client.disconnect(force=False)
        # transcript = await self.bot.loop.run_in_executor(None, transcribe, '0_audio.wav', 'medium.en')
        # await ctx.send(transcript)  # type: ignore

    @commands.hybrid_command()
    async def test(self, ctx: GuildContext):
        transcript = await self.bot.loop.run_in_executor(None, transcribe, '0_audio.wav', 'small.en')
        await ctx.send(transcript)  # type: ignore

    @commands.Cog.listener()
    async def on_transcript_complete(self, file: str):
        with open(file, 'rb') as file_:
           size = len(file_.read())
        transcript = await self.bot.loop.run_in_executor(None, transcribe, file, 'small.en')
        await self.bot.get_channel(1016137096316063844).send(f'Transcript of {file} produced:```{transcript}```')  # type: ignore
        with open(file, 'rb') as file_:
           size2 = len(file_.read())
           # print(size, size2, (size2-size)/size, f'diff = {size2-size}')

async def setup(bot: RoboDan):
    await bot.add_cog(STT(bot))
