"""
Override Cog — all override operations are now button-driven via the Control Panel.

Access: Control Panel → 🛠️ Overrides button.

Operations available via OverridePanelView:
  🚫 DQ Team | ⚔️ Set Winner | ⏩ Advance Round | 👻 Forfeit No-shows
  📸 Take Snapshot | 🔁 Restore Snapshot
"""
import logging
from discord.ext import commands

logger = logging.getLogger(__name__)


class OverrideCog(commands.Cog, name="override"):
    """Override operations live in OverridePanelView — this cog is a registry stub."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OverrideCog(bot))
