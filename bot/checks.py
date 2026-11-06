"""Shared permission checks for slash commands."""

import discord
from discord import app_commands

from .config import OWNER_ID


def is_owner_user(user: discord.abc.User) -> bool:
    return OWNER_ID is not None and user.id == OWNER_ID


def owner_only():
    """Reject anyone except OWNER_ID from .env, regardless of server permissions."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if is_owner_user(interaction.user):
            return True
        raise app_commands.CheckFailure("owner_only")

    return app_commands.check(predicate)
