"""Uptime monitor check-in (e.g. healthchecks.io).

Every few minutes: if the bot is connected, the database answers, and every background
loop is running, ping HEALTHCHECK_URL. If something is wrong, ping <url>/fail with the
reason. If the bot dies or hangs, pings stop and the monitor emails you.
Sends nothing but the URL and, on failure, a short status line. No server data.
"""

import logging

import aiohttp
from discord.ext import commands, tasks

from ..config import CONFIG, HEALTHCHECK_URL

log = logging.getLogger("bucks")

# (cog name, loop attribute) that must be running.
LOOPS = [("Members", "grant_loop"), ("Roundup", "roundup_loop"), ("Voice", "voice_loop")]


class Health(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self.health_loop.change_interval(minutes=CONFIG.safety.healthcheck_interval_minutes)

    async def cog_load(self):
        if HEALTHCHECK_URL:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self.health_loop.start()
        else:
            log.info("HEALTHCHECK_URL not set; uptime check-ins disabled")

    async def cog_unload(self):
        self.health_loop.cancel()
        if self.session:
            await self.session.close()

    def problems(self) -> list[str]:
        issues = []
        if self.bot.is_closed() or not self.bot.is_ready():
            issues.append("not connected to Discord")
        try:
            self.bot.db.execute("SELECT 1").fetchone()
        except Exception as e:
            issues.append(f"database error: {e}")
        for cog_name, attr in LOOPS:
            cog = self.bot.get_cog(cog_name)
            if cog is None or not getattr(cog, attr).is_running():
                issues.append(f"{cog_name}.{attr} not running")
        return issues

    @tasks.loop(minutes=5)
    async def health_loop(self):
        issues = self.problems()
        url = HEALTHCHECK_URL.rstrip("/") + ("/fail" if issues else "")
        try:
            async with self.session.post(url, data="; ".join(issues) or "ok") as resp:
                if resp.status >= 400:
                    log.warning("Health check-in got HTTP %s", resp.status)
        except (aiohttp.ClientError, TimeoutError) as e:
            log.warning("Health check-in failed: %s", e)
        if issues:
            log.error("Health problems: %s", "; ".join(issues))

    @health_loop.error
    async def _error(self, error):
        log.exception("Health loop error", exc_info=error)

    @health_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Health(bot))
