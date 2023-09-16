import datetime
import functools
import time
from io import BytesIO
from typing import Any, Annotated

import discord
from discord.ext import commands
from PIL import Image, ImageFont, ImageDraw

from bot import Bot
from utils.context import Context


def overlay_text(
        img: Any,
        text: str,
        _format: str = 'jpeg',
        font_size: int = 140,
        coordinates: tuple[int, int] = (0, 0),
        colour: tuple[int, int, int] = (0, 0, 0)
) -> BytesIO:
    font = ImageFont.truetype('arial.ttf', font_size)
    draw = ImageDraw.Draw(img)
    draw.text(coordinates, text, fill=colour, font=font)

    buffer = BytesIO()
    img.save(buffer, _format)
    buffer.seek(0)

    return buffer


class Art(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.hybrid_command()
    async def overlay(
            self,
            ctx: Context,
            x: int,
            y: int,
            *,
            text: str,
            attachment: Annotated[discord.Attachment | discord.Asset | None, discord.Attachment | None] = None
    ):
        if not ctx.interaction:
            if ctx.message.attachments:
                attachment = ctx.message.attachments[0]
            else:
                attachment = ctx.author.display_avatar
        else:
            attachment = attachment or ctx.author.display_avatar

        img_buffer = BytesIO(await attachment.read())
        img = Image.open(img_buffer)
        partial = functools.partial(overlay_text, img, text, _format='png', coordinates=(x, y))

        start = time.perf_counter()
        buffer = await self.bot.loop.run_in_executor(None, partial)
        dt = (time.perf_counter() - start) * 1000.0
        await ctx.send(
            f'*Rendered 1 image in {dt:.2f}ms*',
            file=discord.File(fp=buffer, filename=getattr(attachment, 'filename', 'render.png'))
        )


async def setup(bot: Bot):
    await bot.add_cog(Art(bot))
