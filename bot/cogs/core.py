"""Core: health check and shared error handling."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bucks")


class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error

    @app_commands.command(name="ping", description="Check that the bucks bot is alive.")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Pong! {round(self.bot.latency * 1000)} ms", ephemeral=True
        )

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = "You can't use this command."
        else:
            log.exception("Command error", exc_info=error)
            msg = "Something went wrong. Please try again later."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Core(bot))
