"""Daily roundup in the transactions channel (default 11pm local time). No tags."""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import economy
from ..checks import owner_only
from ..config import CONFIG, TZ
from ..db import now_utc
from ..formatting import EMBED_COLOR, join_lines, plain

log = logging.getLogger("bucks")

LEGEND = "💬 chat (messages, replies, reacting) · ⭐ reactions received · 🎙️ voice"


def build_embed(data: dict, end) -> discord.Embed | None:
    members = data["members"]
    if not members:
        return None
    top = members[0]
    header = [f"🏅 **Top earner:** {plain(top['name'])} (+{top['total']:,})"]
    post = data["top_post"]
    if post:
        link = (f"https://discord.com/channels/{CONFIG.server.guild_id}/"
                f"{post['channel_id']}/{post['message_id']}")
        people = "person" if post["reactors"] == 1 else "people"
        header.append(f"🔥 **Most-reacted post:** [{plain(post['author_name'])}'s post]({link})"
                      f", {post['reactors']} {people} reacted")
    lines = [
        f"**{plain(p['name'])}** +{p['total']:,}  ·  "
        f"💬 {p['chat']:,}  ⭐ {p['reactions']:,}  🎙️ {p['voice']:,}"
        for p in members
    ]
    title = f"📊 Daily roundup: {end.astimezone(TZ).strftime('%A, %b')} {end.astimezone(TZ).day}"
    embed = discord.Embed(title=title, color=EMBED_COLOR,
                          description=join_lines(header + [""] + lines))
    embed.set_footer(text=LEGEND)
    return embed


class Roundup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.roundup_loop.start()

    async def cog_unload(self):
        self.roundup_loop.cancel()

    @tasks.loop(minutes=1)
    async def roundup_loop(self):
        db, now = self.bot.db, now_utc()
        if not economy.roundup_due(db, now):
            return
        start = economy.roundup_window_start(db, now)
        data = economy.roundup(db, start, now)
        embed = build_embed(data, now)
        if embed is not None:
            channel = self.bot.get_channel(CONFIG.server.transactions_channel_id)
            if channel is None:
                log.error("Roundup: transactions channel not found; will retry")
                return
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                log.exception("Roundup: couldn't post; will retry")
                return
            log.info("Posted daily roundup (%d members)", len(data["members"]))
        else:
            log.info("Daily roundup: no earnings, nothing posted")
        economy.mark_roundup_done(db, now)

    @roundup_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="roundup",
                          description="Owner only: preview tonight's roundup (only you see it).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    async def preview(self, interaction: discord.Interaction):
        db, now = self.bot.db, now_utc()
        start = economy.roundup_window_start(db, now)
        embed = build_embed(economy.roundup(db, start, now), now)
        if embed is None:
            return await interaction.response.send_message(
                "No earnings since the last roundup yet.", ephemeral=True)
        await interaction.response.send_message(
            f"Preview (since <t:{int(start.timestamp())}:f>). Not posted.",
            embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Roundup(bot))
