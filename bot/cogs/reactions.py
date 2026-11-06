"""Reaction earning: reacting to others' posts, and receiving reactions."""

import logging

import discord
from discord.ext import commands

from .. import economy
from ..config import CONFIG
from ..db import now_utc

log = logging.getLogger("bucks")


class Reactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _author_of(self, payload: discord.RawReactionActionEvent) -> int | None:
        if payload.message_author_id is not None:
            return payload.message_author_id
        # Older/odd payloads may omit the author; fetch the message as a fallback.
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return None
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return None
        return message.author.id

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Raw event: works on messages sent before the bot started, too.
        if payload.guild_id != CONFIG.server.guild_id:
            return
        if payload.member is None or payload.member.bot:
            return
        author_id = await self._author_of(payload)
        if author_id is None or author_id == payload.user_id:
            return
        # Bot/webhook authors aren't in the members table, so they earn and pay nothing.
        given, received = economy.earn_reaction(
            self.bot.db, payload.user_id, author_id, payload.message_id, payload.channel_id,
            now_utc())
        if given is not None or received is not None:
            log.debug("reaction %s -> %s on %s: reactor %s, author %s", payload.user_id,
                      author_id, payload.message_id, given, received)

    # Removing a reaction intentionally does nothing: no refund, no re-earn on re-add.


async def setup(bot):
    await bot.add_cog(Reactions(bot))
