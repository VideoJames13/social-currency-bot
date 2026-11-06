# Social Currency Discord Bot Plan

Oct 16, 2026 · @James

At 50 members with about 20 active, the bot's workload is tiny, so the main decisions left are anti-farming rules and hosting. The command set and build order stay as planned: `/give`, `/wallet`, `/trophies`, `/setcurrency`, and `/leaderboard`, built in stages from skeleton to voice earning.

## Earning rates

Chat and reactions are weighted so a chatty day earns about as much as a couple of hours in voice.

| Interaction | Payout | Limits |
| --- | --- | --- |
| Send a message (5+ characters) | 10 | 30-second cooldown |
| Reply to someone else | 15 | 30-second cooldown, shared with messages |
| React to someone's message | 5 | Once per message; at most 10 times a day from reacting to any one person |
| Receive a reaction | 10 per unique reactor | Up to 25 reactors per message; any one person's reactions pay you at most 5 times a day |
| Voice, per minute | 2 base, +1 camera on, +1 screen sharing | Multipliers and speaking check below |

- **Crowd multiplier:** x1.3 at 3 people, +0.1 per extra person, up to x2.0 at 10+.
- **Duration multiplier:** x1.2 after 1 hour, +0.1 per extra hour, up to x2.3 at 12 hours. Both multipliers stack.
- **Daily soft cap:** after 3,000 earned in a day, everything earns 25% until midnight.

## Anti-farming rules

The bot can see who reacted to what, message timestamps and length, voice channel membership, mute, deafen, camera and screen-share status, and when each account joined. By sitting in a voice channel it can also see who is speaking; it only watches the speaking indicator and never records audio. It can sit in one voice channel per server at a time, so other channels fall back to the unmuted rule.

Since March 2026 Discord only accepts DAVE-encrypted voice connections. Before building voice earning, confirm a Python library supports DAVE and speaking events; if none does, build the bot in JavaScript (discord.js) instead.

| Loophole | Rule |
| --- | --- |
| Reaction spam | Only one reaction per message counts. Removing and re-adding a reaction earns nothing. |
| Friends trading reactions | Reacting to any one person earns at most 10 times a day; any one person's reactions pay you at most 5 times a day. |
| Spamming short messages | Messages need at least 5 characters, with a 30-second cooldown. |
| Idling in voice (speaking check) | Full rate if you've spoken in the last 10 minutes; 50% if the channel is active but you're quiet; nothing if nobody has spoken for 10 minutes. |
| Voice channels the bot isn't in | Earn only if at least one other person is unmuted. |
| Deafened or AFK | Deafened users and the AFK channel earn nothing. |
| Alt accounts | Accounts that joined in the last 7 days don't earn, and gifts to them are blocked. |
| Self-dealing | No gifts to yourself or to bots. |
| Grinding all day | Soft daily cap: after about 3,000 earned in a day, everything earns 25% until midnight. |

The soft cap is the only rule that limits the economy overall; the rest close specific loopholes. Every number lives in one config file. An admin-only `/adjust` command lets you fix balances by hand if something slips through.

## Hosting

Either option handles a server this size easily.

| Option | Cost | Trade-off |
| --- | --- | --- |
| Raspberry Pi | None if you already own one | Needs to stay plugged in with a stable connection |
| Cheap VPS | A few dollars a month | No hardware to manage, better uptime |

Build and test on your own computer first, then move it over. Have Claude Code set it up to restart automatically after crashes or reboots, and to back up the database file nightly. That file is the whole economy, so losing it wipes everyone's balances.

## Pinned messages

An owner-only `/setup` command posts and pins these two messages at the top of the transactions channel. The rates in the guide come from the config file, so re-running `/setup` after a change keeps the pins current. Drafts below use Discord formatting.

**1. How bucks work**

```
**How Bucks Work**
Everyone here has their own currency. Earn it by hanging out, then give it to whoever makes the server better.

**Earning** (goes into your mint)
- Message: 10 | Reply: 15
- Reacting to someone's post: 5
- Each person who reacts to YOUR post: 10
- Voice: 2/min, plus more for camera, screen share, bigger groups and longer sessions. Talk to earn the full rate.
- After 3,000 in a day, earnings drop to 25% until midnight.

**Commands**
/give @user amount reason - send your bucks
/wallet - your unspent mint (only you see it)
/trophies @user - everything someone has been given
/leaderboard - top holder of each currency
/hoarders - the wall of shame
/setcurrency - name your currency and pick an emoji

Gifts post here and tag the recipient. A daily roundup posts at 11pm. New accounts start earning after 7 days.
```

**2. Voice notice**

```
**About the bot in voice**
The bucks bot may sit in a voice channel. It only checks the speaking indicator (the same green ring you see) to tell who's actively talking. It doesn't record, save, or process what anyone says. The only thing stored is how many bucks you earned.
```

## Kickoff prompt for Claude Code

Open Claude Code in an empty folder and paste this. Once the bot has run for a week or two, the leaderboard and earnings log will show whether any numbers need adjusting.

```
Build a Discord bot (SQLite) for a social currency system on a ~50-member server. Prefer Python (discord.py), but voice earning needs speaking detection: since March 2026 Discord only accepts DAVE-encrypted voice connections. Before building voice, confirm a Python library supports DAVE and speaking events; if none does, propose switching to JavaScript (discord.js) and wait for my OK.

Each member has their own currency (default "[DisplayName]-bucks"; /setcurrency sets a custom name + emoji). Currency names must be unique across the server (case-insensitive, max 20 characters) so no one can duplicate someone else's; custom server emoji are allowed. At launch, every current member starts with 500 in their mint, and members who join later get the same 500 once they pass the 7-day account rule. Members earn their OWN currency into a "mint" balance through activity:
- 10 per message of 5+ characters, 15 per reply to someone else (shared 30s cooldown)
- 5 per reaction on others' messages (once per message; removing and re-adding doesn't re-earn; max 10/day from reacting to any single person)
- 10 per unique person who reacts to your message (max 25 reactors per message; any one person's reactions pay you at most 5 times/day; no self-reactions)
- Voice: 2 per minute base, +1 with camera on, +1 while screen sharing, then multipliers. Crowd multiplier scales linearly from x1.3 at 3 people to x2.0 at 10+ (+0.1 per additional person). Duration multiplier scales from x1.2 after 1h to x2.3 after 12h of continuous session (+0.1 per hour). Multipliers stack.
- Speaking check: the bot joins the most populated voice channel and watches speaking indicators only (never records or stores audio). Full voice rate if the member spoke in the last 10 minutes; 50% if the channel is active but they're quiet; 0 if nobody has spoken for 10 minutes. In channels the bot isn't in, earn only if at least one OTHER non-bot human is unmuted. No earning while deafened or in the AFK channel.
- Soft daily cap: after ~3,000 earned in a day, all earning is at 25% until midnight (America/New_York)
- Accounts that joined less than 7 days ago don't earn and can't receive gifts

/give @user amount [reason] moves currency from the giver's mint into the recipient's trophy case and immediately posts the announcement in a dedicated transactions channel (channel ID set in config), tagging the recipient. Nothing is posted in the channel where /give was used; the giver gets an ephemeral confirmation instead. Earnings are never announced individually: once a day at 11pm America/New_York, post a roundup in the transactions channel with no tags, listing each active member's earnings for the day split into chat, reactions received, and voice, plus the day's top earner and most-reacted post. No self-gifts, no gifts to bots. Received currency is display-only. Also: /wallet (ephemeral), /trophies [@user], /leaderboard (for each currency, who holds the most of it), /hoarders (a wall of shame ranking the largest unspent mint balances), and /adjust. /adjust is restricted to a single owner user ID stored in .env (the person who installed the bot); it is hidden from everyone else and rejects anyone else even if they have server admin permissions. Add an owner-only /setup command (same restriction) that posts and pins two messages at the top of the transactions channel, replacing the bot's earlier pins: (1) a "How Bucks Work" guide listing earning rates generated from the config file, all member commands, that gifts post in that channel and tag the recipient, the 11pm daily roundup, the daily soft cap, and the 7-day new-account rule; (2) a voice notice saying the bot may sit in a voice channel, only checks the speaking indicator to tell who is actively talking, doesn't record, save, or process what anyone says, and stores only earning totals. Keep a full gift log and earnings log with timestamps. Put every rate, cap, and threshold in one config file. Voice tracking runs on a 1-minute loop and rebuilds state on startup. Keep the token in .env. Design the schema so a rewards shop can be added later.

Before writing code, walk me through Discord Developer Portal setup step by step, and remind me to enable both the Server Members and Message Content intents. When we reach voice earning, remind me to (1) post a notice in the server explaining the bot joins voice only to see who is speaking and never records audio, and (2) line up a second person or a second account on another device to test the speaking check. Build in stages (skeleton -> commands -> text earning -> reaction earning -> voice earning -> speaking check), and check in with me before changing anything we've already built. At the end, help me deploy it to a Raspberry Pi or a VPS with auto-restart and nightly database backups.
```
