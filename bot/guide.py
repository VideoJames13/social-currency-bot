"""Text for the two messages /setup pins. Rates come from config.toml."""

from .config import CONFIG
from .formatting import clock_time


def how_bucks_work() -> str:
    c = CONFIG
    soft_pct = round(c.soft_cap.rate_after * 100)
    roundup = clock_time(c.roundup.hour, c.roundup.minute)
    days = c.economy.min_account_age_days
    return f"""\
**How Bucks Work**
Everyone here has their own currency. Earn it by hanging out, then give it to whoever makes the server better. Everyone starts with {c.economy.starting_balance:,} in their mint.

**Earning** (goes into your mint)
- Message: {c.chat.message_reward} | Reply: {c.chat.reply_reward}
- Reacting to someone's post: {c.reactions.give_reward}
- Each person who reacts to YOUR post: {c.reactions.receive_reward}
- Voice: {c.voice.base_per_minute}/min, plus more for camera, screen share, bigger groups and longer sessions. Talk to earn the full rate.
- After {c.soft_cap.daily_threshold:,} in a day, earnings drop to {soft_pct}% until midnight.

**Commands**
/give @user amount reason - send your bucks
/wallet - your unspent mint (only you see it)
/trophies @user - everything someone has been given
/leaderboard - top holder of each currency
/hoarders - the wall of shame
/setcurrency - name your currency and pick an emoji

Gifts post here and tag the recipient. A daily roundup posts at {roundup}. New members can earn and receive gifts after {days} days in the server."""


VOICE_NOTICE = """\
**About the bot in voice**
The bucks bot may sit in a voice channel. It only checks the speaking indicator (the same green ring you see) to tell who's actively talking. It doesn't record, save, or process what anyone says. The only thing stored is how many bucks you earned."""
