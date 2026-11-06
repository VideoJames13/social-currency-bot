"""Economy data layer: members, currencies, balances, gifts, adjustments.

Pure SQLite, no Discord objects, so it can be tested directly. Every function
that records something takes `now` (an aware UTC datetime; db.now_utc() in
production) so tests can control time.
"""

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta

from .config import CONFIG
from .db import local_day, transaction

# Earnings sources that count as activity (soft cap, roundup). starting_grant does not.
ACTIVITY_SOURCES = ("message", "reply", "react_given", "react_received", "voice")


class EconomyError(Exception):
    """A rule was broken. The message is safe to show to the user."""


# ---------------------------------------------------------------- time helpers

def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def established_at(joined_at: datetime) -> datetime:
    return joined_at + timedelta(days=CONFIG.economy.min_account_age_days)


def is_established(joined_at: datetime | None, now: datetime) -> bool:
    """True once a member has been in the server long enough to earn and receive gifts."""
    return joined_at is not None and now >= established_at(joined_at)


# ------------------------------------------------------------- currency names

_NAME_RE = re.compile(r"^\w[\w '\-.!&+?]*$")
_CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([A-Za-z0-9_]{2,32}):(\d{15,25})>$")


def clean_name(name: str) -> str:
    return " ".join(name.split())


def currency_key(name: str) -> str:
    """Normalized form used for uniqueness: 'Ｂob-Bucks' and 'bob-bucks' collide."""
    return clean_name(unicodedata.normalize("NFKC", name).casefold())


def _key_taken(conn, key: str, user_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM members WHERE currency_key = ? AND user_id != ?", (key, user_id)
    ).fetchone() is not None


def _default_name(conn, user_id: int, display_name: str) -> str:
    base = clean_name(display_name) + CONFIG.economy.currency_suffix
    name, n = base, 1
    while _key_taken(conn, currency_key(name), user_id):
        n += 1
        name = f"{base} {n}"
    return name


def validate_currency_name(conn, user_id: int, raw: str) -> tuple[str, str]:
    name = clean_name(raw)
    max_len = CONFIG.economy.currency_name_max_length
    if not name:
        raise EconomyError("Your currency needs a name.")
    if len(name) > max_len:
        raise EconomyError(f"Currency names can be at most {max_len} characters.")
    if not _NAME_RE.match(name):
        raise EconomyError(
            "Currency names can only use letters, numbers, spaces and - ' . ! & + ?, "
            "and must start with a letter or number."
        )
    key = currency_key(name)
    if _key_taken(conn, key, user_id):
        raise EconomyError(f"**{name}** is already someone else's currency.")
    suffix = CONFIG.economy.currency_suffix
    for row in conn.execute(
        "SELECT display_name FROM members WHERE user_id != ? AND in_guild = 1", (user_id,)
    ):
        if currency_key(clean_name(row["display_name"]) + suffix) == key:
            raise EconomyError(f"**{name}** looks like another member's default currency.")
    return name, key


def _is_unicode_emoji(text: str) -> bool:
    if not text or len(text) > 16:
        return False
    has_symbol = False
    for ch in text:
        cp = ord(ch)
        if unicodedata.category(ch) == "So" or cp == 0x20E3:  # symbols, keycap
            has_symbol = True
        elif cp in (0x200D, 0xFE0E, 0xFE0F):                  # ZWJ, variation selectors
            continue
        elif 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F:  # skin tones, flag tags
            continue
        elif ch in "0123456789#*":                             # keycap bases
            continue
        else:
            return False
    return has_symbol


def validate_emoji(text: str, guild_emoji_ids: set[int]) -> str:
    """Accept a single standard emoji, or a custom emoji from this server."""
    text = text.strip()
    match = _CUSTOM_EMOJI_RE.match(text)
    if match:
        if int(match.group(3)) not in guild_emoji_ids:
            raise EconomyError("You can only use custom emoji from this server.")
        return text
    if _is_unicode_emoji(text):
        return text
    raise EconomyError("That doesn't look like a single emoji.")


def set_currency(conn, user_id: int, name: str | None = None, emoji: str | None = None) -> None:
    """`emoji` must already be validated with validate_emoji()."""
    try:
        with transaction(conn):
            if get_member(conn, user_id) is None:
                raise EconomyError("You're not registered yet. Try again in a minute.")
            if name is not None:
                name, key = validate_currency_name(conn, user_id, name)
                conn.execute(
                    "UPDATE members SET currency_name = ?, currency_key = ?, currency_custom = 1 "
                    "WHERE user_id = ?",
                    (name, key, user_id),
                )
            if emoji is not None:
                conn.execute(
                    "UPDATE members SET currency_emoji = ? WHERE user_id = ?", (emoji, user_id)
                )
    except sqlite3.IntegrityError:
        raise EconomyError("That name was just taken by someone else.") from None


# ------------------------------------------------------------------- members

def get_member(conn, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM members WHERE user_id = ?", (user_id,)).fetchone()


def upsert_member(conn, user_id: int, display_name: str, joined_at: datetime | None,
                  now: datetime) -> None:
    """Insert or refresh a member. Default currency names follow display-name changes."""
    joined = joined_at.isoformat() if joined_at else None
    row = conn.execute(
        "SELECT display_name, currency_name, currency_custom FROM members WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        name = _default_name(conn, user_id, display_name)
        conn.execute(
            "INSERT INTO members (user_id, display_name, joined_at, currency_name, currency_key,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, display_name, joined, name, currency_key(name), now.isoformat()),
        )
        return
    conn.execute(
        "UPDATE members SET display_name = ?, joined_at = ?, in_guild = 1 WHERE user_id = ?",
        (display_name, joined, user_id),
    )
    if not row["currency_custom"] and (
        row["currency_name"] is None or row["display_name"] != display_name
    ):
        name = _default_name(conn, user_id, display_name)
        conn.execute(
            "UPDATE members SET currency_name = ?, currency_key = ? WHERE user_id = ?",
            (name, currency_key(name), user_id),
        )


def sync_members(conn, members, now: datetime) -> None:
    """`members`: iterable of (user_id, display_name, joined_at) for every human in the server."""
    with transaction(conn):
        conn.execute("UPDATE members SET in_guild = 0")
        for user_id, display_name, joined_at in members:
            upsert_member(conn, user_id, display_name, joined_at, now)


def mark_left(conn, user_id: int) -> None:
    conn.execute("UPDATE members SET in_guild = 0 WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------ starting grants

def _launch_time(conn, now: datetime) -> datetime:
    row = conn.execute("SELECT value FROM bot_state WHERE key = 'launched_at'").fetchone()
    if row:
        return parse_ts(row["value"])
    conn.execute("INSERT INTO bot_state (key, value) VALUES ('launched_at', ?)", (now.isoformat(),))
    return now


def _log_earning(conn, user_id, source, base_amount, amount, now, *,
                 counterpart_id=None, message_id=None, detail=None):
    conn.execute(
        "INSERT INTO earnings (user_id, source, base_amount, amount, counterpart_id, message_id,"
        " detail, created_at, day) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, source, base_amount, amount, counterpart_id, message_id, detail,
         now.isoformat(), local_day(now)),
    )


def grant_starting_balances(conn, now: datetime) -> list[int]:
    """Give the starting balance to members who were here at launch, or who have
    since passed the new-account rule. Safe to call any time; each member is paid once."""
    amount = CONFIG.economy.starting_balance
    granted = []
    with transaction(conn):
        launched = _launch_time(conn, now)
        rows = conn.execute(
            "SELECT user_id, joined_at FROM members WHERE in_guild = 1 AND starting_granted = 0"
        ).fetchall()
        for row in rows:
            joined = parse_ts(row["joined_at"])
            if joined is None:
                continue
            if joined <= launched or is_established(joined, now):
                conn.execute(
                    "UPDATE members SET mint = mint + ?, starting_granted = 1 WHERE user_id = ?",
                    (amount, row["user_id"]),
                )
                _log_earning(conn, row["user_id"], "starting_grant", amount, amount, now)
                granted.append(row["user_id"])
    return granted


# ------------------------------------------------------------------- earning

def can_earn(member: sqlite3.Row | None, now: datetime) -> bool:
    return (member is not None and bool(member["in_guild"])
            and is_established(parse_ts(member["joined_at"]), now))


def credit(conn, member: sqlite3.Row, source: str, base: float, now: datetime, *,
           counterpart_id=None, message_id=None, detail: dict | None = None) -> int:
    """Pay an activity earning: apply the daily soft cap, carry fractions, update the
    mint and log it. Call inside a transaction. Returns the whole bucks credited."""
    threshold = CONFIG.soft_cap.daily_threshold
    earned = earned_today(conn, member["user_id"], now)
    full = max(0.0, min(base, threshold - earned))
    value = full + (base - full) * CONFIG.soft_cap.rate_after
    total = round(value + member["earn_carry"], 6)  # round away float noise before flooring
    amount = int(total)
    conn.execute(
        "UPDATE members SET mint = mint + ?, earn_carry = ? WHERE user_id = ?",
        (amount, total - amount, member["user_id"]),
    )
    detail = dict(detail or {})
    if full < base:
        detail["soft_capped"] = round(base - full, 6)
    _log_earning(conn, member["user_id"], source, base, amount, now,
                 counterpart_id=counterpart_id, message_id=message_id,
                 detail=json.dumps(detail) if detail else None)
    return amount


_CUSTOM_EMOJI_ANY = re.compile(r"<a?:\w+:\d+>")
_MENTION_ANY = re.compile(r"<(?:@[!&]?|#)\d+>")


def visible_length(content: str) -> int:
    """Characters a person actually typed: custom emoji and mentions count as one,
    runs of whitespace as one."""
    text = _CUSTOM_EMOJI_ANY.sub("x", content)
    text = _MENTION_ANY.sub("x", text)
    return len(" ".join(text.split()))


def earn_chat(conn, user_id: int, now: datetime, *, message_id: int | None = None,
              reply_to: int | None = None) -> int | None:
    """Pay for a qualifying message (caller checks length and that `reply_to`, if given,
    is another human). Returns bucks credited, or None if not eligible / on cooldown."""
    cooldown = timedelta(seconds=CONFIG.chat.cooldown_seconds)
    with transaction(conn):
        member = get_member(conn, user_id)
        if not can_earn(member, now):
            return None
        last = conn.execute(
            "SELECT created_at FROM earnings WHERE user_id = ? AND source IN ('message', 'reply')"
            " ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if last and now - parse_ts(last["created_at"]) < cooldown:
            return None
        if reply_to is not None:
            source, base = "reply", CONFIG.chat.reply_reward
        else:
            source, base = "message", CONFIG.chat.message_reward
        return credit(conn, member, source, base, now,
                      counterpart_id=reply_to, message_id=message_id)


# --------------------------------------------------------------------- gifts

def give(conn, giver_id: int, recipient_id: int, amount: int, reason: str | None,
         now: datetime) -> int:
    """Move `amount` from giver's mint to recipient's trophy case. Returns giver's new mint."""
    if giver_id == recipient_id:
        raise EconomyError("You can't give bucks to yourself.")
    if amount <= 0:
        raise EconomyError("Amount must be positive.")
    with transaction(conn):
        giver = get_member(conn, giver_id)
        recipient = get_member(conn, recipient_id)
        if giver is None:
            raise EconomyError("You're not registered yet. Try again in a minute.")
        if recipient is None or not recipient["in_guild"]:
            raise EconomyError("That person isn't a member here.")
        joined = parse_ts(recipient["joined_at"])
        if not is_established(joined, now):
            when = f" They can receive gifts <t:{int(established_at(joined).timestamp())}:R>." \
                if joined else ""
            raise EconomyError(
                f"**{recipient['display_name']}** is too new to receive gifts.{when}"
            )
        if giver["mint"] < amount:
            raise EconomyError(f"You only have **{giver['mint']:,}** in your mint.")
        conn.execute("UPDATE members SET mint = mint - ? WHERE user_id = ?", (amount, giver_id))
        conn.execute(
            "INSERT INTO holdings (holder_id, currency_owner_id, amount) VALUES (?, ?, ?)"
            " ON CONFLICT (holder_id, currency_owner_id) DO UPDATE SET amount = amount + excluded.amount",
            (recipient_id, giver_id, amount),
        )
        conn.execute(
            "INSERT INTO gifts (giver_id, recipient_id, amount, reason, created_at, day)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (giver_id, recipient_id, amount, reason, now.isoformat(), local_day(now)),
        )
        return giver["mint"] - amount


# --------------------------------------------------------------- adjustments

def adjust(conn, admin_id: int, target_id: int, amount: int, reason: str | None, now: datetime,
           currency_owner_id: int | None = None) -> int:
    """Owner fix-up. Changes target's mint, or (if currency_owner_id is given) how much of
    that member's currency target holds. Returns the new balance."""
    if amount == 0:
        raise EconomyError("Amount can't be zero.")
    with transaction(conn):
        target = get_member(conn, target_id)
        if target is None:
            raise EconomyError("That person isn't registered.")
        if currency_owner_id is None:
            new = target["mint"] + amount
            if new < 0:
                raise EconomyError(f"Their mint is only {target['mint']:,}; it can't go below zero.")
            conn.execute("UPDATE members SET mint = ? WHERE user_id = ?", (new, target_id))
        else:
            if get_member(conn, currency_owner_id) is None:
                raise EconomyError("That currency's owner isn't registered.")
            row = conn.execute(
                "SELECT amount FROM holdings WHERE holder_id = ? AND currency_owner_id = ?",
                (target_id, currency_owner_id),
            ).fetchone()
            current = row["amount"] if row else 0
            new = current + amount
            if new < 0:
                raise EconomyError(f"They only hold {current:,} of that currency.")
            conn.execute(
                "INSERT INTO holdings (holder_id, currency_owner_id, amount) VALUES (?, ?, ?)"
                " ON CONFLICT (holder_id, currency_owner_id) DO UPDATE SET amount = excluded.amount",
                (target_id, currency_owner_id, new),
            )
        conn.execute(
            "INSERT INTO adjustments (admin_id, target_id, amount, reason, created_at,"
            " currency_owner_id) VALUES (?, ?, ?, ?, ?, ?)",
            (admin_id, target_id, amount, reason, now.isoformat(), currency_owner_id),
        )
        return new


# ------------------------------------------------------------------- queries

def earned_today(conn, user_id: int, now: datetime) -> int:
    placeholders = ",".join("?" * len(ACTIVITY_SOURCES))
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM earnings WHERE user_id = ? AND day = ?"
        f" AND source IN ({placeholders})",
        (user_id, local_day(now), *ACTIVITY_SOURCES),
    ).fetchone()
    return row[0]


def trophies(conn, holder_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT h.amount, m.user_id AS owner_id, m.display_name AS owner_name,"
        " m.currency_name, m.currency_emoji"
        " FROM holdings h JOIN members m ON m.user_id = h.currency_owner_id"
        " WHERE h.holder_id = ? AND h.amount > 0 ORDER BY h.amount DESC",
        (holder_id,),
    ).fetchall()


def leaderboard(conn) -> list[dict]:
    """For each current member's currency, who holds the most of it (ties all listed)."""
    rows = conn.execute(
        "SELECT h.currency_owner_id, h.amount, holder.display_name AS holder_name,"
        " owner.currency_name, owner.currency_emoji"
        " FROM holdings h"
        " JOIN members holder ON holder.user_id = h.holder_id AND holder.in_guild = 1"
        " JOIN members owner ON owner.user_id = h.currency_owner_id AND owner.in_guild = 1"
        " WHERE h.amount > 0"
        " ORDER BY h.currency_owner_id, h.amount DESC, holder.display_name"
    ).fetchall()
    boards: dict[int, dict] = {}
    for row in rows:
        entry = boards.get(row["currency_owner_id"])
        if entry is None:
            boards[row["currency_owner_id"]] = {
                "currency_name": row["currency_name"],
                "currency_emoji": row["currency_emoji"],
                "amount": row["amount"],
                "holders": [row["holder_name"]],
            }
        elif row["amount"] == entry["amount"]:
            entry["holders"].append(row["holder_name"])
    return sorted(boards.values(), key=lambda e: (-e["amount"], e["currency_name"].casefold()))


def hoarders(conn, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT user_id, display_name, mint, currency_name, currency_emoji FROM members"
        " WHERE in_guild = 1 AND mint > 0 ORDER BY mint DESC, display_name LIMIT ?",
        (limit,),
    ).fetchall()
