"""Voice earning: a 1-minute loop that snapshots voice channels and pays out.

Speaking check: the bot sits (self-muted) in the most populated voice channel and
notes who is transmitting (see bot/listener.py). It never hears audio.
"""

import asyncio
import logging
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from .. import economy
from ..config import CONFIG
from ..db import now_utc
from ..listener import SpeakingVoiceClient
from ..voice import VoiceChannel, VoiceMember

log = logging.getLogger("bucks")

JOIN_RETRY = timedelta(minutes=5)


def snapshot_member(m: discord.Member) -> VoiceMember:
    vs = m.voice
    return VoiceMember(
        user_id=m.id,
        deaf=bool(vs.self_deaf or vs.deaf),
        muted=bool(vs.self_mute or vs.mute or vs.suppress),
        video=bool(vs.self_video),
        stream=bool(vs.self_stream),
    )


def human_count(ch) -> int:
    return sum(1 for m in ch.members if not m.bot)


def can_join(ch, me: discord.Member) -> bool:
    perms = ch.permissions_for(me)
    if not (perms.view_channel and perms.connect):
        return False
    full = ch.user_limit and len(ch.members) >= ch.user_limit
    return not full or perms.move_members


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.listening_since = None      # when the bot entered its current channel
        self.listening_channel_id = None
        self.retry_after = None          # back off after a failed join
        self.voice_loop.change_interval(seconds=CONFIG.voice.loop_seconds)

    async def cog_load(self):
        self.voice_loop.start()

    async def cog_unload(self):
        self.voice_loop.cancel()
        vc = self.voice_client()
        if vc:
            await vc.disconnect(force=True)

    @property
    def guild(self) -> discord.Guild | None:
        return self.bot.get_guild(CONFIG.server.guild_id)

    def voice_client(self) -> SpeakingVoiceClient | None:
        guild = self.guild
        vc = guild.voice_client if guild else None
        return vc if isinstance(vc, SpeakingVoiceClient) else None

    # --------------------------------------------------------------- snapshot
    def build_snapshot(self, guild: discord.Guild) -> list[VoiceChannel]:
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        vc = self.voice_client()
        listening_id = vc.channel.id if vc and vc.is_connected() else None
        channels = []
        for ch in [*guild.voice_channels, *guild.stage_channels]:
            humans = [snapshot_member(m) for m in ch.members if not m.bot and m.voice]
            if not humans:
                continue
            snap = VoiceChannel(channel_id=ch.id, members=humans, afk=ch.id == afk_id)
            if ch.id == listening_id and ch.id == self.listening_channel_id:
                snap.listening_since = self.listening_since
                snap.last_spoke = vc.last_spoke()
            channels.append(snap)
        return channels

    # ---------------------------------------------------------- channel choice
    def pick_channel(self, guild: discord.Guild):
        """Most populated joinable non-AFK channel; stay put on ties."""
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        vc = self.voice_client()
        current = vc.channel if vc and vc.is_connected() else None
        options = [ch for ch in [*guild.voice_channels, *guild.stage_channels]
                   if ch.id != afk_id and human_count(ch) > 0
                   and (ch == current or can_join(ch, guild.me))]
        if not options:
            return None
        best = max(options, key=human_count)
        if current in options and human_count(current) >= human_count(best):
            return current
        return best

    async def follow_crowd(self, guild: discord.Guild):
        vc = self.voice_client()
        target = self.pick_channel(guild) if CONFIG.speaking.enabled else None
        if target is None:
            if vc:
                await vc.disconnect(force=True)
                self.listening_since = self.listening_channel_id = None
                log.info("Left voice (nobody to listen to)")
            return
        if vc and vc.is_connected() and vc.channel == target:
            if self.listening_channel_id != target.id:  # someone dragged the bot here
                self.listening_since, self.listening_channel_id = now_utc(), target.id
            return
        now = now_utc()
        if self.retry_after and now < self.retry_after:
            return
        try:
            if vc and vc.is_connected():
                await vc.move_to(target)
            else:
                if vc:
                    await vc.disconnect(force=True)
                await target.connect(cls=SpeakingVoiceClient, self_mute=True, self_deaf=False,
                                     timeout=30, reconnect=True)
            self.listening_since, self.listening_channel_id = now_utc(), target.id
            self.retry_after = None
            log.info("Listening for speaking in #%s", target.name)
        except (asyncio.TimeoutError, discord.ClientException, discord.HTTPException,
                RuntimeError) as e:
            self.listening_since = self.listening_channel_id = None
            self.retry_after = now + JOIN_RETRY
            log.warning("Couldn't join #%s for the speaking check (%s); retrying in %s. "
                        "Voice earning there uses the unmuted rule meanwhile.",
                        target.name, e, JOIN_RETRY)

    # -------------------------------------------------------------------- loop
    @tasks.loop(seconds=60)
    async def voice_loop(self):
        guild = self.guild
        if guild is None:
            return
        # Pay for the minute that just passed, then reposition for the next one.
        # Errors are logged and the loop carries on next minute.
        try:
            paid = economy.voice_tick(self.bot.db, self.build_snapshot(guild), now_utc())
            if paid:
                log.debug("voice tick: %s", paid)
        except Exception:
            log.exception("Voice tick failed")
        try:
            await self.follow_crowd(guild)
        except Exception:
            log.exception("Voice channel management failed")

    @voice_loop.before_loop
    async def _before(self):
        # Voice states come from Discord on connect, so sessions rebuild from a fresh snapshot.
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Voice(bot))
