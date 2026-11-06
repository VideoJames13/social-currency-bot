"""Text earning: messages and replies."""

import logging

import discord
from discord.ext import commands

from .. import economy
from ..config import CONFIG

log = logging.getLogger("bucks")

# Ordinary typed messages only (not joins, pins, boosts, slash-command echoes, ...).
_EARNING_TYPES = (discord.MessageType.default, discord.MessageType.reply)


def reply_target(message: discord.Message) -> int | None:
    """User ID this message replies to, if it's a reply to another human."""
    ref = message.reference
    if (message.type != discord.MessageType.reply or ref is None
            or ref.type != discord.MessageReferenceType.reply):
        return None
    original = ref.resolved
    if not isinstance(original, discord.Message):  # deleted or not delivered
        return None
    author = original.author
    if author.bot or author.id == message.author.id:
        return None
    return author.id


class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (message.guild is None or message.guild.id != CONFIG.server.guild_id
                or message.author.bot or message.webhook_id is not None
                or message.type not in _EARNING_TYPES):
            return
        if economy.visible_length(message.content) < CONFIG.chat.min_message_length:
            return
        target = reply_target(message)
        paid = economy.earn_chat(self.bot.db, message.author.id, message.created_at,
                                 message_id=message.id, reply_to=target)
        if paid is not None:
            log.debug("%s earned %d for %s", message.author.id, paid,
                      "reply" if target else "message")


async def setup(bot):
    await bot.add_cog(Chat(bot))
