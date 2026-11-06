"""The bot client: intents, startup, command sync."""

import logging

import discord
from discord.ext import commands

from . import db
from .config import CONFIG, OWNER_ID
from .safety import PostGuard

log = logging.getLogger("bucks")


class PostingPaused(Exception):
    """The posting circuit breaker is open; the message was not sent."""

EXTENSIONS = [
    "bot.cogs.core",
    "bot.cogs.members",
    "bot.cogs.currency",
    "bot.cogs.admin",
    "bot.cogs.chat",
    "bot.cogs.reactions",
    "bot.cogs.roundup",
    "bot.cogs.voice",
    "bot.cogs.health",
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
        self.post_guard = PostGuard(CONFIG.safety.max_posts_per_hour)
        self._owner_warned = False

    async def post(self, channel: discord.abc.Messageable, *args, **kwargs) -> discord.Message:
        """Send a channel message through the circuit breaker. ALL bot posts to channels
        must use this. Raises PostingPaused if the hourly limit has been hit."""
        now = db.now_utc()
        if not self.post_guard.allow(now):
            if not self._owner_warned:
                self._owner_warned = True
                log.error("Posting circuit breaker tripped: over %d posts in an hour. "
                          "Pausing posts until %s.", self.post_guard.limit,
                          self.post_guard.resumes_at())
                await self._dm_owner(
                    f"⚠️ I tried to post more than {self.post_guard.limit} messages in an hour, "
                    "so I've paused posting in case something's wrong. Gifts still work; their "
                    f"announcements are skipped. Posting resumes "
                    f"<t:{int(self.post_guard.resumes_at().timestamp())}:R>. Check the logs.")
            raise PostingPaused()
        if self._owner_warned:
            self._owner_warned = False
            log.warning("Posting circuit breaker closed; posting resumed.")
        return await channel.send(*args, **kwargs)

    async def _dm_owner(self, text: str) -> None:
        if OWNER_ID is None:
            return
        try:
            owner = self.get_user(OWNER_ID) or await self.fetch_user(OWNER_ID)
            await owner.send(text)
        except discord.HTTPException:
            log.exception("Couldn't DM the owner")

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
