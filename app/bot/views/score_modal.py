"""
Score submission modal.

Captains use submit_team_score_claim() (dual-submission, auto-approved when
both sides agree).  Staff / referees use submit_score() directly (overrides).
"""
import discord
import logging

logger = logging.getLogger(__name__)


class ScoreModal(discord.ui.Modal, title="Submit Match Score"):
    score_mine = discord.ui.TextInput(
        label="Your Team Score",
        placeholder="e.g. 2",
        required=True,
        max_length=10,
    )
    score_opponent = discord.ui.TextInput(
        label="Opponent Score",
        placeholder="e.g. 1",
        required=True,
        max_length=10,
    )
    notes = discord.ui.TextInput(
        label="Notes (optional)",
        placeholder="Any relevant details about the match",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        team1_id: str,
        team2_id: str,
    ):
        super().__init__()
        self.match_id = match_id
        self.tournament_id = tournament_id
        self.organization_id = organization_id
        self.team1_id = team1_id
        self.team2_id = team2_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        from app.database.session import AsyncSessionLocal
        from app.services.match.score_handler import ScoreHandler
        from app.database.repositories.user import UserRepository
        from app.bot.helpers.formatters import success_embed, error_embed, info_embed
        from sqlalchemy import select, and_
        from app.database.models.team import TeamMember

        async with AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(
                        str(interaction.user.id), interaction.user.name
                    )

                    try:
                        s_mine = int(self.score_mine.value.strip())
                        s_opp = int(self.score_opponent.value.strip())
                    except ValueError:
                        await interaction.followup.send(
                            embed=error_embed("Scores must be integers (e.g. 2 and 1)."),
                            ephemeral=True,
                        )
                        return

                    handler = ScoreHandler(session)

                    # Determine which team this user is on (for dual-submission flow)
                    claiming_team_id: str | None = None
                    opposing_team_id: str | None = None

                    if self.team1_id or self.team2_id:
                        team_ids = [t for t in [self.team1_id, self.team2_id] if t]
                        q = select(TeamMember).where(
                            and_(
                                TeamMember.user_id == user.id,
                                TeamMember.team_id.in_(team_ids),
                                TeamMember.is_active.is_(True),
                            )
                        )
                        result = await session.execute(q)
                        member = result.scalar_one_or_none()
                        if member:
                            claiming_team_id = member.team_id
                            opposing_team_id = (
                                self.team2_id
                                if claiming_team_id == self.team1_id
                                else self.team1_id
                            )

                    if claiming_team_id:
                        # Captain dual-submission path
                        my_score = s_mine
                        opp_score = s_opp
                        winner_id: str | None = (
                            claiming_team_id if my_score > opp_score
                            else (opposing_team_id if opp_score > my_score else None)
                        )
                        loser_id: str | None = (
                            opposing_team_id if my_score > opp_score
                            else (claiming_team_id if opp_score > my_score else None)
                        )

                        outcome = await handler.submit_team_score_claim(
                            match_id=self.match_id,
                            tournament_id=self.tournament_id,
                            organization_id=self.organization_id,
                            claiming_team_id=claiming_team_id,
                            score_team1=(
                                {"score": my_score}
                                if claiming_team_id == self.team1_id
                                else {"score": opp_score}
                            ),
                            score_team2=(
                                {"score": opp_score}
                                if claiming_team_id == self.team1_id
                                else {"score": my_score}
                            ),
                            winner_id=winner_id,
                            loser_id=loser_id,
                        )

                        if outcome == "pending":
                            await interaction.followup.send(
                                embed=info_embed(
                                    f"Score recorded: **{s_mine} – {s_opp}**\n"
                                    "⏳ Waiting for the opposing team to confirm.\n"
                                    "Scores will be finalised automatically when both sides agree.",
                                    title="Score Pending Confirmation",
                                ),
                                ephemeral=True,
                            )
                        elif outcome == "auto_approved":
                            await interaction.followup.send(
                                embed=success_embed(
                                    f"Score **{s_mine} – {s_opp}** confirmed! ✅\n"
                                    "Both teams agree — bracket has been advanced.",
                                    title="Score Confirmed",
                                ),
                                ephemeral=True,
                            )
                        elif outcome == "disputed":
                            await interaction.followup.send(
                                embed=discord.Embed(
                                    title="⚠️ Score Conflict",
                                    description=(
                                        f"You submitted **{s_mine} – {s_opp}**, but the opposing "
                                        "team reported a different result.\n"
                                        "A staff member will review the dispute. "
                                        "Use `/dispute` to add more context."
                                    ),
                                    color=discord.Color.orange(),
                                ),
                                ephemeral=True,
                            )
                        else:
                            await interaction.followup.send(
                                embed=success_embed(f"Score submitted: **{s_mine} – {s_opp}**"),
                                ephemeral=True,
                            )
                    else:
                        # Fallback: not on either team — treat like staff (direct submit)
                        winner_id = (
                            self.team1_id if s_mine > s_opp
                            else (self.team2_id if s_opp > s_mine else None)
                        )
                        loser_id = (
                            self.team2_id if s_mine > s_opp
                            else (self.team1_id if s_opp > s_mine else None)
                        )
                        await handler.submit_score(
                            match_id=self.match_id,
                            tournament_id=self.tournament_id,
                            organization_id=self.organization_id,
                            submitted_by=user.id,
                            score_team1={"score": s_mine},
                            score_team2={"score": s_opp},
                            winner_id=winner_id,
                            loser_id=loser_id,
                        )
                        await interaction.followup.send(
                            embed=success_embed(f"Score submitted: **{s_mine} – {s_opp}**"),
                            ephemeral=True,
                        )

                except Exception as exc:
                    logger.error("Score modal error: %s", exc, exc_info=True)
                    await interaction.followup.send(
                        embed=error_embed(str(exc)), ephemeral=True
                    )


class ScoreOverrideModal(discord.ui.Modal, title="Override Match Score"):
    score_team1 = discord.ui.TextInput(label="Team 1 Score", required=True, max_length=10)
    score_team2 = discord.ui.TextInput(label="Team 2 Score", required=True, max_length=10)
    reason = discord.ui.TextInput(
        label="Override Reason",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        team1_id: str,
        team2_id: str,
    ):
        super().__init__()
        self.match_id = match_id
        self.tournament_id = tournament_id
        self.organization_id = organization_id
        self.team1_id = team1_id
        self.team2_id = team2_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.services.match.score_handler import ScoreHandler
        from app.database.repositories.user import UserRepository
        from app.bot.helpers.formatters import success_embed, error_embed

        async with AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(
                        str(interaction.user.id), interaction.user.name
                    )
                    try:
                        s1 = int(self.score_team1.value.strip())
                        s2 = int(self.score_team2.value.strip())
                    except ValueError:
                        await interaction.followup.send(
                            embed=error_embed("Scores must be whole numbers (e.g. 2 and 1)."),
                            ephemeral=True,
                        )
                        return
                    winner_id = (
                        self.team1_id if s1 > s2 else (self.team2_id if s2 > s1 else None)
                    )
                    loser_id = (
                        self.team2_id if s1 > s2 else (self.team1_id if s2 > s1 else None)
                    )
                    handler = ScoreHandler(session)
                    await handler.submit_score(
                        match_id=self.match_id,
                        tournament_id=self.tournament_id,
                        organization_id=self.organization_id,
                        submitted_by=user.id,
                        score_team1={"score": s1},
                        score_team2={"score": s2},
                        winner_id=winner_id,
                        loser_id=loser_id,
                        is_override=True,
                        override_reason=self.reason.value,
                    )
                    await interaction.followup.send(
                        embed=success_embed(
                            f"Score overridden to **{s1} – {s2}**.\nReason: {self.reason.value}"
                        ),
                        ephemeral=True,
                    )
                except Exception as exc:
                    await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
