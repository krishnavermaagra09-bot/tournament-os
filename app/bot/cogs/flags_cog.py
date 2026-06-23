"""
Flags Cog — feature flags and webhook management are now button-driven via the Control Panel.

Access: Control Panel → ⚙️ Settings button.

Operations available via SettingsPanelView:
  Toggle any of the 6 known feature flags | Add Webhook | List Webhooks | Remove Webhook
"""
import logging
from discord.ext import commands

logger = logging.getLogger(__name__)


class FlagsCog(commands.Cog, name="flags"):
    """Flags/webhook operations live in SettingsPanelView — this cog is a registry stub."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FlagsCog(bot))
