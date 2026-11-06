"""Speaking detection WITHOUT listening to audio.

Discord voice packets are RTP: a 12-byte header (unencrypted, includes the sender's
SSRC number) followed by an encrypted payload (transport + DAVE end-to-end encryption).
Clients only send packets while someone is talking, so "packets are arriving from
SSRC X" means "X is talking". The voice server tells us which SSRC belongs to which
user (voice gateway op 5, SPEAKING).

We read ONLY the header's SSRC and note the time. The payload is never decrypted,
decoded, buffered or saved, and these timestamps live in memory only.

Relies on two semi-internal discord.py hooks (VoiceConnectionState(hook=...) and
add_socket_listener), so discord.py is pinned. Re-test voice before upgrading it.
"""

import logging
import threading
from datetime import datetime, timezone

import discord
from discord.voice_state import VoiceConnectionState

log = logging.getLogger("bucks")

OP_SPEAKING = 5
OP_CLIENT_DISCONNECT = 13
RTP_VERSION = 2
OPUS_PAYLOAD_TYPE = 120


def rtp_ssrc(packet: bytes) -> int | None:
    """SSRC of an RTP audio packet, or None for anything else (RTCP, IP discovery...)."""
    if len(packet) < 12 or packet[0] >> 6 != RTP_VERSION:
        return None
    if packet[1] & 0x7F != OPUS_PAYLOAD_TYPE:
        return None
    return int.from_bytes(packet[8:12], "big")


class SpeakingVoiceClient(discord.VoiceClient):
    """A voice client that records *when* each user last transmitted, nothing more."""

    def __init__(self, client, channel):
        self._lock = threading.Lock()   # packets arrive on discord.py's socket thread
        self._ssrc_user: dict[int, int] = {}
        self._last_spoke: dict[int, datetime] = {}
        super().__init__(client, channel)

    def create_connection_state(self) -> VoiceConnectionState:
        return VoiceConnectionState(self, hook=self._on_ws_message)

    async def connect(self, *, reconnect: bool, timeout: float, self_deaf: bool = False,
                      self_mute: bool = False) -> None:
        await super().connect(reconnect=reconnect, timeout=timeout,
                              self_deaf=self_deaf, self_mute=self_mute)
        self._connection.add_socket_listener(self._on_packet)

    def _mark(self, user_id: int) -> None:
        self._last_spoke[user_id] = datetime.now(timezone.utc)

    async def _on_ws_message(self, ws, msg: dict) -> None:
        op, data = msg.get("op"), msg.get("d") or {}
        try:
            if op == OP_SPEAKING and "user_id" in data:
                user_id, ssrc = int(data["user_id"]), int(data["ssrc"])
                with self._lock:
                    self._ssrc_user[ssrc] = user_id
                    if int(data.get("speaking", 0)) & 1:  # microphone flag
                        self._mark(user_id)
            elif op == OP_CLIENT_DISCONNECT and "user_id" in data:
                user_id = int(data["user_id"])
                with self._lock:
                    for ssrc in [s for s, u in self._ssrc_user.items() if u == user_id]:
                        del self._ssrc_user[ssrc]
        except (KeyError, TypeError, ValueError):
            log.debug("Unexpected voice gateway payload: op %s", op)

    def _on_packet(self, packet: bytes) -> None:
        ssrc = rtp_ssrc(packet)
        if ssrc is None:
            return
        with self._lock:
            user_id = self._ssrc_user.get(ssrc)
            if user_id is not None:
                self._mark(user_id)

    def last_spoke(self) -> dict[int, datetime]:
        """Snapshot of {user_id: last time they transmitted}."""
        with self._lock:
            return dict(self._last_spoke)
