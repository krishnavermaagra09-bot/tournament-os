"""
Audit Cog — audit trail and snapshots are now button-driven via the Control Panel.

Access: Control Panel → 📜 Audit Trail | 📸 Snapshots buttons.

Both panels are handled by control_panel_view._panel_audit and _panel_snapshots.
"""
import logging
from discord.ext import commands

logger = logging.getLogger(__name__)


class AuditCog(commands.Cog, name="audit"):
    """Audit operations live in the Control Panel — this cog is a registry stub."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))
