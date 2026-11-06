"""Member commands: /give, /wallet, /trophies, /leaderboard, /hoarders, /setcurrency."""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import economy
from ..config import CONFIG
from ..db import now_utc
from ..economy import EconomyError
from ..formatting import EMBED_COLOR, currency_label, join_lines, member_currency, plain

log = logging.getLogger("bucks")

NAME_MAX = CONFIG.economy.currency_name_max_length


async def _reply(interaction: discord.Interaction, text: str):
    await interaction.response.send_message(text, ephemeral=True)


class Currency(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------------ /give
    @app_commands.command(name="give", description="Give some of your currency to someone.")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Who to give to",
        amount="How much of your currency to give",
        reason="Why (shown in the announcement)",
    )
    async def give(self, interaction: discord.Interaction, user: discord.Member,
                   amount: app_commands.Range[int, 1, 1_000_000_000],
                   reason: Optional[app_commands.Range[str, 1, 200]] = None):
        if user.bot:
            return await _reply(interaction, "Bots can't receive bucks.")
        now = now_utc()
        economy.grant_starting_balances(self.db, now)
        try:
            left = economy.give(self.db, interaction.user.id, user.id, amount, reason, now)
        except EconomyError as e:
            return await _reply(interaction, str(e))

        label = member_currency(economy.get_member(self.db, interaction.user.id))
        await _reply(
            interaction,
            f"Sent **{amount:,} {label}** to {user.mention}. You have **{left:,}** left in your mint.",
        )

        text = f"🎁 {interaction.user.mention} gave {user.mention} **{amount:,} {label}**"
        if reason:
            text += f"\n> {reason}"
        channel = self.bot.get_channel(CONFIG.server.transactions_channel_id)
        try:
            if channel is None:
                raise RuntimeError("transactions channel not found")
            await channel.send(text, allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=[user]))
        except (discord.HTTPException, RuntimeError):
            log.exception("Couldn't post gift announcement")
            await interaction.followup.send(
                "Your gift went through, but I couldn't post the announcement. "
                "Let the server owner know.", ephemeral=True)

    # ---------------------------------------------------------------- /wallet
    @app_commands.command(name="wallet", description="See your unspent mint (only you see this).")
    @app_commands.guild_only()
    async def wallet(self, interaction: discord.Interaction):
        now = now_utc()
        economy.grant_starting_balances(self.db, now)
        me = economy.get_member(self.db, interaction.user.id)
        if me is None:
            return await _reply(interaction, "You're not registered yet. Try again in a minute.")

        lines = [f"Your mint: **{me['mint']:,} {member_currency(me)}**"]
        joined = economy.parse_ts(me["joined_at"])
        if not economy.is_established(joined, now):
            if joined:
                when = int(economy.established_at(joined).timestamp())
                lines.append(f"You're new here, so you start earning <t:{when}:R>.")
            if not me["starting_granted"]:
                lines.append(f"Your starting {CONFIG.economy.starting_balance:,} arrives then too.")
        else:
            earned = economy.earned_today(self.db, me["user_id"], now)
            cap = CONFIG.soft_cap.daily_threshold
            if earned >= cap:
                pct = round(CONFIG.soft_cap.rate_after * 100)
                lines.append(f"Earned today: **{earned:,}**. You're past the {cap:,} soft cap, "
                             f"so everything earns {pct}% until midnight.")
            else:
                lines.append(f"Earned today: **{earned:,}** / {cap:,} before the soft cap.")
        await _reply(interaction, "\n".join(lines))

    # -------------------------------------------------------------- /trophies
    @app_commands.command(name="trophies", description="See everything someone has been given.")
    @app_commands.guild_only()
    @app_commands.describe(user="Whose trophy case (leave empty for your own)")
    async def trophies(self, interaction: discord.Interaction,
                       user: Optional[discord.Member] = None):
        user = user or interaction.user
        if user.bot:
            return await _reply(interaction, "Bots don't have trophy cases.")
        rows = economy.trophies(self.db, user.id)
        if rows:
            body = join_lines([
                f"**{r['amount']:,}** {currency_label(r['currency_name'], r['currency_emoji'])}"
                for r in rows
            ])
        else:
            body = "Nothing yet."
        embed = discord.Embed(title=f"🏆 {user.display_name}'s trophy case",
                              description=body, color=EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    # ----------------------------------------------------------- /leaderboard
    @app_commands.command(name="leaderboard", description="Who holds the most of each currency.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction):
        boards = economy.leaderboard(self.db)
        if boards:
            lines = []
            for b in boards:
                holders = ", ".join(plain(h) for h in b["holders"])
                each = " each" if len(b["holders"]) > 1 else ""
                label = currency_label(b["currency_name"], b["currency_emoji"])
                lines.append(f"{label}: **{holders}** ({b['amount']:,}{each})")
            body = join_lines(lines)
        else:
            body = "No one has given any bucks yet."
        embed = discord.Embed(title="👑 Top holder of each currency", description=body,
                              color=EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------- /hoarders
    @app_commands.command(name="hoarders", description="The wall of shame: biggest unspent mints.")
    @app_commands.guild_only()
    async def hoarders(self, interaction: discord.Interaction):
        rows = economy.hoarders(self.db)
        if rows:
            body = join_lines([
                f"{i}. **{plain(r['display_name'])}** is sitting on {r['mint']:,} {member_currency(r)}"
                for i, r in enumerate(rows, start=1)
            ])
        else:
            body = "No hoarders. Everyone's generous!"
        embed = discord.Embed(title="🐉 Wall of Shame", description=body, color=EMBED_COLOR)
        embed.set_footer(text="Bucks are meant to be given. /give some away!")
        await interaction.response.send_message(embed=embed)

    # ----------------------------------------------------------- /setcurrency
    @app_commands.command(name="setcurrency", description="Name your currency and pick an emoji.")
    @app_commands.guild_only()
    @app_commands.describe(
        name=f"Your currency's name (up to {NAME_MAX} characters, must be unique)",
        emoji="One emoji. This server's custom emoji work too.",
    )
    async def setcurrency(self, interaction: discord.Interaction,
                          name: Optional[app_commands.Range[str, 1, NAME_MAX]] = None,
                          emoji: Optional[app_commands.Range[str, 1, 100]] = None):
        if name is None and emoji is None:
            me = economy.get_member(self.db, interaction.user.id)
            current = member_currency(me) if me else "not set"
            return await _reply(interaction, f"Your currency is **{current}**. "
                                             "Give a name, an emoji, or both to change it.")
        try:
            if emoji is not None:
                emoji = economy.validate_emoji(emoji, {e.id for e in interaction.guild.emojis})
            economy.set_currency(self.db, interaction.user.id, name=name, emoji=emoji)
        except EconomyError as e:
            return await _reply(interaction, str(e))
        me = economy.get_member(self.db, interaction.user.id)
        await _reply(interaction, f"Your currency is now **{member_currency(me)}**.")


async def setup(bot):
    await bot.add_cog(Currency(bot))
