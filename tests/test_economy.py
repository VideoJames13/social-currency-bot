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


class Base(unittest.TestCase):
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


class EconomyTest(Base):
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


class TextEarningTest(Base):
    def setUp(self):
        super().setUp()
        self.add(1, "A")
        self.add(2, "B")
        self.launch()

    def chat(self, at, uid=1, reply_to=None):
        return economy.earn_chat(self.conn, uid, at, reply_to=reply_to)

    def test_message_and_reply_rewards(self):
        self.assertEqual(self.chat(T0), CONFIG.chat.message_reward)
        self.assertEqual(self.chat(T0 + timedelta(minutes=1), reply_to=2), CONFIG.chat.reply_reward)
        self.assertEqual(self.member(1)["mint"],
                         START + CONFIG.chat.message_reward + CONFIG.chat.reply_reward)
        self.assertEqual(economy.earned_today(self.conn, 1, T0),
                         CONFIG.chat.message_reward + CONFIG.chat.reply_reward)

    def test_shared_cooldown(self):
        cd = CONFIG.chat.cooldown_seconds
        self.assertIsNotNone(self.chat(T0))
        self.assertIsNone(self.chat(T0 + timedelta(seconds=cd - 1), reply_to=2))  # shared
        self.assertIsNotNone(self.chat(T0 + timedelta(seconds=cd)))
        self.assertIsNotNone(self.chat(T0, uid=2))  # cooldowns are per member

    def test_new_and_departed_members_dont_earn(self):
        self.add(3, "New", joined=T0 - timedelta(days=6))
        self.assertIsNone(self.chat(T0, uid=3))
        self.assertIsNotNone(self.chat(T0 + timedelta(days=1), uid=3))
        economy.mark_left(self.conn, 2)
        self.assertIsNone(self.chat(T0, uid=2))
        self.assertIsNone(self.chat(T0, uid=999))  # unknown

    def test_soft_cap_split_and_fraction_carry(self):
        member = self.member(1)
        with db.transaction(self.conn):  # get to 5 below the cap
            economy.credit(self.conn, member, "message",
                           CONFIG.soft_cap.daily_threshold - 5, T0)
        rate = CONFIG.soft_cap.rate_after          # 0.25
        reward = CONFIG.chat.message_reward        # 10
        t = T0 + timedelta(minutes=1)
        # 5 at full rate + 5 at 25% = 6.25 -> 6 now, 0.25 carried
        self.assertEqual(self.chat(t), int(5 + 5 * rate))
        # 2.5 + 0.25 = 2.75 -> 2, carry 0.75; then 2.5 + 0.75 = 3.25 -> 3
        self.assertEqual(self.chat(t + timedelta(minutes=1)), 2)
        self.assertEqual(self.chat(t + timedelta(minutes=2)), 3)
        self.assertAlmostEqual(self.member(1)["earn_carry"], 0.25)
        detail = self.conn.execute(
            "SELECT detail FROM earnings ORDER BY id DESC LIMIT 1").fetchone()["detail"]
        self.assertIn("soft_capped", detail)
        # Next day (midnight America/New_York = 05:00 UTC in November): full rate again
        next_day = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(self.chat(next_day - timedelta(minutes=1)), 2)  # still capped day
        self.assertEqual(self.chat(next_day), reward)

    def test_visible_length(self):
        cases = {
            "hey": 3, "hello": 5, "  hi     yo  ": 5,
            "<:pizza:123456789012345678>": 1, "<a:x:123456789012345678> ok": 4,
            "<@123456789012345678> hi": 4, "<@&123> <#456>": 3,
        }
        for text, n in cases.items():
            with self.subTest(text=text):
                self.assertEqual(economy.visible_length(text), n)


class ReactionTest(Base):
    R = CONFIG.reactions

    def setUp(self):
        super().setUp()
        self.add(1, "Reactor")
        self.add(2, "Author")
        self.launch()

    def react(self, msg, reactor=1, author=2, at=T0):
        return economy.earn_reaction(self.conn, reactor, author, msg, 555, at)

    def test_pays_both_sides_once_per_message(self):
        self.assertEqual(self.react(100), (self.R.give_reward, self.R.receive_reward))
        self.assertEqual(self.react(100), (None, None))  # re-add / second emoji
        self.assertEqual(self.member(1)["mint"], START + self.R.give_reward)
        self.assertEqual(self.member(2)["mint"], START + self.R.receive_reward)

    def test_self_bot_and_unknown(self):
        self.assertEqual(self.react(100, reactor=2, author=2), (None, None))
        self.assertEqual(self.react(101, author=999), (None, None))  # bot/webhook author
        self.assertEqual(self.react(102, reactor=999), (None, None))

    def test_daily_pair_limits_and_reset(self):
        results = [self.react(200 + i) for i in range(12)]
        given = [g for g, _ in results if g is not None]
        received = [r for _, r in results if r is not None]
        self.assertEqual(len(given), self.R.give_daily_limit_per_target)        # 10
        self.assertEqual(len(received), self.R.receive_daily_limit_per_reactor)  # 5
        tomorrow = T0 + timedelta(days=1)
        self.assertEqual(self.react(300, at=tomorrow),
                         (self.R.give_reward, self.R.receive_reward))

    def test_limit_is_per_pair(self):
        for i in range(self.R.give_daily_limit_per_target):
            self.react(200 + i)
        self.add(3, "Other")
        self.launch()
        self.assertEqual(self.react(400, author=3), (self.R.give_reward, self.R.receive_reward))

    def test_max_reactors_per_message(self):
        n = self.R.receive_max_reactors_per_message
        for uid in range(10, 10 + n + 2):
            self.add(uid, f"U{uid}")
        self.launch()
        paid = [self.react(500, reactor=uid)[1] for uid in range(10, 10 + n + 2)]
        self.assertEqual(sum(p is not None for p in paid), n)

    def test_new_accounts(self):
        self.add(3, "NewReactor", joined=T0 - timedelta(days=1))
        self.assertEqual(self.react(600, reactor=3), (None, None))   # earns nothing, pays nothing
        later = T0 + timedelta(days=7)
        self.assertEqual(self.react(600, reactor=3, at=later), (None, None))  # already used
        self.add(4, "NewAuthor", joined=T0 - timedelta(days=1))
        self.assertEqual(self.react(601, author=4), (self.R.give_reward, None))


class RoundupTest(Base):
    def setUp(self):
        super().setUp()
        for uid, name in [(1, "Alice"), (2, "Bob"), (3, "Cara")]:
            self.add(uid, name)
        self.launch()

    def test_window_split_and_highlights(self):
        start, end = T0, T0 + timedelta(hours=10)
        economy.earn_chat(self.conn, 1, T0 + timedelta(hours=1))                # Alice chat 10
        economy.earn_chat(self.conn, 2, T0 + timedelta(hours=1), reply_to=1)   # Bob chat 15
        for reactor in (1, 3):                                                 # 2 people on Bob's post
            economy.earn_reaction(self.conn, reactor, 2, 900, 555, T0 + timedelta(hours=2))
        economy.earn_reaction(self.conn, 2, 1, 901, 555, T0 + timedelta(hours=3))
        economy.earn_chat(self.conn, 3, end + timedelta(minutes=1))            # outside window
        data = economy.roundup(self.conn, start, end)
        by_name = {p["name"]: p for p in data["members"]}
        R = CONFIG.reactions
        self.assertEqual(by_name["Bob"]["chat"], CONFIG.chat.reply_reward + R.give_reward)
        self.assertEqual(by_name["Bob"]["reactions"], 2 * R.receive_reward)
        self.assertEqual(by_name["Alice"]["chat"], CONFIG.chat.message_reward + R.give_reward)
        self.assertEqual(by_name["Cara"]["chat"], R.give_reward)
        self.assertEqual(data["members"][0]["name"], "Bob")
        self.assertEqual((data["top_post"]["message_id"], data["top_post"]["reactors"]), (900, 2))
        self.assertNotIn("starting_grant", str(data))

    def test_due_once_per_day_at_roundup_time(self):
        # Nov 5 2026, America/New_York is UTC-5: 23:00 local = 04:00 UTC Nov 6
        before = datetime(2026, 11, 6, 3, 59, tzinfo=timezone.utc)
        at = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)
        self.assertFalse(economy.roundup_due(self.conn, before))
        self.assertTrue(economy.roundup_due(self.conn, at))
        economy.mark_roundup_done(self.conn, at)
        self.assertFalse(economy.roundup_due(self.conn, at + timedelta(minutes=30)))
        self.assertFalse(economy.roundup_due(self.conn, at + timedelta(hours=12)))  # next day, 11am
        self.assertTrue(economy.roundup_due(self.conn, at + timedelta(days=1)))
        self.assertEqual(economy.roundup_window_start(self.conn, at + timedelta(days=1)), at)


from bot import voice  # noqa: E402
from bot.voice import VoiceChannel, VoiceMember as VM  # noqa: E402


class VoiceRulesTest(unittest.TestCase):
    def test_crowd_multiplier(self):
        expected = {1: 1.0, 2: 1.0, 3: 1.3, 4: 1.4, 9: 1.9, 10: 2.0, 25: 2.0}
        for n, m in expected.items():
            with self.subTest(n=n):
                self.assertEqual(voice.crowd_multiplier(n), m)

    def test_duration_multiplier(self):
        expected = {0: 1.0, 59: 1.0, 60: 1.2, 119: 1.2, 120: 1.3, 11 * 60: 2.2, 12 * 60: 2.3,
                    30 * 60: 2.3}
        for mins, m in expected.items():
            with self.subTest(mins=mins):
                self.assertEqual(voice.duration_multiplier(mins), m)

    def test_base_rate(self):
        self.assertEqual(voice.base_rate(VM(1)), 2)
        self.assertEqual(voice.base_rate(VM(1, video=True)), 3)
        self.assertEqual(voice.base_rate(VM(1, video=True, stream=True)), 4)


class VoiceTickTest(Base):
    def setUp(self):
        super().setUp()
        for uid in range(1, 13):
            self.add(uid, f"U{uid}")
        self.launch()

    def tick(self, channels, at):
        return economy.voice_tick(self.conn, channels, at)

    def test_pair_earns_base_rate(self):
        ch = VoiceChannel(10, [VM(1), VM(2)])
        self.assertEqual(self.tick([ch], T0), {1: 2, 2: 2})

    def test_alone_deafened_afk_and_muted_others(self):
        self.assertEqual(self.tick([VoiceChannel(10, [VM(1)])], T0), {})                  # alone
        self.assertEqual(self.tick([VoiceChannel(10, [VM(1), VM(2, deaf=True, muted=True)])],
                                   T0), {})                                                # other deaf
        self.assertEqual(self.tick([VoiceChannel(10, [VM(1, deaf=True, muted=True), VM(2)])],
                                   T0), {})                                                # 2 has nobody
        self.assertEqual(self.tick([VoiceChannel(10, [VM(1), VM(2)], afk=True)], T0), {})  # AFK
        # 1 is muted but 2 is talking: 1 still earns (listening); 2 has nobody unmuted.
        self.assertEqual(self.tick([VoiceChannel(10, [VM(1, muted=True), VM(2)])], T0), {1: 2})

    def test_new_accounts_dont_earn_or_count(self):
        self.add(50, "Alt", joined=T0 - timedelta(days=1))
        ch = VoiceChannel(10, [VM(1, muted=True), VM(50)])   # only the alt is unmuted
        self.assertEqual(self.tick([ch], T0), {})
        crowd = VoiceChannel(10, [VM(1), VM(2), VM(50), VM(51)])  # 51 isn't even registered
        self.assertEqual(self.tick([crowd], T0), {1: 2, 2: 2})    # crowd is 2, not 4

    def test_crowd_and_camera(self):
        ch = VoiceChannel(10, [VM(1, video=True, stream=True)] + [VM(u) for u in range(2, 11)])
        paid = self.tick([ch], T0)  # 10 people -> x2.0
        self.assertEqual(paid[1], 8)
        self.assertEqual(paid[2], 4)

    def test_fractions_carry(self):
        ch = VoiceChannel(10, [VM(u) for u in (1, 2, 3)])  # x1.3 -> 2.6/min
        got = [self.tick([ch], T0 + timedelta(minutes=i))[1] for i in range(5)]
        self.assertEqual(sum(got), 13)  # 5 * 2.6 = 13 exactly, nothing lost to rounding
        self.assertEqual(got[:3], [2, 3, 2])

    def test_duration_session_and_reset(self):
        ch = VoiceChannel(10, [VM(1), VM(2)])
        for i in range(60):
            self.tick([ch], T0 + timedelta(minutes=i))
        detail = lambda: self.conn.execute(  # noqa: E731
            "SELECT detail FROM earnings WHERE user_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()["detail"]
        self.assertIn('"duration": 1.0', detail())
        self.tick([VoiceChannel(11, [VM(1), VM(2)])], T0 + timedelta(minutes=60))  # moved channel
        self.assertIn('"duration": 1.2', detail())                                  # kept session
        # Gone longer than the grace period -> new session
        back = T0 + timedelta(minutes=61 + CONFIG.voice.session_grace_minutes + 1)
        self.tick([ch], back)
        self.assertIn('"duration": 1.0', detail())

    def test_non_earning_minutes_dont_build_duration(self):
        alone = VoiceChannel(10, [VM(1)])
        for i in range(90):
            self.tick([alone], T0 + timedelta(minutes=i))
        row = self.conn.execute("SELECT earning_minutes FROM voice_sessions WHERE user_id = 1"
                                ).fetchone()
        self.assertEqual(row["earning_minutes"], 0)

    def test_sessions_dropped_when_leaving_voice(self):
        self.tick([VoiceChannel(10, [VM(1), VM(2)])], T0)
        self.tick([VoiceChannel(10, [VM(1)])], T0 + timedelta(minutes=1))
        ids = [r[0] for r in self.conn.execute("SELECT user_id FROM voice_sessions")]
        self.assertEqual(ids, [1])

    def test_soft_cap_applies_to_voice(self):
        with db.transaction(self.conn):
            economy.credit(self.conn, self.member(1), "message", CONFIG.soft_cap.daily_threshold, T0)
        ch = VoiceChannel(10, [VM(1), VM(2)])
        got = [self.tick([ch], T0 + timedelta(minutes=i)).get(1, 0) for i in range(4)]
        self.assertEqual(sum(got), 2)  # 4 minutes * 2 * 25%


class SpeakingCheckTest(unittest.TestCase):
    EST = {1, 2, 3}
    W = timedelta(minutes=CONFIG.speaking.window_minutes)

    def factor(self, uid, members, spoke=None, since=T0 - timedelta(hours=1), now=T0):
        ch = VoiceChannel(10, members, listening_since=since, last_spoke=spoke or {})
        member = next(m for m in members if m.user_id == uid)
        return voice.activity_factor(member, ch, self.EST, now)

    def test_spoke_quiet_silent(self):
        people = [VM(1), VM(2), VM(3)]
        recently = T0 - timedelta(minutes=3)
        self.assertEqual(self.factor(1, people, {1: recently}), (1.0, "spoke"))
        self.assertEqual(self.factor(2, people, {1: recently}),
                         (CONFIG.speaking.quiet_rate, "quiet"))
        self.assertEqual(self.factor(1, people, {1: T0 - self.W - timedelta(seconds=1)}),
                         (0.0, "silent_channel"))
        self.assertEqual(self.factor(1, people, {1: T0 - self.W}), (1.0, "spoke"))  # edge

    def test_muted_listener_still_gets_quiet_rate(self):
        people = [VM(1, muted=True), VM(2)]
        self.assertEqual(self.factor(1, people, {2: T0}), (CONFIG.speaking.quiet_rate, "quiet"))

    def test_talking_alone_earns_nothing(self):
        self.assertEqual(self.factor(1, [VM(1)], {1: T0}), (0.0, "alone"))
        self.assertEqual(self.factor(1, [VM(1), VM(2, deaf=True)], {1: T0}), (0.0, "alone"))
        self.assertEqual(self.factor(1, [VM(1), VM(99)], {1: T0}), (0.0, "alone"))  # 99 = alt

    def test_alt_speaking_doesnt_make_channel_active(self):
        self.assertEqual(self.factor(1, [VM(1), VM(2), VM(99)], {99: T0}),
                         (0.0, "silent_channel"))

    def test_warm_up_uses_unmuted_rule(self):
        since = T0 - timedelta(minutes=2)
        self.assertEqual(self.factor(1, [VM(1), VM(2)], since=since), (1.0, "warming_up"))
        self.assertEqual(self.factor(1, [VM(1), VM(2, muted=True)], since=since),
                         (0.0, "warming_up"))

    def test_channels_without_bot_use_unmuted_rule(self):
        ch = VoiceChannel(10, [VM(1), VM(2)])
        self.assertEqual(voice.activity_factor(VM(1), ch, self.EST, T0), (1.0, "unmuted_other"))


class ListenerTest(unittest.TestCase):
    """Speaking detection bookkeeping, without a real voice connection."""

    def setUp(self):
        import threading
        from bot.listener import SpeakingVoiceClient
        self.vc = SpeakingVoiceClient.__new__(SpeakingVoiceClient)  # skip network setup
        self.vc._lock = threading.Lock()
        self.vc._ssrc_user, self.vc._last_spoke = {}, {}

    @staticmethod
    def rtp(ssrc, pt=120, marker=False, size=60):
        header = bytes([0x80, pt | (0x80 if marker else 0), 0, 1, 0, 0, 0, 0])
        return header + ssrc.to_bytes(4, "big") + bytes(size - 12)

    def test_rtp_ssrc(self):
        from bot.listener import rtp_ssrc
        self.assertEqual(rtp_ssrc(self.rtp(1234)), 1234)
        self.assertEqual(rtp_ssrc(self.rtp(1234, marker=True)), 1234)
        self.assertIsNone(rtp_ssrc(self.rtp(1234, pt=72)))          # RTCP (200 & 0x7F)
        self.assertIsNone(rtp_ssrc(bytes([0, 2, 0, 70]) + bytes(70)))  # IP discovery
        self.assertIsNone(rtp_ssrc(b"\x80\x78"))                      # truncated

    def test_packets_mark_mapped_users_only(self):
        import asyncio
        self.vc._on_packet(self.rtp(555))
        self.assertEqual(self.vc.last_spoke(), {})                    # unknown SSRC ignored
        asyncio.run(self.vc._on_ws_message(None, {"op": 5, "d": {
            "user_id": "42", "ssrc": 555, "speaking": 0}}))
        self.assertEqual(self.vc.last_spoke(), {})                    # mapping only
        self.vc._on_packet(self.rtp(555))
        self.assertIn(42, self.vc.last_spoke())
        asyncio.run(self.vc._on_ws_message(None, {"op": 13, "d": {"user_id": "42"}}))
        self.assertEqual(self.vc._ssrc_user, {})
        asyncio.run(self.vc._on_ws_message(None, {"op": 5, "d": {"bad": 1}}))  # ignored


class SafetyTest(unittest.TestCase):
    def test_post_guard_trips_and_recovers(self):
        from bot.safety import PostGuard
        g = PostGuard(limit=3)
        times = [T0 + timedelta(minutes=i) for i in range(3)]
        self.assertTrue(all(g.allow(t) for t in times))
        self.assertFalse(g.allow(T0 + timedelta(minutes=10)))
        self.assertTrue(g.tripped)
        self.assertEqual(g.resumes_at(), T0 + timedelta(hours=1))
        self.assertFalse(g.allow(T0 + timedelta(minutes=59)))
        self.assertTrue(g.allow(T0 + timedelta(hours=1)))    # oldest post aged out
        self.assertFalse(g.tripped)
        self.assertFalse(g.allow(T0 + timedelta(hours=1, seconds=1)))  # still 3 in window

    def test_bot_post_blocks_and_warns_owner_once(self):
        import asyncio
        from types import SimpleNamespace
        from bot.client import BucksBot, PostingPaused
        from bot.safety import PostGuard

        sent, dms = [], []

        class FakeChannel:
            async def send(self, *a, **k):
                sent.append(a)

        bot = BucksBot.__new__(BucksBot)
        bot.post_guard = PostGuard(limit=2)
        bot._owner_warned = False

        async def dm(text):
            dms.append(text)
        bot._dm_owner = dm

        async def run():
            ch = FakeChannel()
            await bot.post(ch, "a")
            await bot.post(ch, "b")
            for _ in range(3):
                with self.assertRaises(PostingPaused):
                    await bot.post(ch, "spam")
        asyncio.run(run())
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(dms), 1)


if __name__ == "__main__":
    unittest.main()
