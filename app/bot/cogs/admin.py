"""
Admin Cog — staff-only commands.

Button-first rule: player-facing features use Discord buttons, not slash commands.
Staff tools here are OK as slash commands because they're admin utilities.

Commands:
  /staff seed      — seed N fake teams into a tournament for testing
  /staff simulate  — simulate a complete match round with random scores
  /staff status    — show bot health + active tournament summary
"""
import logging
import random
import string

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def _rand_name(prefix: str = "Team") -> str:
    suffix = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"{prefix} {suffix}"


def _rand_ign(game: str = "Game") -> str:
    words = ["Shadow", "Blaze", "Storm", "Echo", "Nova", "Viper", "Ghost", "Titan"]
    nums = random.randint(100, 9999)
    return f"{random.choice(words)}{nums}"


class StaffGroup(app_commands.Group):
    """Staff-only tournament management commands."""

    def __init__(self):
        super().__init__(name="staff", description="Staff tournament management tools")

    @app_commands.command(name="status", description="Show bot health and active tournaments")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament, TournamentStatus
        from app.database.models.guild import Guild
        from app.database.models.match import Match, MatchStatus
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()

            if not guild:
                await interaction.followup.send("⚠️ This server is not registered.", ephemeral=True)
                return

            active_q = select(Tournament).where(
                Tournament.organization_id == guild.organization_id,
                Tournament.status.notin_([TournamentStatus.CANCELLED, TournamentStatus.ARCHIVED]),
                Tournament.deleted_at.is_(None),
            )
            tournaments = (await session.execute(active_q)).scalars().all()

            embed = discord.Embed(
                title="🤖 Bot Status",
                color=discord.Color.green(),
            )
            embed.add_field(name="Latency", value=f"{interaction.client.latency * 1000:.1f} ms", inline=True)
            embed.add_field(name="Guild", value=guild.discord_guild_id[:8], inline=True)
            embed.add_field(name="Active Tournaments", value=str(len(tournaments)), inline=True)

            for t in tournaments[:5]:
                live_matches_q = select(func.count()).where(
                    Match.tournament_id == t.id,
                    Match.status == MatchStatus.LIVE,
                    Match.deleted_at.is_(None),
                )
                live_count = (await session.execute(live_matches_q)).scalar() or 0
                embed.add_field(
                    name=t.name[:50],
                    value=(
                        f"Status: **{t.status.value.replace('_', ' ').title()}**\n"
                        f"Live matches: {live_count}\n"
                        f"Autonomous: {'✅' if t.autonomous_mode else '❌'}"
                    ),
                    inline=True,
                )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="seed",
        description="[TEST] Create fake teams in a tournament so you can test the full flow",
    )
    @app_commands.describe(
        tournament_id="First 8 chars of the tournament ID (from /staff status)",
        count="Number of fake teams to create (default 4, max 16)",
    )
    @app_commands.default_permissions(administrator=True)
    async def seed(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        count: int = 4,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        count = max(2, min(count, 16))

        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament, TeamSizeType
        from app.database.models.team import Team, TeamMember
        from app.database.models.user import User
        from app.database.models.guild import Guild
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            async with session.begin():
                guild_q = select(Guild).where(
                    Guild.discord_guild_id == str(interaction.guild_id),
                    Guild.deleted_at.is_(None),
                )
                guild = (await session.execute(guild_q)).scalar_one_or_none()
                if not guild:
                    await interaction.followup.send("Server not registered.", ephemeral=True)
                    return

                # Find tournament by prefix
                t_q = select(Tournament).where(
                    Tournament.organization_id == guild.organization_id,
                    Tournament.deleted_at.is_(None),
                )
                all_t = (await session.execute(t_q)).scalars().all()
                tournament = next(
                    (t for t in all_t if t.id.startswith(tournament_id) or t.id[:8] == tournament_id[:8]),
                    None,
                )
                if not tournament:
                    await interaction.followup.send(
                        f"Tournament `{tournament_id}` not found. Use **/staff status** to see IDs.",
                        ephemeral=True,
                    )
                    return

                is_solo = (
                    tournament.team_size_type == TeamSizeType.SOLO
                    or (tournament.max_team_size or 1) <= 1
                )
                team_size = 1 if is_solo else max(tournament.min_team_size or 1, 2)
                game = tournament.game or "Game"

                teams_created: list[str] = []

                for t_num in range(1, count + 1):
                    t_name = _rand_name("Team") if not is_solo else _rand_ign(game)

                    # Create a fake captain user
                    fake_discord_id = f"FAKE_{t_num}_{random.randint(100000, 999999)}"
                    fake_user = User(
                        discord_user_id=fake_discord_id,
                        username=t_name.replace(" ", "").lower(),
                        display_name=t_name,
                    )
                    session.add(fake_user)
                    await session.flush()

                    team = Team(
                        organization_id=guild.organization_id,
                        tournament_id=tournament.id,
                        name=t_name,
                        tag=t_name[:3].upper(),
                        captain_id=fake_user.id,
                        seed=t_num,
                    )
                    session.add(team)
                    await session.flush()

                    # Captain as member
                    cap_member = TeamMember(
                        organization_id=guild.organization_id,
                        tournament_id=tournament.id,
                        team_id=team.id,
                        user_id=fake_user.id,
                        role="captain",
                        is_active=True,
                    )
                    session.add(cap_member)

                    # Extra members for team tournaments
                    for m_num in range(2, team_size + 1):
                        m_discord_id = f"FAKE_{t_num}_M{m_num}_{random.randint(1000, 9999)}"
                        m_user = User(
                            discord_user_id=m_discord_id,
                            username=f"player{t_num}m{m_num}",
                            display_name=_rand_ign(game),
                        )
                        session.add(m_user)
                        await session.flush()

                        m_member = TeamMember(
                            organization_id=guild.organization_id,
                            tournament_id=tournament.id,
                            team_id=team.id,
                            user_id=m_user.id,
                            role="member",
                            is_active=True,
                        )
                        session.add(m_member)

                    teams_created.append(t_name)
                    await session.flush()

        embed = discord.Embed(
            title="🌱 Test Data Seeded",
            description=(
                f"Created **{count}** fake {'players' if is_solo else 'teams'} "
                f"for **{tournament.name}**.\n\n"
                "These are test-only entries with fake Discord IDs.\n"
                "You can now:\n"
                "• Generate a bracket (Control Panel → ⚡ Generate Bracket)\n"
                "• Use `/staff simulate` to auto-complete matches\n\n"
                + "\n".join(f"• {n}" for n in teams_created)
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="⚠️ Remove test data before going live: /staff cleanup")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="simulate",
        description="[TEST] Auto-complete all live matches with random scores",
    )
    @app_commands.describe(
        tournament_id="First 8 chars of the tournament ID",
    )
    @app_commands.default_permissions(administrator=True)
    async def simulate(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.match import Match, MatchStatus
        from app.database.models.guild import Guild
        from app.services.match.score_handler import ScoreHandler
        from app.database.repositories.user import UserRepository
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                await interaction.followup.send("Server not registered.", ephemeral=True)
                return

            t_q = select(Tournament).where(
                Tournament.organization_id == guild.organization_id,
                Tournament.deleted_at.is_(None),
            )
            all_t = (await session.execute(t_q)).scalars().all()
            tournament = next(
                (t for t in all_t if t.id.startswith(tournament_id) or t.id[:8] == tournament_id[:8]),
                None,
            )
            if not tournament:
                await interaction.followup.send(f"Tournament `{tournament_id}` not found.", ephemeral=True)
                return

            live_q = select(Match).where(
                Match.tournament_id == tournament.id,
                Match.status.in_([MatchStatus.LIVE, MatchStatus.SCHEDULED, MatchStatus.AWAITING_SCORE]),
                Match.team1_id.isnot(None),
                Match.team2_id.isnot(None),
                Match.deleted_at.is_(None),
            )
            matches = (await session.execute(live_q)).scalars().all()

        if not matches:
            await interaction.followup.send(
                f"No live/scheduled matches found in **{tournament.name}**.\n"
                "Make sure the bracket is generated and matches have teams assigned.",
                ephemeral=True,
            )
            return

        completed = 0
        errors = 0
        results_lines: list[str] = []

        for match in matches:
            try:
                s1 = random.randint(0, 3)
                s2 = random.randint(0, 3)
                while s1 == s2:
                    s2 = random.randint(0, 3)

                winner_id = match.team1_id if s1 > s2 else match.team2_id
                loser_id = match.team2_id if s1 > s2 else match.team1_id

                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        user_repo = UserRepository(session)
                        caller, _ = await user_repo.get_or_create(
                            str(interaction.user.id), interaction.user.name
                        )
                        handler = ScoreHandler(session)
                        await handler.submit_score(
                            match_id=match.id,
                            tournament_id=match.tournament_id,
                            organization_id=match.organization_id,
                            submitted_by=caller.id,
                            score_team1={"score": s1},
                            score_team2={"score": s2},
                            winner_id=winner_id,
                            loser_id=loser_id,
                            is_override=True,
                            override_reason="Staff simulation",
                        )
                completed += 1
                results_lines.append(f"✅ Match {match.id[:6]}: `{s1}–{s2}`")
            except Exception as exc:
                errors += 1
                results_lines.append(f"❌ Match {match.id[:6]}: {exc}")
                logger.warning("Simulate error match %s: %s", match.id[:8], exc)

        embed = discord.Embed(
            title=f"🎲 Simulation Complete — {tournament.name}",
            description="\n".join(results_lines[:20]) or "No results",
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"✅ {completed} completed · ❌ {errors} failed")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="cleanup",
        description="[TEST] Remove all fake/seeded test teams from a tournament",
    )
    @app_commands.describe(tournament_id="First 8 chars of the tournament ID")
    @app_commands.default_permissions(administrator=True)
    async def cleanup(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.team import Team, TeamMember
        from app.database.models.user import User
        from app.database.models.guild import Guild
        from sqlalchemy import select, delete
        from datetime import datetime, timezone

        async with AsyncSessionLocal() as session:
            async with session.begin():
                guild_q = select(Guild).where(
                    Guild.discord_guild_id == str(interaction.guild_id),
                    Guild.deleted_at.is_(None),
                )
                guild = (await session.execute(guild_q)).scalar_one_or_none()
                if not guild:
                    await interaction.followup.send("Server not registered.", ephemeral=True)
                    return

                t_q = select(Tournament).where(
                    Tournament.organization_id == guild.organization_id,
                    Tournament.deleted_at.is_(None),
                )
                all_t = (await session.execute(t_q)).scalars().all()
                tournament = next(
                    (t for t in all_t if t.id.startswith(tournament_id) or t.id[:8] == tournament_id[:8]),
                    None,
                )
                if not tournament:
                    await interaction.followup.send(f"Tournament `{tournament_id}` not found.", ephemeral=True)
                    return

                # Find fake users (discord_user_id starts with "FAKE_")
                users_q = select(User).where(User.discord_user_id.startswith("FAKE_"))
                fake_users = (await session.execute(users_q)).scalars().all()
                fake_user_ids = {u.id for u in fake_users}

                # Soft-delete teams whose captain is a fake user
                teams_q = select(Team).where(
                    Team.tournament_id == tournament.id,
                    Team.captain_id.in_(fake_user_ids),
                    Team.deleted_at.is_(None),
                )
                teams = (await session.execute(teams_q)).scalars().all()
                now = datetime.now(timezone.utc)
                team_ids = {t.id for t in teams}
                for team in teams:
                    team.deleted_at = now

                # Soft-delete team members
                mems_q = select(TeamMember).where(TeamMember.team_id.in_(team_ids))
                mems = (await session.execute(mems_q)).scalars().all()
                for m in mems:
                    m.is_active = False

                count = len(teams)

        await interaction.followup.send(
            embed=discord.Embed(
                title="🧹 Cleanup Complete",
                description=f"Removed **{count}** test teams from **{tournament.name}**.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class AdminCog(commands.Cog, name="admin"):
    """Staff tournament management — seed/simulate/status."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.staff_group = StaffGroup()
        bot.tree.add_command(self.staff_group)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
