"""
Search Cog — search is now button-driven via the Control Panel and Player Hub.

Access:
  Staff:  Control Panel → 🔍 Search button
  Player: Player Hub → 🔍 Search button

Operations available via SearchPanelView:
  📅 Find Tournament | 👥 Find Team | 🎮 Find Matches
"""
import logging
from discord.ext import commands

logger = logging.getLogger(__name__)


class SearchCog(commands.Cog, name="search"):
    """Search operations live in SearchPanelView — this cog is a registry stub."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
