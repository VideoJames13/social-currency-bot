"""SQLite storage. Schema changes go in MIGRATIONS (append only, never edit old ones).

Design notes:
- members.mint is a cached balance; every change to it is also written to a log
  table (earnings, gifts, adjustments) so balances can be audited or rebuilt.
- holdings is the trophy case: (holder, currency owner) -> amount received.
- earnings doubles as rate-limit state (daily caps are counted from it by `day`).
- Rewards shop later: add shop_items + purchases tables in a new migration;
  purchases debit mint or holdings and get logged the same way.
- Timestamps are UTC ISO-8601; `day` is the local (config timezone) date, YYYY-MM-DD.
"""

import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH, TZ

MIGRATIONS = [
    # 1: initial schema
    """
    CREATE TABLE members (
        user_id         INTEGER PRIMARY KEY,
        display_name    TEXT NOT NULL,
        joined_at       TEXT,               -- when they joined the server (UTC)
        currency_name   TEXT,               -- NULL = default "<DisplayName>-bucks"
        currency_emoji  TEXT,
        mint            INTEGER NOT NULL DEFAULT 0,
        starting_granted INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL
    );
    CREATE UNIQUE INDEX members_currency_name_unique
        ON members (lower(currency_name)) WHERE currency_name IS NOT NULL;

    CREATE TABLE holdings (
        holder_id         INTEGER NOT NULL REFERENCES members(user_id),
        currency_owner_id INTEGER NOT NULL REFERENCES members(user_id),
        amount            INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (holder_id, currency_owner_id)
    );
    CREATE INDEX holdings_by_currency ON holdings (currency_owner_id, amount DESC);

    CREATE TABLE gifts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        giver_id     INTEGER NOT NULL REFERENCES members(user_id),
        recipient_id INTEGER NOT NULL REFERENCES members(user_id),
        amount       INTEGER NOT NULL CHECK (amount > 0),
        reason       TEXT,
        created_at   TEXT NOT NULL,
        day          TEXT NOT NULL
    );

    -- source: message | reply | react_given | react_received | voice | starting_grant
    CREATE TABLE earnings (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL REFERENCES members(user_id),
        source        TEXT NOT NULL,
        base_amount   REAL NOT NULL,        -- before soft cap
        amount        INTEGER NOT NULL,     -- actually credited
        counterpart_id INTEGER,             -- other member involved (reactor/author)
        message_id    INTEGER,
        detail        TEXT,                 -- JSON: multipliers, flags, etc.
        created_at    TEXT NOT NULL,
        day           TEXT NOT NULL
    );
    CREATE INDEX earnings_user_day ON earnings (user_id, day, source);
    CREATE INDEX earnings_day ON earnings (day);

    CREATE TABLE adjustments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id   INTEGER NOT NULL,
        target_id  INTEGER NOT NULL REFERENCES members(user_id),
        amount     INTEGER NOT NULL,
        reason     TEXT,
        created_at TEXT NOT NULL
    );

    -- One row per (message, reactor) that has ever been credited, so
    -- removing and re-adding a reaction never pays again.
    CREATE TABLE reaction_credits (
        message_id INTEGER NOT NULL,
        reactor_id INTEGER NOT NULL,
        author_id  INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (message_id, reactor_id)
    );

    -- Messages we track (for reaction caps and "most-reacted post").
    CREATE TABLE messages (
        message_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        author_id  INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        day        TEXT NOT NULL
    );

    -- Live voice state; rebuilt from Discord on startup.
    CREATE TABLE voice_sessions (
        user_id        INTEGER PRIMARY KEY,
        channel_id     INTEGER NOT NULL,
        started_at     TEXT NOT NULL,
        last_spoke_at  TEXT
    );

    -- Small key/value store (pinned message IDs, last roundup date, ...).
    CREATE TABLE bot_state (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # 2: commands stage
    # - currency_key: normalized (NFKC + casefold) name, unique across the server.
    #   SQLite's lower() only folds ASCII, so uniqueness is enforced on this instead.
    # - currency_custom: 0 = default "<DisplayName>-bucks" that follows name changes.
    # - in_guild: 0 once a member leaves (kept for history, hidden from boards).
    # - adjustments.currency_owner_id: NULL = mint; else trophy-case holding of that currency.
    """
    ALTER TABLE members ADD COLUMN currency_key TEXT;
    ALTER TABLE members ADD COLUMN currency_custom INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE members ADD COLUMN in_guild INTEGER NOT NULL DEFAULT 1;
    DROP INDEX members_currency_name_unique;
    CREATE UNIQUE INDEX members_currency_key_unique
        ON members (currency_key) WHERE currency_key IS NOT NULL;
    ALTER TABLE adjustments ADD COLUMN currency_owner_id INTEGER;
    """,
    # 3: text earning
    # - earn_carry: fractional remainder of earnings (soft cap 25%, voice multipliers).
    #   Mints stay whole numbers; the fraction rolls into the next payout.
    """
    ALTER TABLE members ADD COLUMN earn_carry REAL NOT NULL DEFAULT 0;
    """,
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_day(dt: datetime | None = None) -> str:
    return (dt or now_utc()).astimezone(TZ).date().isoformat()


def connect(path=DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; use `with transaction(conn)`
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")


class transaction:
    """`with transaction(conn): ...` — commits on success, rolls back on error."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
