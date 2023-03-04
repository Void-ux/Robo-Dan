import discord


def error_embed(message: str, /, *, timestamp: bool = False) -> discord.Embed:
    return discord.Embed(
        colour=0xFF872B,
        description=message,
        timestamp=discord.utils.utcnow() if timestamp else None
    )


def affirmation_embed(message: str, /, *, timestamp: bool = False) -> discord.Embed:
    return discord.Embed(
        colour=0x8BC34A,
        description=message,
        timestamp=discord.utils.utcnow() if timestamp else None
    )
