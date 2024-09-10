from __future__ import annotations
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot import RoboDan


class Interaction(discord.Interaction):
    client: RoboDan
