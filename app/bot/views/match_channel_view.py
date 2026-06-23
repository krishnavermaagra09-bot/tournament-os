"""
Match Channel Score View — persistent button posted in private match channels.

A single constant custom_id allows this view to be registered once at bot
startup and handle ALL match channels automatically after restarts.
The match is looked up by channel_id at click time.
"""
import logging

import discord

logger = logging.getLogger(__name__)


class MatchScoreButtonView(discord.ui.View):
    """Persistent view — one instance covers every match channel."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Submit Score",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="match_channel:submit_score",
    )
    async def submit_score(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        """Look up the match by channel_id, verify caller is a captain, open ScoreModal."""
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match, MatchStatus
        from app.database.models.team import Team
        from app.database.models.user import User
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        channel_id_str = str(interaction.channel_id)

        async with AsyncSessionLocal() as session:
            q = select(Match).where(
                Match.private_channel_id == channel_id_str,
                Match.deleted_at.is_(None),
            )
            match = (await session.execute(q)).scalar_one_or_none()

            if not match:
                await interaction.response.send_message(
                    embed=error_embed("Could not find a match linked to this channel."),
                    ephemeral=True,
                )
                return

            if match.status == MatchStatus.COMPLETED:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="✅ Already Completed",
                        description="This match has already been scored.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
                return

            user_q = select(User).where(
                User.discord_user_id == str(interaction.user.id)
            ).limit(1)
            caller = (await session.execute(user_q)).scalar_one_or_none()

            team1 = await session.get(Team, match.team1_id) if match.team1_id else None
            team2 = await session.get(Team, match.team2_id) if match.team2_id else None

            is_captain = caller and (
                (team1 and team1.captain_id == caller.id)
                or (team2 and team2.captain_id == caller.id)
            )

            if not is_captain:
                await interaction.response.send_message(
                    embed=error_embed(
                        "Only the **team captain** can submit a score.\n"
                        "If you believe this is wrong, contact a staff member."
                    ),
                    ephemeral=True,
                )
                return

            match_id = match.id
            org_id = match.organization_id
            t_id = match.tournament_id
            t1_id = match.team1_id
            t2_id = match.team2_id

        from app.bot.views.score_modal import ScoreModal
        modal = ScoreModal(
            match_id=match_id,
            tournament_id=t_id,
            organization_id=org_id,
            team1_id=t1_id,
            team2_id=t2_id,
        )
        await interaction.response.send_modal(modal)
