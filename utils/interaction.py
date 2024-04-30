import discord

from bot import RoboDan


class Interaction(discord.Interaction):
    client: RoboDan
