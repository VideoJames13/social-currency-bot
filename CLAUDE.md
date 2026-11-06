# Social Bucks Bot

A Discord social-currency bot for a ~50-member server (~20 active). Full spec is in `PLAN.md` (the "Kickoff prompt" section is the source of truth). This file records the rules every session must follow.

## Working rules

- **Build in stages, in order:** skeleton → commands → text earning → reaction earning → voice earning → speaking check → deployment.
- **Check in with the user before changing anything already built** in an earlier stage.
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

## Discord setup requirements

- Privileged intents: **Server Members** and **Message Content** must be enabled in the Developer Portal.
- Bot also needs guild, voice-state, and reaction intents, and permissions to read/send messages, manage messages (pin), connect to voice, and use slash commands.
