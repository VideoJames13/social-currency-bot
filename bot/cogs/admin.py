"""Owner-only commands: /adjust and /setup.

Both are restricted twice: Discord hides them from non-admins (default_permissions),
and owner_only() rejects everyone except OWNER_ID from .env, admins included.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import economy, guide
from ..checks import owner_only
from ..config import CONFIG
from ..db import now_utc
from ..economy import EconomyError
from ..formatting import member_currency

log = logging.getLogger("bucks")

SETUP_STATE_KEY = "setup_message_ids"


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------------- /adjust
    @app_commands.command(name="adjust", description="Owner only: fix a balance by hand.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    @app_commands.describe(
        user="Whose balance to change",
        amount="How much to add (use a negative number to remove)",
        reason="Why (saved in the log)",
        currency="Leave empty to change their mint. Pick a member to change how much "
                 "of THAT member's currency is in their trophy case.",
    )
    async def adjust(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                     reason: Optional[app_commands.Range[str, 1, 200]] = None,
                     currency: Optional[discord.Member] = None):
        db = self.bot.db
        try:
            new = economy.adjust(db, interaction.user.id, user.id, amount, reason, now_utc(),
                                 currency_owner_id=currency.id if currency else None)
        except EconomyError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if currency:
            label = member_currency(economy.get_member(db, currency.id))
            where = f"{user.mention} now holds **{new:,} {label}**"
        else:
            label = member_currency(economy.get_member(db, user.id))
            where = f"{user.mention}'s mint is now **{new:,} {label}**"
        log.info("Adjust by %s: user=%s amount=%+d currency=%s reason=%r",
                 interaction.user.id, user.id, amount, currency.id if currency else None, reason)
        await interaction.response.send_message(f"Done ({amount:+,}). {where}.", ephemeral=True)

    # ----------------------------------------------------------------- /setup
    @app_commands.command(name="setup",
                          description="Owner only: post and pin the guide in the transactions channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    async def setup_pins(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = self.bot.get_channel(CONFIG.server.transactions_channel_id)
        if channel is None:
            return await interaction.followup.send(
                "I can't find the transactions channel. Check transactions_channel_id in "
                "config.toml and that I can view the channel.", ephemeral=True)
        try:
            # Replace the bot's earlier pins. Deleting a message also unpins it.
            async for msg in channel.pins(limit=50):
                if msg.author.id == self.bot.user.id:
                    await msg.delete()
            quiet = discord.AllowedMentions.none()
            guide_msg = await channel.send(guide.how_bucks_work(), allowed_mentions=quiet)
            voice_msg = await channel.send(guide.VOICE_NOTICE, allowed_mentions=quiet)
            # Newest pin shows first, so pin the guide last to keep it on top.
            await voice_msg.pin(reason="/setup")
            await guide_msg.pin(reason="/setup")
        except discord.Forbidden:
            return await interaction.followup.send(
                f"I'm missing permissions in {channel.mention}. I need View Channel, "
                "Send Messages, Read Message History and Pin Messages there.", ephemeral=True)
        self.bot.db.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (SETUP_STATE_KEY, f"{guide_msg.id},{voice_msg.id}"),
        )
        await interaction.followup.send(f"Posted and pinned the guide in {channel.mention}.",
                                        ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
