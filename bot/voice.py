"""Voice earning rules as pure functions over a snapshot of the server's voice channels.

The cog turns Discord voice states into these dataclasses once a minute;
economy.voice_tick() applies them and pays out.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import CONFIG


@dataclass(frozen=True)
class VoiceMember:
    user_id: int
    deaf: bool = False      # self- or server-deafened
    muted: bool = False     # self- or server-muted, or suppressed in a stage channel
    video: bool = False     # camera on
    stream: bool = False    # screen sharing (Go Live)


@dataclass
class VoiceChannel:
    channel_id: int
    members: list[VoiceMember]          # humans only
    afk: bool = False                   # the server's AFK channel
    # Set only for the channel the bot is sitting in (speaking check, stage 6).
    listening_since: datetime | None = None
    last_spoke: dict[int, datetime] = field(default_factory=dict)


def crowd_multiplier(people: int) -> float:
    v = CONFIG.voice
    if people < v.crowd_min_people:
        return 1.0
    return round(min(v.crowd_max, v.crowd_start + v.crowd_step * (people - v.crowd_min_people)), 4)


def duration_multiplier(earning_minutes: int) -> float:
    v = CONFIG.voice
    hours = earning_minutes // 60
    if hours < v.duration_start_hours:
        return 1.0
    return round(min(v.duration_max,
                     v.duration_start + v.duration_step * (hours - v.duration_start_hours)), 4)


def base_rate(m: VoiceMember) -> int:
    v = CONFIG.voice
    return v.base_per_minute + (v.camera_bonus if m.video else 0) + \
        (v.screenshare_bonus if m.stream else 0)


def counted(channel: VoiceChannel, established: set[int]) -> list[VoiceMember]:
    """People who count toward the crowd and the 'someone else is unmuted' rule:
    not deafened, and past the new-account rule (so alts can't pad a channel)."""
    return [m for m in channel.members if not m.deaf and m.user_id in established]


def activity_factor(m: VoiceMember, channel: VoiceChannel, established: set[int],
                    now: datetime) -> tuple[float, str]:
    """How much of the voice rate this member gets this minute, and why.

    Channel the bot is listening in (speaking check):
      - nobody else (counted) in the channel -> 0
      - member spoke within the window AND isn't muted right now -> full rate
        (muting drops you to the quiet rate at the next tick)
      - someone counted in the channel spoke within the window -> quiet_rate (50%)
      - nobody spoke within the window -> 0, except during the bot's first window
        in the channel (no data yet), when the unmuted-other rule applies instead.
    Any other channel: full rate if at least one OTHER counted person is unmuted, else 0.
    """
    people = counted(channel, established)
    others = [o for o in people if o.user_id != m.user_id]
    unmuted_rule = (1.0, "unmuted_other") if any(not o.muted for o in others) \
        else (0.0, "nobody_else_unmuted")

    if channel.listening_since is None:
        return unmuted_rule

    s = CONFIG.speaking
    window = timedelta(minutes=s.window_minutes)
    cutoff = now - window
    if not others:
        return 0.0, "alone"
    def recent(user_id: int) -> bool:
        t = channel.last_spoke.get(user_id)
        return t is not None and t >= cutoff

    if recent(m.user_id) and not m.muted:
        return 1.0, "spoke"
    if any(recent(o.user_id) for o in people):
        return s.quiet_rate, "quiet"
    if now - channel.listening_since < window:
        return unmuted_rule[0], "warming_up"
    return 0.0, "silent_channel"
