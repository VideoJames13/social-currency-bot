"""Run with: .venv/Scripts/python -m unittest discover tests"""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot import db, economy
from bot.config import CONFIG
from bot.economy import EconomyError

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
OLD = T0 - timedelta(days=100)   # long-time member
START = CONFIG.economy.starting_balance


class EconomyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, uid, name, joined=OLD, now=T0):
        with db.transaction(self.conn):
            economy.upsert_member(self.conn, uid, name, joined, now)

    def member(self, uid):
        return economy.get_member(self.conn, uid)

    def launch(self, now=T0):
        return economy.grant_starting_balances(self.conn, now)

    # ---------------------------------------------------------- migrations
    def test_upgrade_from_v1_database(self):
        path = Path(self.tmp.name) / "v1.db"
        raw = sqlite3.connect(path, isolation_level=None)
        raw.executescript(f"BEGIN;{db.MIGRATIONS[0]}PRAGMA user_version = 1;COMMIT;")
        raw.execute("INSERT INTO members (user_id, display_name, joined_at, created_at)"
                    " VALUES (1, 'Alice', ?, ?)", (OLD.isoformat(), T0.isoformat()))
        raw.close()
        conn = db.connect(path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))
        economy.sync_members(conn, [(1, "Alice", OLD)], T0)
        self.assertEqual(economy.get_member(conn, 1)["currency_name"], "Alice-bucks")
        conn.close()

    # ------------------------------------------------------ currency names
    def test_default_names_are_unique_and_follow_renames(self):
        self.add(1, "Bob")
        self.add(2, "bob")
        self.assertEqual(self.member(1)["currency_name"], "Bob-bucks")
        self.assertEqual(self.member(2)["currency_name"], "bob-bucks 2")
        self.add(1, "Robert")
        self.assertEqual(self.member(1)["currency_name"], "Robert-bucks")

    def test_custom_name_survives_rename(self):
        self.add(1, "Bob")
        economy.set_currency(self.conn, 1, name="Doubloons")
        self.add(1, "Robert")
        self.assertEqual(self.member(1)["currency_name"], "Doubloons")

    def test_custom_name_rules(self):
        self.add(1, "Alice")
        self.add(2, "Bob")
        economy.set_currency(self.conn, 1, name="  Gold   Coins ")
        self.assertEqual(self.member(1)["currency_name"], "Gold Coins")
        # "Alice-Bucks": Alice uses a custom name now, but her default is still reserved.
        for bad in ["gold coins", "ＧＯＬＤ coins", "Alice-Bucks", "x" * 21, "<@123>", "-dash", "a`b"]:
            with self.subTest(bad=bad), self.assertRaises(EconomyError):
                economy.set_currency(self.conn, 2, name=bad)
        economy.set_currency(self.conn, 2, name="Gold Coins II")  # similar but distinct is fine
        economy.set_currency(self.conn, 1, name="gold coins")     # re-casing your own is fine

    def test_emoji_validation(self):
        guild_ids = {123456789012345678}
        for ok in ["🍕", "👍🏽", "👨‍👩‍👧", "🇺🇸", "1️⃣", "❤️", "<:pizza:123456789012345678>",
                   "<a:spin:123456789012345678>"]:
            with self.subTest(ok=ok):
                self.assertEqual(economy.validate_emoji(ok, guild_ids), ok)
        for bad in ["abc", "🍕 pizza", "<:other:999999999999999999>", "@everyone", "1", ""]:
            with self.subTest(bad=bad), self.assertRaises(EconomyError):
                economy.validate_emoji(bad, guild_ids)

    # --------------------------------------------------- starting balances
    def test_launch_members_paid_once_and_newcomers_after_seven_days(self):
        self.add(1, "Old")
        self.add(2, "Recent", joined=T0 - timedelta(days=2))   # here at launch, still new
        self.assertEqual(sorted(self.launch()), [1, 2])
        self.assertEqual(self.launch(T0 + timedelta(hours=1)), [])
        self.assertEqual(self.member(1)["mint"], START)

        later = T0 + timedelta(days=1)
        self.add(3, "Newbie", joined=later)
        self.assertEqual(self.launch(later + timedelta(days=6, hours=23)), [])
        self.assertEqual(self.launch(later + timedelta(days=7)), [3])
        self.assertEqual(self.member(3)["mint"], START)

    def test_left_members_not_paid(self):
        self.add(1, "Gone")
        economy.mark_left(self.conn, 1)
        self.assertEqual(self.launch(), [])

    def test_starting_grant_not_counted_as_activity(self):
        self.add(1, "A")
        self.launch()
        self.assertEqual(economy.earned_today(self.conn, 1, T0), 0)

    # ---------------------------------------------------------------- gifts
    def test_give_moves_mint_to_trophy_case_and_logs(self):
        self.add(1, "A")
        self.add(2, "B")
        self.launch()
        left = economy.give(self.conn, 1, 2, 120, "nice meme", T0)
        self.assertEqual(left, START - 120)
        economy.give(self.conn, 1, 2, 30, None, T0)
        self.assertEqual(self.member(1)["mint"], START - 150)
        self.assertEqual(self.member(2)["mint"], START)  # received currency doesn't add to mint
        [t] = economy.trophies(self.conn, 2)
        self.assertEqual((t["owner_id"], t["amount"]), (1, 150))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM gifts").fetchone()[0], 2)

    def test_give_rules(self):
        self.add(1, "A")
        self.add(2, "B")
        self.launch()
        self.add(3, "New", joined=T0 - timedelta(days=1))
        with self.assertRaises(EconomyError):
            economy.give(self.conn, 1, 1, 10, None, T0)             # self
        with self.assertRaises(EconomyError):
            economy.give(self.conn, 1, 3, 10, None, T0)             # too new
        with self.assertRaises(EconomyError):
            economy.give(self.conn, 1, 2, START + 1, None, T0)      # too much
        with self.assertRaises(EconomyError):
            economy.give(self.conn, 1, 999, 10, None, T0)           # unknown
        economy.mark_left(self.conn, 2)
        with self.assertRaises(EconomyError):
            economy.give(self.conn, 1, 2, 10, None, T0)             # left server
        self.assertEqual(self.member(1)["mint"], START)             # nothing moved

    # ---------------------------------------------------------- adjustments
    def test_adjust_mint_and_holdings(self):
        self.add(1, "A")
        self.add(2, "B")
        self.launch()
        self.assertEqual(economy.adjust(self.conn, 9, 1, -100, "oops", T0), START - 100)
        with self.assertRaises(EconomyError):
            economy.adjust(self.conn, 9, 1, -START, None, T0)
        economy.give(self.conn, 1, 2, 50, None, T0)
        self.assertEqual(economy.adjust(self.conn, 9, 2, -50, "farmed", T0, currency_owner_id=1), 0)
        with self.assertRaises(EconomyError):
            economy.adjust(self.conn, 9, 2, -1, None, T0, currency_owner_id=1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM adjustments").fetchone()[0], 2)

    # -------------------------------------------------------------- boards
    def test_leaderboard_and_hoarders(self):
        for uid, name in [(1, "A"), (2, "B"), (3, "C")]:
            self.add(uid, name)
        self.launch()
        economy.give(self.conn, 1, 2, 40, None, T0)
        economy.give(self.conn, 1, 3, 40, None, T0)   # tie for A-bucks
        economy.give(self.conn, 2, 3, 100, None, T0)
        boards = economy.leaderboard(self.conn)
        self.assertEqual([(b["currency_name"], b["holders"], b["amount"]) for b in boards],
                         [("B-bucks", ["C"], 100), ("A-bucks", ["B", "C"], 40)])
        self.assertEqual([r["user_id"] for r in economy.hoarders(self.conn)], [3, 1, 2])


if __name__ == "__main__":
    unittest.main()
