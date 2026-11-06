"""Display helpers shared by cogs."""

from discord.utils import escape_markdown

EMBED_COLOR = 0xF1C40F
EMBED_LIMIT = 4000  # Discord allows 4096 in an embed description; leave headroom


def currency_label(name: str, emoji: str | None) -> str:
    name = escape_markdown(name)
    return f"{emoji} {name}" if emoji else name


def member_currency(row) -> str:
    return currency_label(row["currency_name"], row["currency_emoji"])


def plain(text: str) -> str:
    return escape_markdown(text)


def join_lines(lines: list[str], limit: int = EMBED_LIMIT) -> str:
    """Join lines, cutting off with '...and N more' if it would be too long."""
    out, used = [], 0
    for i, line in enumerate(lines):
        remaining = len(lines) - i
        tail = f"\n...and {remaining} more"
        if used + len(line) + 1 + len(tail) > limit and remaining > 1:
            out.append(tail.strip())
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def clock_time(hour: int, minute: int) -> str:
    """23, 0 -> '11pm'; 21, 30 -> '9:30pm'."""
    suffix = "am" if hour < 12 else "pm"
    h = hour % 12 or 12
    return f"{h}{suffix}" if minute == 0 else f"{h}:{minute:02d}{suffix}"
