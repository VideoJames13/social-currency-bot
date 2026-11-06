"""The bot client: intents, startup, command sync, member sync."""

import logging

import discord
from discord.ext import commands

from . import db
from .config import CONFIG

log = logging.getLogger("bucks")

EXTENSIONS = [
    "bot.cogs.core",
]


def make_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True            # privileged: Server Members Intent
    intents.message_content = True    # privileged: Message Content Intent
    intents.guild_messages = True
    intents.guild_reactions = True
    intents.voice_states = True
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
            log.error("Bot is not in guild %s — check guild_id in config.toml and the invite.",
                      CONFIG.server.guild_id)
            return
        self.sync_members(guild)
        channel = guild.get_channel(CONFIG.server.transactions_channel_id)
        if channel is None:
            log.error("Transactions channel %s not found.", CONFIG.server.transactions_channel_id)
        else:
            log.info("Transactions channel: #%s", channel.name)

    async def on_member_join(self, member: discord.Member):
        if member.guild.id == CONFIG.server.guild_id and not member.bot:
            self.upsert_member(member)

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id == CONFIG.server.guild_id and not after.bot and \
                before.display_name != after.display_name:
            self.upsert_member(after)

    def sync_members(self, guild: discord.Guild):
        humans = [m for m in guild.members if not m.bot]
        with db.transaction(self.db):
            for m in humans:
                self.upsert_member(m)
        log.info("Synced %d members", len(humans))

    def upsert_member(self, member: discord.Member):
        self.db.execute(
            """
            INSERT INTO members (user_id, display_name, joined_at, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                display_name = excluded.display_name,
                joined_at = excluded.joined_at
            """,
            (
                member.id,
                member.display_name,
                member.joined_at.isoformat() if member.joined_at else None,
                db.now_utc().isoformat(),
            ),
        )
