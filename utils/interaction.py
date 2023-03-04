import discord

from main import Bot


class Interaction(discord.Interaction):
    client: Bot
