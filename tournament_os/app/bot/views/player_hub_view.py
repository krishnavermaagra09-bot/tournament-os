"""
Persistent Player Hub view — posted in 📝-register channel during server setup.

Buttons:
  [📝 Register]           → find open tournament → open RegistrationModal
  [📋 My Status]          → ephemeral registration status
  [📅 View Schedule]      → ephemeral schedule info
  [🏆 View Prize Pool]    → ephemeral prize pool info
  [🎮 My Matches]         → ephemeral match list + Submit Score button
  [👥 My Team]            → ephemeral team composition
  [📊 Standings]          → ephemeral live standings
  [🗺️ Bracket]            → ephemeral bracket view

custom_ids are static strings (no encoded IDs) because this view is not
tied to a specific tournament — it queries the DB at click time.
"""
import logging

import discord

logger = logging.getLogger(__name__)


class PlayerHubView(discord.ui.View):
    """Persistent view — survives bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    # ── Register ──────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="Register",
        style=discord.ButtonStyle.success,
        emoji="📝",
        custom_id="player_hub:register",
    )
    async def register(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament, TournamentStatus
        from app.database.repositories.tournament import TournamentRepository
        from app.services.registration.form_builder import FormBuilderService
        from app.bot.views.registration_modal import RegistrationModal
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                await interaction.response.send_message(
                    embed=error_embed("This server is not registered. Ask an admin to run `/setup tournament`."),
                    ephemeral=True,
                )
                return

            open_q = (
                select(Tournament)
                .where(Tournament.organization_id == guild.organization_id)
                .where(Tournament.status == TournamentStatus.REGISTRATION_OPEN)
                .where(Tournament.deleted_at.is_(None))
            )
            tournaments = (await session.execute(open_q)).scalars().all()

            if not tournaments:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="📝 Registration",
                        description="There are no tournaments open for registration right now.\nCheck back when registration opens!",
                        color=discord.Color.yellow(),
                    ),
                    ephemeral=True,
                )
                return

            if len(tournaments) == 1:
                t = tournaments[0]
                fb = FormBuilderService(session)
                form = await fb.get_active_form(guild.organization_id, t.id)
                fields: list[dict] = []
                if form and form.fields:
                    fields = [
                        {
                            "field_key": f.field_key,
                            "label": f.label,
                            "is_required": f.is_required,
                            "long_text": f.field_type.value == "long_text",
                            "placeholder": getattr(f, "placeholder", ""),
                        }
                        for f in form.fields
                    ]
                else:
                    # ── Auto-generate fields from tournament settings (no manual setup) ──
                    from app.services.registration.auto_form import fields_to_modal_pages
                    pages = fields_to_modal_pages(t)
                    fields = pages[0] if pages else []

                modal = RegistrationModal(tournament_id=t.id, organization_id=guild.organization_id, fields=fields[:5])
                await interaction.response.send_modal(modal)
                return

            options = [
                discord.SelectOption(label=t.name[:100], value=t.id, description=f"{t.game} · {t.format.value.replace('_',' ').title()}")
                for t in tournaments[:25]
            ]
            view = _TournamentPickView(options=options, org_id=guild.organization_id)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="📝 Choose Tournament",
                    description="Multiple tournaments are open. Select one to register:",
                    color=discord.Color.blurple(),
                ),
                view=view,
                ephemeral=True,
            )

    # ── My Status ─────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="My Status",
        style=discord.ButtonStyle.secondary,
        emoji="📋",
        custom_id="player_hub:status",
    )
    async def my_status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.registration import Registration
        from app.database.models.user import User
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                return

            q = (
                select(Registration)
                .join(User, Registration.submitted_by == User.id)
                .where(Registration.organization_id == guild.organization_id)
                .where(User.discord_user_id == str(interaction.user.id))
                .where(Registration.deleted_at.is_(None))
                .order_by(Registration.created_at.desc())
            )
            regs = (await session.execute(q)).scalars().all()

        if not regs:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📋 Your Registrations",
                    description="You haven't registered for any tournaments yet.",
                    color=discord.Color.greyple(),
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 Your Registrations", color=discord.Color.blurple())
        status_emoji = {
            "pending": "⏳", "auto_approved": "✅", "manually_approved": "✅",
            "rejected": "❌", "flagged": "🚩", "hold": "⏸", "changes_requested": "🔄",
        }
        for reg in regs[:5]:
            emoji = status_emoji.get(reg.status.value, "❓")
            embed.add_field(
                name=f"{emoji} {reg.status.value.replace('_', ' ').title()}",
                value=f"ID: `{reg.id[:8]}` • Submitted: {reg.created_at.strftime('%b %d, %Y')}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── View Schedule ─────────────────────────────────────────────────────────

    @discord.ui.button(
        label="Schedule",
        style=discord.ButtonStyle.secondary,
        emoji="📅",
        custom_id="player_hub:schedule",
    )
    async def view_schedule(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament, TournamentStatus
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

            active_q = (
                select(Tournament)
                .where(Tournament.organization_id == guild.organization_id)
                .where(Tournament.status.in_([
                    TournamentStatus.REGISTRATION_OPEN,
                    TournamentStatus.CHECKIN_OPEN,
                    TournamentStatus.LIVE,
                    TournamentStatus.SCHEDULED,
                ]))
                .where(Tournament.deleted_at.is_(None))
            )
            tournaments = (await session.execute(active_q)).scalars().all()

        if not tournaments:
            await interaction.followup.send(
                embed=discord.Embed(title="📅 Schedule", description="No active tournaments at this time.", color=discord.Color.greyple()),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📅 Tournament Schedule", color=discord.Color.blue())
        status_emoji = {"registration_open": "📝", "checkin_open": "✅", "live": "🔴", "scheduled": "📅"}
        for t in tournaments[:5]:
            emoji = status_emoji.get(t.status.value, "⚙️")
            val = f"**Game:** {t.game}\n**Format:** {t.format.value.replace('_', ' ').title()}\n**Status:** {emoji} {t.status.value.replace('_', ' ').title()}"
            if t.match_start_at:
                val += f"\n**Starts:** {t.match_start_at.strftime('%b %d, %Y %I:%M %p')}"
            embed.add_field(name=t.name, value=val, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── View Prize Pool ───────────────────────────────────────────────────────

    @discord.ui.button(
        label="Prize Pool",
        style=discord.ButtonStyle.secondary,
        emoji="💰",
        custom_id="player_hub:prize",
    )
    async def view_prize(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament, TournamentStatus
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

            q = (
                select(Tournament)
                .where(Tournament.organization_id == guild.organization_id)
                .where(Tournament.status.notin_([TournamentStatus.CANCELLED, TournamentStatus.ARCHIVED]))
                .where(Tournament.deleted_at.is_(None))
            )
            tournaments = (await session.execute(q)).scalars().all()

        embed = discord.Embed(title="💰 Prize Pools", color=discord.Color.gold())
        for t in tournaments[:5]:
            embed.add_field(
                name=t.name,
                value=t.prize_pool or "Prize pool to be announced.",
                inline=False,
            )
        if not tournaments:
            embed.description = "No tournament information available."
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── My Matches ────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="My Matches",
        style=discord.ButtonStyle.primary,
        emoji="🎮",
        custom_id="player_hub:matches",
    )
    async def my_matches(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.match import Match, MatchStatus
        from app.database.models.team import Team, TeamMember
        from app.database.models.user import User
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                return

            user_q = select(User).where(User.discord_user_id == str(interaction.user.id)).limit(1)
            caller = (await session.execute(user_q)).scalar_one_or_none()
            if not caller:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🎮 My Matches",
                        description="You don't have any matches yet. Register for a tournament first!",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            # Find teams the user belongs to
            tm_q = (
                select(TeamMember)
                .where(
                    TeamMember.user_id == caller.id,
                    TeamMember.organization_id == guild.organization_id,
                    TeamMember.deleted_at.is_(None),
                )
            )
            memberships = (await session.execute(tm_q)).scalars().all()
            team_ids = [m.team_id for m in memberships]

            if not team_ids:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🎮 My Matches",
                        description="You are not on any team yet.\nRegister for a tournament to get placed on a team.",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            # Fetch live / scheduled matches for those teams
            matches_q = (
                select(Match)
                .where(
                    Match.organization_id == guild.organization_id,
                    Match.status.in_([MatchStatus.LIVE, MatchStatus.SCHEDULED, MatchStatus.AWAITING_SCORE]),
                    Match.deleted_at.is_(None),
                )
                .where(
                    (Match.team1_id.in_(team_ids)) | (Match.team2_id.in_(team_ids))
                )
                .order_by(Match.round.asc(), Match.match_number.asc())
                .limit(10)
            )
            matches = (await session.execute(matches_q)).scalars().all()

            if not matches:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🎮 My Matches",
                        description="No active matches right now.\nCheck back when your next round begins!",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            # Resolve team names
            resolved: list[dict] = []
            for m in matches:
                t1 = await session.get(Team, m.team1_id) if m.team1_id else None
                t2 = await session.get(Team, m.team2_id) if m.team2_id else None
                my_team = None
                for tid in team_ids:
                    if tid == m.team1_id or tid == m.team2_id:
                        my_team = t1 if tid == m.team1_id else t2
                        break
                resolved.append({
                    "match": m,
                    "team1_name": t1.name if t1 else "Team 1",
                    "team2_name": t2.name if t2 else "Team 2",
                    "team1_id": m.team1_id,
                    "team2_id": m.team2_id,
                    "my_team_name": my_team.name if my_team else "Your Team",
                })

        if len(resolved) == 1:
            r = resolved[0]
            m = r["match"]
            embed = _match_info_embed(r)
            view = _MatchActionsView(
                match_id=m.id,
                tournament_id=m.tournament_id,
                organization_id=m.organization_id,
                team1_id=r["team1_id"],
                team2_id=r["team2_id"],
                team1_name=r["team1_name"],
                team2_name=r["team2_name"],
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            options = [
                discord.SelectOption(
                    label=f"R{r['match'].round} #{r['match'].match_number} — {r['team1_name']} vs {r['team2_name']}"[:100],
                    value=r["match"].id,
                    description=f"Status: {r['match'].status.value.replace('_',' ').title()}"[:100],
                )
                for r in resolved[:25]
            ]
            view = _MatchSelectView(resolved_matches=resolved)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🎮 My Matches",
                    description=f"You have **{len(resolved)}** active matches. Select one to view details:",
                    color=discord.Color.blue(),
                ),
                view=view,
                ephemeral=True,
            )

    # ── My Team ───────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="My Team",
        style=discord.ButtonStyle.secondary,
        emoji="👥",
        custom_id="player_hub:team",
    )
    async def my_team(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.team import Team, TeamMember
        from app.database.models.user import User
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                return

            user_q = select(User).where(User.discord_user_id == str(interaction.user.id)).limit(1)
            caller = (await session.execute(user_q)).scalar_one_or_none()
            if not caller:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="👥 My Team",
                        description="You are not registered in any team.\nUse **📝 Register** to join a tournament!",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            # Most recent team membership
            tm_q = (
                select(TeamMember)
                .where(
                    TeamMember.user_id == caller.id,
                    TeamMember.organization_id == guild.organization_id,
                    TeamMember.deleted_at.is_(None),
                )
                .order_by(TeamMember.created_at.desc())
                .limit(1)
            )
            membership = (await session.execute(tm_q)).scalar_one_or_none()
            if not membership:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="👥 My Team",
                        description="You are not on any team yet.\nUse **📝 Register** to sign up!",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            team = await session.get(Team, membership.team_id)
            if not team:
                await interaction.followup.send(embed=error_embed("Team not found."), ephemeral=True)
                return

            # All team members
            members_q = (
                select(TeamMember)
                .where(
                    TeamMember.team_id == team.id,
                    TeamMember.deleted_at.is_(None),
                )
            )
            members = (await session.execute(members_q)).scalars().all()

            # Resolve captain
            captain: User | None = None
            if team.captain_id:
                captain = await session.get(User, team.captain_id)

            embed = discord.Embed(
                title=f"👥 {team.name}",
                color=discord.Color.blue(),
            )
            if team.tag:
                embed.add_field(name="Tag", value=f"`{team.tag}`", inline=True)
            if team.seed is not None:
                embed.add_field(name="Seed", value=f"#{team.seed}", inline=True)
            embed.add_field(name="Members", value=str(len(members)), inline=True)

            member_lines: list[str] = []
            for m in members:
                u = await session.get(User, m.user_id)
                name = u.display_name or u.discord_user_id if u else m.user_id[:8]
                is_cap = (u and captain and u.id == captain.id)
                prefix = "👑 " if is_cap else "• "
                member_lines.append(f"{prefix}**{name}**")

            if member_lines:
                embed.add_field(name="Roster", value="\n".join(member_lines[:20]), inline=False)

            embed.set_footer(text=f"Team ID: {team.id[:8]}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Standings ─────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="Standings",
        style=discord.ButtonStyle.secondary,
        emoji="📊",
        custom_id="player_hub:standings",
    )
    async def standings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament, TournamentStatus
        from app.database.models.standings import Standings
        from app.database.models.team import Team
        from app.bot.helpers.formatters import standings_embed
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

            # Find live tournaments
            live_q = (
                select(Tournament)
                .where(
                    Tournament.organization_id == guild.organization_id,
                    Tournament.status == TournamentStatus.LIVE,
                    Tournament.deleted_at.is_(None),
                )
            )
            live_tournaments = (await session.execute(live_q)).scalars().all()

            if not live_tournaments:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="📊 Standings",
                        description="No live tournament running right now.",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            t = live_tournaments[0]

            sq = (
                select(Standings)
                .where(
                    Standings.tournament_id == t.id,
                    Standings.organization_id == guild.organization_id,
                )
                .order_by(Standings.wins.desc(), Standings.points.desc())
                .limit(15)
            )
            rows = (await session.execute(sq)).scalars().all()

            standings_list = []
            for i, st in enumerate(rows):
                team = await session.get(Team, st.team_id)
                standings_list.append({
                    "rank": i + 1,
                    "team_name": team.name if team else st.team_id[:8],
                    "wins": st.wins,
                    "losses": st.losses,
                    "points": st.points,
                })

        embed = standings_embed(standings_list, t.name)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Bracket ───────────────────────────────────────────────────────────────

    @discord.ui.button(
        label="Bracket",
        style=discord.ButtonStyle.secondary,
        emoji="🗺️",
        custom_id="player_hub:bracket",
    )
    async def bracket(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament, TournamentStatus
        from app.database.models.match import Match, MatchStatus
        from app.database.models.team import Team
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

            live_q = (
                select(Tournament)
                .where(
                    Tournament.organization_id == guild.organization_id,
                    Tournament.status == TournamentStatus.LIVE,
                    Tournament.deleted_at.is_(None),
                )
                .limit(1)
            )
            t = (await session.execute(live_q)).scalar_one_or_none()

            if not t:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🗺️ Bracket",
                        description="No live tournament running right now.",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                return

            mq = (
                select(Match)
                .where(
                    Match.tournament_id == t.id,
                    Match.organization_id == guild.organization_id,
                    Match.deleted_at.is_(None),
                )
                .order_by(Match.round.asc(), Match.match_number.asc())
            )
            matches = (await session.execute(mq)).scalars().all()

            # Group by round
            rounds: dict[int, list] = {}
            for m in matches:
                r = m.round or 0
                rounds.setdefault(r, []).append(m)

            embed = discord.Embed(
                title=f"🗺️ Bracket — {t.name}",
                color=discord.Color.blurple(),
            )

            status_icons = {
                "live": "🔴",
                "completed": "✅",
                "scheduled": "📅",
                "awaiting_score": "⏳",
                "protested": "⚖️",
                "under_review": "🔍",
                "voided": "🚫",
                "rescheduled": "🔄",
            }

            for rnd in sorted(rounds.keys())[:6]:  # max 6 rounds shown
                round_matches = rounds[rnd]
                lines: list[str] = []
                for m in round_matches[:8]:
                    t1 = await session.get(Team, m.team1_id) if m.team1_id else None
                    t2 = await session.get(Team, m.team2_id) if m.team2_id else None
                    t1_name = (t1.name if t1 else "TBD")[:20]
                    t2_name = (t2.name if t2 else "TBD")[:20]
                    icon = status_icons.get(m.status.value, "❓")

                    if m.status == MatchStatus.COMPLETED and m.winner_id:
                        winner = t1 if m.winner_id == m.team1_id else t2
                        w_name = winner.name if winner else "?"
                        lines.append(f"{icon} **{t1_name}** vs **{t2_name}** → 🏆 {w_name}")
                    elif m.score_team1 and m.score_team2:
                        s1 = m.score_team1.get("score", 0) if isinstance(m.score_team1, dict) else (m.score_team1 or 0)
                        s2 = m.score_team2.get("score", 0) if isinstance(m.score_team2, dict) else (m.score_team2 or 0)
                        lines.append(f"{icon} **{t1_name}** `{s1}-{s2}` **{t2_name}**")
                    else:
                        lines.append(f"{icon} **{t1_name}** vs **{t2_name}**")

                if lines:
                    embed.add_field(
                        name=f"Round {rnd}",
                        value="\n".join(lines),
                        inline=False,
                    )

            if not rounds:
                embed.description = "Bracket not yet generated."

            embed.set_footer(text="✅ Complete · 🔴 Live · ⏳ Awaiting Score · 📅 Scheduled")

        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Helper: match info embed ───────────────────────────────────────────────────

def _match_info_embed(r: dict) -> discord.Embed:
    m = r["match"]
    status_map = {
        "live": "🔴 Live",
        "scheduled": "📅 Scheduled",
        "awaiting_score": "⏳ Awaiting Score",
        "completed": "✅ Completed",
        "disputed": "⚖️ Disputed",
    }
    embed = discord.Embed(
        title=f"🎮 Round {m.round} · Match #{m.match_number}",
        color=discord.Color.red() if m.status.value == "live" else discord.Color.blue(),
    )
    embed.add_field(name="🔵 " + r["team1_name"], value="​", inline=True)
    embed.add_field(name="⚔️", value="**vs**", inline=True)
    embed.add_field(name="🔴 " + r["team2_name"], value="​", inline=True)
    embed.add_field(name="Status", value=status_map.get(m.status.value, m.status.value), inline=True)
    if m.score_team1 is not None and m.score_team2 is not None:
        embed.add_field(name="Score", value=f"`{m.score_team1} — {m.score_team2}`", inline=True)
    if m.private_channel_id:
        embed.add_field(name="Match Channel", value=f"<#{m.private_channel_id}>", inline=False)
    embed.set_footer(text=f"Match ID: {m.id[:8]}")
    return embed


# ── Action view: submit score for a specific match ────────────────────────────

class _MatchActionsView(discord.ui.View):
    def __init__(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        team1_id: str,
        team2_id: str,
        team1_name: str,
        team2_name: str,
    ) -> None:
        super().__init__(timeout=120)
        self.match_id = match_id
        self.tournament_id = tournament_id
        self.organization_id = organization_id
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.team1_name = team1_name
        self.team2_name = team2_name

    @discord.ui.button(label="Submit Score", emoji="📝", style=discord.ButtonStyle.primary)
    async def submit_score(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from app.bot.views.score_modal import ScoreModal
        modal = ScoreModal(
            match_id=self.match_id,
            tournament_id=self.tournament_id,
            organization_id=self.organization_id,
            team1_id=self.team1_id,
            team2_id=self.team2_id,
        )
        await interaction.response.send_modal(modal)


# ── Select menu: pick a match to view ─────────────────────────────────────────

class _MatchSelectView(discord.ui.View):
    def __init__(self, resolved_matches: list[dict]) -> None:
        super().__init__(timeout=60)
        self._resolved = {r["match"].id: r for r in resolved_matches}

        options = [
            discord.SelectOption(
                label=f"R{r['match'].round} #{r['match'].match_number} — {r['team1_name']} vs {r['team2_name']}"[:100],
                value=r["match"].id,
                description=f"Status: {r['match'].status.value.replace('_',' ').title()}"[:100],
            )
            for r in resolved_matches[:25]
        ]
        sel = discord.ui.Select(placeholder="Select a match…", options=options)
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        match_id = interaction.data["values"][0]
        r = self._resolved.get(match_id)
        if not r:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return
        m = r["match"]
        embed = _match_info_embed(r)
        view = _MatchActionsView(
            match_id=m.id,
            tournament_id=m.tournament_id,
            organization_id=m.organization_id,
            team1_id=r["team1_id"],
            team2_id=r["team2_id"],
            team1_name=r["team1_name"],
            team2_name=r["team2_name"],
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ── Tournament pick view (for registration with multiple open tournaments) ─────

class _TournamentPickView(discord.ui.View):
    """Ephemeral select when multiple tournaments are open."""

    def __init__(self, options: list[discord.SelectOption], org_id: str) -> None:
        super().__init__(timeout=60)
        self.org_id = org_id
        sel = discord.ui.Select(placeholder="Select a tournament…", options=options)
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        tournament_id = interaction.data["values"][0]
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.services.registration.form_builder import FormBuilderService
        from app.services.registration.auto_form import fields_to_modal_pages
        from app.bot.views.registration_modal import RegistrationModal

        async with AsyncSessionLocal() as session:
            tournament = await session.get(Tournament, tournament_id)
            fb = FormBuilderService(session)
            form = await fb.get_active_form(self.org_id, tournament_id)
            fields: list[dict] = []
            if form and form.fields:
                fields = [
                    {"field_key": f.field_key, "label": f.label, "is_required": f.is_required,
                     "long_text": f.field_type.value == "long_text", "placeholder": getattr(f, "placeholder", "")}
                    for f in form.fields
                ]
            elif tournament:
                pages = fields_to_modal_pages(tournament)
                fields = pages[0] if pages else []
            else:
                fields = [{"field_key": "in_game_name", "label": "In-Game Name", "is_required": True, "long_text": False, "placeholder": "Your IGN"}]

        await interaction.response.send_modal(
            RegistrationModal(tournament_id=tournament_id, organization_id=self.org_id, fields=fields[:5])
        )
