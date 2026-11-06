"""Keeps the members table in step with the server and pays starting balances."""

import logging

import discord
from discord.ext import commands, tasks

from .. import economy
from ..config import CONFIG
from ..db import now_utc

log = logging.getLogger("bucks")


def _ours(member: discord.Member) -> bool:
    return member.guild.id == CONFIG.server.guild_id and not member.bot


class Members(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.grant_loop.start()

    async def cog_unload(self):
        self.grant_loop.cancel()

    def _upsert(self, member: discord.Member):
        economy.upsert_member(self.bot.db, member.id, member.display_name, member.joined_at,
                              now_utc())

    def _grant(self):
        granted = economy.grant_starting_balances(self.bot.db, now_utc())
        if granted:
            log.info("Paid starting balance to %d member(s)", len(granted))

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(CONFIG.server.guild_id)
        if guild is None:
            return  # client.on_ready logs this
        humans = [(m.id, m.display_name, m.joined_at) for m in guild.members if not m.bot]
        economy.sync_members(self.bot.db, humans, now_utc())
        log.info("Synced %d members", len(humans))
        self._grant()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if _ours(member):
            self._upsert(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if _ours(member):
            economy.mark_left(self.bot.db, member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if _ours(after) and before.display_name != after.display_name:
            self._upsert(after)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        # Global display-name changes arrive here, not in on_member_update.
        guild = self.bot.get_guild(CONFIG.server.guild_id)
        member = guild and guild.get_member(after.id)
        if member and _ours(member):
            self._upsert(member)

    @tasks.loop(minutes=30)
    async def grant_loop(self):
        self._grant()

    @grant_loop.before_loop
    async def _before_grant_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Members(bot))
