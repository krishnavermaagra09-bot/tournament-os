"""
Dispute Cog — dispute management is now button-driven via the Control Panel.

Access: Control Panel → ⚖️ Disputes button.

The disputes panel shows all open disputes. A "Resolve" button on each dispute
opens a modal to submit the resolution. Dispute creation for players is via
the 🎮 Matches → dispute flow in match_cog.
"""
import logging
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class _ResolveModal(discord.ui.Modal, title="⚖️ Resolve Dispute"):
    resolution = discord.ui.TextInput(
        label="Resolution notes",
        style=discord.TextStyle.paragraph,
        min_length=10,
        placeholder="Describe how the dispute was resolved…",
    )

    def __init__(self, dispute_id: str, org_id: str):
        super().__init__()
        self._dispute_id = dispute_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.dispute import Dispute
        from app.database.repositories.user import UserRepository
        from app.services.dispute.case_manager import DisputeCaseManager
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select, cast, String

        async with AsyncSessionLocal() as session:
            async with session.begin():
                q = (
                    select(Dispute)
                    .where(cast(Dispute.id, String).like(f"{self._dispute_id}%"))
                    .where(Dispute.deleted_at.is_(None))
                    .where(Dispute.organization_id == self._org_id)
                )
                dispute = (await session.execute(q)).scalar_one_or_none()
                if not dispute:
                    await interaction.followup.send(embed=error_embed(f"Dispute `{self._dispute_id}` not found."), ephemeral=True)
                    return

                user_repo = UserRepository(session)
                user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                svc = DisputeCaseManager(session)
                await svc.resolve(
                    dispute_id=dispute.id,
                    organization_id=self._org_id,
                    tournament_id=dispute.tournament_id,
                    resolved_by=user.id,
                    resolution=self.resolution.value.strip(),
                )

        await interaction.followup.send(
            embed=success_embed(f"Dispute `{self._dispute_id[:8]}` resolved.", title="⚖️ Dispute Resolved"),
            ephemeral=True,
        )
        logger.info("dispute.resolve: id=%s by=%s", self._dispute_id[:8], interaction.user.id)


class DisputeCog(commands.Cog, name="dispute"):
    """Dispute management lives in the Control Panel disputes panel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisputeCog(bot))
