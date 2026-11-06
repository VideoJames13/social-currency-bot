"""Voice earning: a 1-minute loop that snapshots voice channels and pays out."""

import logging

import discord
from discord.ext import commands, tasks

from .. import economy
from ..config import CONFIG
from ..db import now_utc
from ..voice import VoiceChannel, VoiceMember

log = logging.getLogger("bucks")


def snapshot_member(m: discord.Member) -> VoiceMember:
    vs = m.voice
    return VoiceMember(
        user_id=m.id,
        deaf=bool(vs.self_deaf or vs.deaf),
        muted=bool(vs.self_mute or vs.mute or vs.suppress),
        video=bool(vs.self_video),
        stream=bool(vs.self_stream),
    )


def snapshot_guild(guild: discord.Guild) -> list[VoiceChannel]:
    afk_id = guild.afk_channel.id if guild.afk_channel else None
    channels = []
    for ch in [*guild.voice_channels, *guild.stage_channels]:
        humans = [snapshot_member(m) for m in ch.members if not m.bot and m.voice]
        if humans:
            channels.append(VoiceChannel(channel_id=ch.id, members=humans, afk=ch.id == afk_id))
    return channels


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_loop.change_interval(seconds=CONFIG.voice.loop_seconds)

    async def cog_load(self):
        self.voice_loop.start()

    async def cog_unload(self):
        self.voice_loop.cancel()

    def build_snapshot(self) -> list[VoiceChannel] | None:
        guild = self.bot.get_guild(CONFIG.server.guild_id)
        return snapshot_guild(guild) if guild else None

    @tasks.loop(seconds=60)
    async def voice_loop(self):
        channels = self.build_snapshot()
        if channels is None:
            return
        paid = economy.voice_tick(self.bot.db, channels, now_utc())
        if paid:
            log.debug("voice tick: %s", paid)

    @voice_loop.before_loop
    async def _before(self):
        # Voice states come from Discord on connect, so sessions rebuild from a fresh snapshot.
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Voice(bot))
