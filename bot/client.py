"""The bot client: intents, startup, command sync."""

import logging

import discord
from discord.ext import commands

from . import db
from .config import CONFIG

log = logging.getLogger("bucks")

EXTENSIONS = [
    "bot.cogs.core",
    "bot.cogs.members",
    "bot.cogs.currency",
    "bot.cogs.admin",
    "bot.cogs.chat",
    "bot.cogs.reactions",
    "bot.cogs.roundup",
    "bot.cogs.voice",
]


def make_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True            # privileged: Server Members Intent
    intents.message_content = True    # privileged: Message Content Intent
    intents.guild_messages = True
    intents.guild_reactions = True
    intents.voice_states = True
    intents.emojis_and_stickers = True  # /setcurrency checks custom emoji belong to this server
    return intents


class BucksBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=make_intents())
        self.guild_obj = discord.Object(id=CONFIG.server.guild_id)
        self.db = db.connect()

    async def setup_hook(self):
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        # Guild-scoped sync makes commands appear instantly (global sync can take an hour).
        self.tree.copy_global_to(guild=self.guild_obj)
        synced = await self.tree.sync(guild=self.guild_obj)
        log.info("Synced %d slash commands: %s", len(synced), ", ".join(c.name for c in synced))

    async def on_ready(self):
        log.info("Logged in as %s (id %s)", self.user, self.user.id)
        guild = self.get_guild(CONFIG.server.guild_id)
        if guild is None:
            log.error("Bot is not in guild %s. Check guild_id in config.toml and the invite.",
                      CONFIG.server.guild_id)
            return
        channel = guild.get_channel(CONFIG.server.transactions_channel_id)
        if channel is None:
            log.error("Transactions channel %s not found.", CONFIG.server.transactions_channel_id)
        else:
            log.info("Transactions channel: #%s", channel.name)
