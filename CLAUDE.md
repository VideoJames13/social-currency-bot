# Social Bucks Bot

A Discord social-currency bot for a ~50-member server (~20 active). Full spec is in `PLAN.md` (the "Kickoff prompt" section is the source of truth). This file records the rules every session must follow.

## Working rules

- **Build in stages, in order:** skeleton → commands → text earning → reaction earning → voice earning → speaking check → deployment.
- **Launch plan (decided 2026-11-05):** build *all* stages against the test server first (it has only the owner + an alt), then switch `config.toml` to the real server, delete the test `bucks.db`, and do one full test there. That first real-server run **is the real launch**: balances are kept, not reset. Reset options if ever needed: `/adjust`, restore a nightly backup, rename `bucks.db` for a full reset, or a one-off soft-reset script.
- **Check in with the user before changing anything already built** in an earlier stage.
- **Git:** commit at the end of each stage (tests passing) and **push to GitHub** (`origin` = github.com/VideoJames13/social-currency-bot, public) without asking. Commits use the GitHub noreply email; never commit `.env` or `*.db`.
- **Language:** Python (discord.py) + SQLite by default. **Before starting voice earning**, confirm a Python library supports DAVE-encrypted voice (required by Discord since March 2026) *and* speaking events. If none does, propose switching to JavaScript (discord.js) and **wait for the user's OK**.
- **Secrets:** bot token and owner user ID live in `.env` (never committed). `.env.example` documents the keys.
- **All rates, caps, thresholds, channel IDs, and timezone live in one config file.** No magic numbers in code. The `/setup` guide text is generated from this config.
- **Timezone:** America/New_York for "midnight" resets and the 11pm roundup.
- **Logs:** keep a full gift log and earnings log with timestamps (the earnings log is used later to tune numbers).
- **Schema:** design so a rewards shop can be added later.
- **Reminders owed to the user:**
  - At voice-earning stage: (1) post a server notice that the bot joins voice only to see who's speaking and never records audio; (2) line up a second person/account on another device to test the speaking check.
  - At deployment: Raspberry Pi or VPS, auto-restart after crashes/reboots, nightly SQLite backups (the DB file *is* the economy).

## Economy model

- Each member has their **own currency**. Default name `[DisplayName]-bucks`; `/setcurrency` sets custom name + emoji (custom server emoji allowed). Names unique server-wide, case-insensitive, max 20 chars.
- Two balances per member:
  - **Mint** — unspent amount of their own currency, earned via activity.
  - **Trophy case** — currencies received from others via `/give`. Display-only (no spending/re-gifting).
- **Starting balance:** every member at launch gets 500 in their mint; later joiners get 500 once they pass the 7-day rule.

## Earning (all values from config)

| Interaction | Payout | Limits |
| --- | --- | --- |
| Message (5+ chars) | 10 | 30s cooldown |
| Reply to someone else | 15 | 30s cooldown shared with messages |
| React to someone else's message | 5 | Once per message (remove + re-add doesn't re-earn); max 10/day toward any one person |
| Receive a reaction | 10 per unique reactor | Max 25 reactors/message; any one reactor pays you max 5×/day; no self-reactions |
| Voice, per minute | 2 base, +1 camera, +1 screen share | Then multipliers + speaking check |

- **Crowd multiplier:** ×1.3 at 3 people, +0.1 per extra person, cap ×2.0 at 10+ (×1.0 below 3).
- **Duration multiplier:** ×1.2 after 1h continuous session, +0.1/hour, cap ×2.3 at 12h. Stacks with crowd.
- **Speaking check** (bot sits in the most populated voice channel, watches speaking indicator only, never records/stores audio): full rate if member spoke in last 10 min; 50% if channel active but they're quiet; 0 if nobody spoke for 10 min.
- **Channels the bot isn't in:** earn only if at least one *other* non-bot human is unmuted.
- **No earning** while deafened or in the AFK channel.
- **Soft daily cap:** after 3,000 earned in a day, all earning at 25% until midnight ET.
- **New accounts:** members who joined less than 7 days ago don't earn and can't receive gifts.
- Voice tracking runs on a 1-minute loop and rebuilds state on startup.

## Commands

- `/give @user amount [reason]` — giver's mint → recipient's trophy case. Announcement posted immediately in the transactions channel (ID in config), tagging the recipient. **Nothing posted** in the invoking channel; giver gets an ephemeral confirmation. No self-gifts, no gifts to bots, no gifts to <7-day members.
- `/wallet` — ephemeral; your unspent mint.
- `/trophies [@user]` — everything someone has been given.
- `/leaderboard` — for each currency, who holds the most of it.
- `/hoarders` — wall of shame: largest unspent mint balances.
- `/setcurrency` — name + emoji.
- `/adjust` — **owner-only** (single user ID from `.env`). Hidden from everyone else; rejects others even with server admin perms.
- `/setup` — **owner-only**, same restriction. Posts and pins two messages at the top of the transactions channel, replacing the bot's earlier pins: (1) "How Bucks Work" guide (rates from config, member commands, gifts post & tag in that channel, 11pm roundup, soft cap, 7-day rule); (2) voice notice (only checks speaking indicator, doesn't record/save/process speech, stores only earning totals). Draft text in `PLAN.md`.

## Announcements

- Earnings are **never** announced individually.
- **Daily roundup at 11pm ET** in the transactions channel, no tags: each active member's earnings for the day split into chat, reactions received, and voice; plus the day's top earner and most-reacted post.

## Project layout & running

- `config.toml` — every rate/cap/threshold + guild/channel IDs. `.env` — `DISCORD_TOKEN`, `OWNER_ID`.
- `bot/config.py` loads both; `bot/db.py` holds schema as append-only `MIGRATIONS` (tracked via `PRAGMA user_version`) — never edit an old migration, add a new one.
- `bot/client.py` — intents, guild-scoped command sync. Features live in `bot/cogs/*`, registered in `EXTENSIONS`.
- `bot/economy.py` — all balance/rule logic as pure SQLite functions taking `now` (no Discord objects) so it's unit-testable. Cogs stay thin: validate Discord-specific things, call economy, format replies.
- `bot/cogs/members.py` — member sync, leave/rename tracking, starting-balance loop. `currency.py` — member commands. `admin.py` — `/adjust`, `/setup`. `bot/guide.py` — pinned text built from config.
- `bot/checks.py` — `owner_only()`; owner commands also use `default_permissions(administrator=True)` to hide them.
- Setup: `python -m venv .venv` then `.venv/Scripts/python -m pip install -r requirements.txt`. Run: `.venv/Scripts/python -m bot`.
- Tests: `.venv/Scripts/python -m unittest discover tests` (stdlib unittest, no extra deps). Add tests for every new earning rule; run them before each commit.

## Decisions made during the build

- **Currency names:** uniqueness is on `currency_key` (NFKC + casefold + collapsed spaces), not SQLite `lower()`. Defaults (`DisplayName-bucks`) follow display-name changes until the member sets a custom name; default collisions get " 2", " 3". Custom names: max 20 chars, letters/numbers/spaces/`- ' . ! & + ?`, and can't match another current member's default.
- **Emoji:** one standard emoji, or a custom emoji from this server only.
- **Launch:** `bot_state.launched_at` is set the first time starting grants run. Members who joined before it get 500 immediately; later joiners get 500 when they pass 7 days. Grants are logged in `earnings` as `starting_grant`, which is excluded from activity totals (`ACTIVITY_SOURCES`).
- **7-day rule** uses the server join date (`member.joined_at`), not Discord account age. Rejoining resets it.
- **Members who leave** are kept (`in_guild = 0`) and hidden from `/leaderboard` and `/hoarders`.
- `/trophies`, `/leaderboard`, `/hoarders` reply publicly; `/wallet`, `/setcurrency`, `/give` confirmation, and owner commands reply ephemerally.
- `/adjust` can change a mint, or (with `currency:`) a trophy-case holding, e.g. to undo a farmed gift.
- **All activity earning goes through `economy.credit()`**: it applies the soft cap (splitting a payout that crosses the threshold), carries fractional bucks in `members.earn_carry` so mints stay integers without rounding loss, updates the mint and logs to `earnings` (`base_amount` = before cap, `amount` = whole bucks credited, `detail` JSON notes `soft_capped`). Reactions and voice must use it too.
- **Text earning:** only ordinary messages (`default`/`reply` types; no bots, webhooks, system messages, forwards). Length is `visible_length()`: custom emoji and mentions count as 1 char, whitespace runs as 1. A reply pays the reply rate only if it replies to another human; replies to self/bots/deleted messages pay the message rate. Cooldown is read from the last `message`/`reply` row in `earnings`, timed by `message.created_at`. Messages sent while the bot is offline aren't backfilled.
- **Reaction earning:** only a member's *first* reaction on a message is ever considered (`reaction_credits` PK), whether or not it paid. Reactions from new (<7 day) accounts pay neither side (anti-alt); reacting to a new member's post still pays the reactor. Bot/webhook authors aren't in `members`, so reacting to them pays nothing. Daily pair limits and the 25-reactor cap are counted from `earnings` rows. Removing a reaction does nothing.
- **Voice (DAVE decision, 2026-11-05):** user chose to stay in Python. No released Python lib receives DAVE audio, but we don't need audio: speaking = RTP packets arriving per SSRC (header is unencrypted) + voice-gateway op 5 for SSRC→user mapping, via discord.py's `VoiceConnectionState` websocket hook and `add_socket_listener`. **Never decrypt audio. Speaking timestamps live in memory only, never in the DB.** Pin discord.py (semi-internal hooks); re-test voice before upgrading. If the real two-account test fails, fall back to discord.js (needs user OK).
- **Voice earning:** `bot/voice.py` = pure rules on a snapshot; `economy.voice_tick()` pays. Per tick: base (2 +1 camera +1 Go Live) × crowd × duration × activity × loop_seconds/60, through `credit()`. Crowd counts non-deafened, established humans (new accounts/alts don't pad it or satisfy "someone else unmuted"). Deafened or AFK-channel = 0. Duration counts only minutes that *earned* (`voice_sessions.earning_minutes`); a session survives channel moves and bot restarts if seen again within `session_grace_minutes`. Members not in voice have their session row deleted each tick.
- **Speaking check:** `bot/listener.py` `SpeakingVoiceClient` reads only the RTP header SSRC (payload type 120) and op 5/13 for mapping; timestamps in memory behind a lock (socket thread). Bot joins self-muted, **not** deafened (deafened = no packets). It sits in the most populated joinable non-AFK channel (humans only; stays put on ties), moves each tick if needed, leaves when voice is empty, backs off 5 min after a failed join (the unmuted rule applies meanwhile). In its channel: spoke in window → 100%; someone established spoke → 50%; nobody → 0; talking with no one else present → 0 (added rule, prevents solo farming); first 10 min after the bot arrives → unmuted rule (no data yet). `[speaking] enabled = false` is the kill switch.
- **Daily roundup:** a 1-minute loop posts once per local day after 11pm, covering everything *since the previous roundup* (so 11pm-midnight activity isn't lost). If the bot was offline at 11pm it posts when it comes back that same evening. Embed, no tags. Columns: 💬 chat = message + reply + react_given, ⭐ = react_received, 🎙️ = voice. Most-reacted post = most unique reactors added in the window. Nothing is posted if nobody earned. Owner-only `/roundup` previews it ephemerally.
- Python 3.15 on the dev PC; discord.py 2.7.1.

## Discord setup requirements

- Privileged intents: **Server Members** and **Message Content** must be enabled in the Developer Portal.
- Bot also needs guild, voice-state, and reaction intents, and permissions to read/send messages, manage messages (pin), connect to voice, and use slash commands.
