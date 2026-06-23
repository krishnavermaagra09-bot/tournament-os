"""
Check-in button view — persists across bot restarts (timeout=None).

The custom_id encodes both tournament_id and organization_id so that after
a bot restart the persistent view can still route the interaction correctly
without any in-memory state.

Format: "checkin:<tournament_id>:<organization_id>"
Max length: "checkin:" (8) + UUID (36) + ":" (1) + UUID (36) = 81 chars (well under Discord's 100-char limit).
"""
import logging

import discord

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "checkin"


def _make_custom_id(tournament_id: str, organization_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{tournament_id}:{organization_id}"


def _parse_custom_id(custom_id: str) -> tuple[str, str] | None:
    """Return (tournament_id, organization_id) or None if the custom_id is invalid."""
    parts = custom_id.split(":", 2)
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    _, tournament_id, organization_id = parts
    return tournament_id, organization_id


class CheckInView(discord.ui.View):
    def __init__(self, tournament_id: str, organization_id: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.organization_id = organization_id

        # Build the button dynamically so custom_id encodes both IDs.
        # This is required for persistent views (timeout=None) because Discord
        # routes button interactions by custom_id — the view must be re-added
        # at startup with the same custom_id to receive interactions after restart.
        button: discord.ui.Button = discord.ui.Button(
            label="Check In",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=_make_custom_id(tournament_id, organization_id),
        )
        button.callback = self._handle_checkin
        self.add_item(button)

    async def _handle_checkin(self, interaction: discord.Interaction) -> None:
        from app.database.session import AsyncSessionLocal
        from app.database.repositories.tournament import TournamentRepository
        from app.database.repositories.team import TeamRepository
        from app.database.repositories.user import UserRepository
        from app.services.checkin.window import CheckInService
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select
        from app.database.models.team import TeamMember
        from app.database.models.user import User

        await interaction.response.defer(ephemeral=True)

        # Resolve tournament_id / organization_id from the button's custom_id so
        # this still works after a bot restart (instance vars may be empty on
        # views reconstructed without positional args during add_view).
        raw_custom_id: str = interaction.data.get("custom_id", "")
        parsed = _parse_custom_id(raw_custom_id)
        if parsed is None:
            await interaction.followup.send(
                embed=error_embed("Invalid check-in button. Please contact an admin."),
                ephemeral=True,
            )
            return
        tournament_id, organization_id = parsed

        async with AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    t_repo = TournamentRepository(session)
                    tournament = await t_repo.get_by_id(tournament_id, organization_id)
                    if not tournament:
                        await interaction.followup.send(
                            embed=error_embed("Tournament not found."), ephemeral=True
                        )
                        return

                    team_repo = TeamRepository(session)
                    discord_uid = str(interaction.user.id)

                    # Try captain lookup first (joins through User.discord_user_id)
                    team = await team_repo.get_by_captain(organization_id, tournament_id, discord_uid)

                    # Fall back: user is a non-captain team member
                    if not team:
                        q = (
                            select(TeamMember)
                            .join(User, TeamMember.user_id == User.id)
                            .where(User.discord_user_id == discord_uid)
                            .where(TeamMember.tournament_id == tournament_id)
                            .where(TeamMember.is_active.is_(True))
                        )
                        result = await session.execute(q)
                        member = result.scalar_one_or_none()
                        if member:
                            team = await team_repo.get_by_id(
                                member.team_id, organization_id, tournament_id
                            )

                    if not team:
                        await interaction.followup.send(
                            embed=error_embed("You are not registered for this tournament."),
                            ephemeral=True,
                        )
                        return

                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(discord_uid, interaction.user.name)

                    svc = CheckInService(session)
                    if await svc.is_checked_in(tournament_id, organization_id, team.id):
                        await interaction.followup.send(
                            embed=success_embed(f"**{team.name}** is already checked in! ✅"),
                            ephemeral=True,
                        )
                        return

                    await svc.checkin_team(tournament, team.id, user.id, method="button")
                    await interaction.followup.send(
                        embed=success_embed(f"**{team.name}** has successfully checked in! ✅"),
                        ephemeral=True,
                    )

                except ValueError as exc:
                    await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
                except Exception as exc:
                    logger.error("Check-in button error: %s", exc, exc_info=True)
                    await interaction.followup.send(
                        embed=error_embed("An error occurred. Please try again."), ephemeral=True
                    )
