import discord

from bot import Bot


class Interaction(discord.Interaction):
    client: Bot
