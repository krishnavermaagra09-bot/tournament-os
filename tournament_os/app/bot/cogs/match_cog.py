"""
Match cog — score submission, match status, standings.
Match lookups always include organization_id derived from the guild so that
a user cannot target a match from a different server by guessing its UUID.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class MatchCog(commands.Cog, name="match"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="submit_score", description="Submit your match score")
    @app_commands.describe(match_id="Match ID from your match channel")
    async def submit_score(self, interaction: discord.Interaction, match_id: str) -> None:
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.match import Match
        from app.bot.views.score_modal import ScoreModal
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
            result = await session.execute(guild_q)
            guild = result.scalar_one_or_none()
            if not guild:
                await interaction.response.send_message(embed=error_embed("Server not registered."), ephemeral=True)
                return

            # Scope to this guild's organization so cross-server guessing is impossible
            q = (
                select(Match)
                .where(Match.id == match_id)
                .where(Match.organization_id == guild.organization_id)
                .where(Match.deleted_at.is_(None))
            )
            result2 = await session.execute(q)
            match = result2.scalar_one_or_none()
            if not match:
                await interaction.response.send_message(embed=error_embed("Match not found."), ephemeral=True)
                return

        modal = ScoreModal(
            match_id=match_id,
            tournament_id=match.tournament_id,
            organization_id=match.organization_id,
            team1_id=match.team1_id or "",
            team2_id=match.team2_id or "",
        )
        await interaction.response.send_modal(modal)

    @app_commands.command(name="score_override", description="Override a match score (staff only)")
    @app_commands.describe(match_id="Match ID")
    async def score_override(self, interaction: discord.Interaction, match_id: str) -> None:
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.staff import StaffRole
        from app.database.models.match import Match
        from app.bot.views.score_modal import ScoreOverrideModal
        from app.bot.helpers.formatters import error_embed
        from app.bot.helpers.permissions import has_permission
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
            result = await session.execute(guild_q)
            guild = result.scalar_one_or_none()
            if not guild:
                await interaction.response.send_message(embed=error_embed("Server not registered."), ephemeral=True)
                return

            if not await has_permission(session, interaction.user, str(interaction.guild_id), StaffRole.REFEREE):
                await interaction.response.send_message(embed=error_embed("Insufficient permissions."), ephemeral=True)
                return

            q = (
                select(Match)
                .where(Match.id == match_id)
                .where(Match.organization_id == guild.organization_id)
                .where(Match.deleted_at.is_(None))
            )
            result2 = await session.execute(q)
            match = result2.scalar_one_or_none()
            if not match:
                await interaction.response.send_message(embed=error_embed("Match not found."), ephemeral=True)
                return

        modal = ScoreOverrideModal(
            match_id=match_id,
            tournament_id=match.tournament_id,
            organization_id=match.organization_id,
            team1_id=match.team1_id or "",
            team2_id=match.team2_id or "",
        )
        await interaction.response.send_modal(modal)

    @app_commands.command(name="standings", description="View tournament standings")
    @app_commands.describe(tournament_id="Tournament ID")
    async def standings(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer()
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.repositories.tournament import TournamentRepository
        from app.ai.tools.db_tools import AIDBTools
        from app.bot.helpers.formatters import standings_embed, error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
            result = await session.execute(guild_q)
            guild = result.scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."))
                return

            t_repo = TournamentRepository(session)
            tournament = await t_repo.get_by_id(tournament_id, guild.organization_id)
            if not tournament:
                await interaction.followup.send(embed=error_embed("Tournament not found."))
                return
            tournament_id = tournament.id  # normalize short ID to full UUID

            db_tools = AIDBTools(session, guild.organization_id, tournament_id)
            standings_data = await db_tools.get_standings(limit=20)
            await interaction.followup.send(embed=standings_embed(standings_data, tournament.name))

    @app_commands.command(name="my_matches", description="View your upcoming matches")
    @app_commands.describe(tournament_id="Tournament ID")
    async def my_matches(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.ai.tools.db_tools import AIDBTools
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
            result = await session.execute(guild_q)
            guild = result.scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                return

            from app.database.repositories.tournament import TournamentRepository
            t_repo = TournamentRepository(session)
            tournament = await t_repo.get_by_id(tournament_id, guild.organization_id)
            if not tournament:
                await interaction.followup.send(embed=error_embed("Tournament not found."), ephemeral=True)
                return
            tournament_id = tournament.id  # normalize short ID to full UUID

            db_tools = AIDBTools(session, guild.organization_id, tournament_id)
            matches = await db_tools.get_my_matches(str(interaction.user.id))

            if not matches:
                await interaction.followup.send("You have no matches scheduled.", ephemeral=True)
                return

            embed = discord.Embed(title="🎮 Your Matches", color=discord.Color.blue())
            for m in matches[:10]:
                embed.add_field(
                    name=f"Round {m['round']} | {m['status'].replace('_', ' ').title()}",
                    value=f"Scheduled: {m['scheduled_at']}\nMatch ID: `{m['id'][:8]}`",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="dispute", description="Open a dispute for a match")
    @app_commands.describe(match_id="Match ID", reason="Describe the issue")
    async def dispute(self, interaction: discord.Interaction, match_id: str, reason: str) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.match import Match
        from app.database.models.dispute import DisputeCaseType
        from app.database.repositories.user import UserRepository
        from app.services.dispute.case_manager import DisputeCaseManager
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            async with session.begin():
                guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
                result = await session.execute(guild_q)
                guild = result.scalar_one_or_none()
                if not guild:
                    await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                    return

                # Scope match lookup to this org — prevents cross-server targeting
                q = (
                    select(Match)
                    .where(Match.id == match_id)
                    .where(Match.organization_id == guild.organization_id)
                    .where(Match.deleted_at.is_(None))
                )
                result2 = await session.execute(q)
                match = result2.scalar_one_or_none()
                if not match:
                    await interaction.followup.send(embed=error_embed("Match not found."), ephemeral=True)
                    return

                user_repo = UserRepository(session)
                user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                svc = DisputeCaseManager(session)
                dispute = await svc.open_dispute(
                    organization_id=guild.organization_id,
                    tournament_id=match.tournament_id,
                    opened_by=user.id,
                    case_type=DisputeCaseType.WRONG_SCORE,
                    description=reason,
                    match_id=match_id,
                )
                await interaction.followup.send(
                    embed=success_embed(
                        f"Dispute opened!\nTicket ID: `{dispute.id[:8]}`\nStaff will review it shortly.",
                        title="Dispute Submitted"
                    ),
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchCog(bot))
