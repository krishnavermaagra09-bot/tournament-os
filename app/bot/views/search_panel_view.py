"""
Search Panel — tournament, team, and match search via buttons + modals.
Accessible from the Control Panel and the Player Hub.
"""
import logging
import discord

logger = logging.getLogger(__name__)


# ── Modals ────────────────────────────────────────────────────────────────────

class _TournamentSearchModal(discord.ui.Modal, title="🔍 Search Tournaments"):
    query = discord.ui.TextInput(label="Name or game to search", min_length=1, max_length=100)

    def __init__(self, org_id: str):
        super().__init__()
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from sqlalchemy import select, or_, func

        q_str = self.query.value.strip()
        pattern = f"%{q_str.lower()}%"

        async with AsyncSessionLocal() as session:
            q = (
                select(Tournament)
                .where(
                    Tournament.organization_id == self._org_id,
                    Tournament.deleted_at.is_(None),
                    or_(
                        func.lower(Tournament.name).like(pattern),
                        func.lower(Tournament.game).like(pattern),
                    ),
                )
                .order_by(Tournament.created_at.desc())
                .limit(10)
            )
            results = list((await session.execute(q)).scalars().all())

        if not results:
            await interaction.followup.send(
                embed=discord.Embed(title="🔍 No Results", description=f"No tournaments matching `{q_str}`.", color=discord.Color.light_grey()),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title=f"🔍 Tournaments — '{q_str}'", color=discord.Color.blurple())
        _STATUS_ICON = {"registration_open": "📝", "checkin_open": "✅", "live": "🔴", "completed": "🏆"}
        for t in results:
            icon = _STATUS_ICON.get(t.status.value if t.status else "", "📅")
            embed.add_field(
                name=f"{icon} {t.name}",
                value=(
                    f"Game: **{t.game or 'N/A'}** | Format: **{t.format.value.replace('_',' ').title() if t.format else 'N/A'}**\n"
                    f"Status: `{t.status.value if t.status else 'unknown'}` | ID: `{t.id[:8]}`"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


class _TeamSearchModal(discord.ui.Modal, title="👥 Search Teams"):
    tournament_id = discord.ui.TextInput(label="Tournament ID (first 8 chars is fine)", min_length=4, max_length=36)
    team_name     = discord.ui.TextInput(label="Team name (blank = find your own team)", required=False)

    def __init__(self, org_id: str):
        super().__init__()
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.team import Team, TeamMember
        from app.database.models.user import User
        from app.database.repositories.tournament import TournamentRepository
        from sqlalchemy import select, func

        t_raw  = self.tournament_id.value.strip()
        n_raw  = (self.team_name.value or "").strip()

        async with AsyncSessionLocal() as session:
            t_repo = TournamentRepository(session)
            tq = (
                select(type(None))  # placeholder
            )
            from app.database.models.tournament import Tournament
            tq2 = select(Tournament).where(
                Tournament.organization_id == self._org_id,
                Tournament.deleted_at.is_(None),
                (Tournament.id == t_raw) | Tournament.id.startswith(t_raw),
            ).limit(1)
            tournament = (await session.execute(tq2)).scalar_one_or_none()
            if not tournament:
                await interaction.followup.send(embed=discord.Embed(title="❌ Not Found", description="Tournament not found.", color=discord.Color.red()), ephemeral=True)
                return

            if n_raw:
                pattern = f"%{n_raw.lower()}%"
                q = select(Team).where(
                    Team.organization_id == self._org_id,
                    Team.tournament_id   == tournament.id,
                    Team.deleted_at.is_(None),
                    func.lower(Team.name).like(pattern),
                ).limit(10)
                teams = list((await session.execute(q)).scalars().all())
            else:
                user_q = select(User).where(
                    User.discord_user_id == str(interaction.user.id),
                    User.deleted_at.is_(None),
                )
                user = (await session.execute(user_q)).scalar_one_or_none()
                if not user:
                    await interaction.followup.send(embed=discord.Embed(title="Not Registered", description="You are not registered.", color=discord.Color.light_grey()), ephemeral=True)
                    return
                member_q = select(TeamMember).where(
                    TeamMember.user_id       == user.id,
                    TeamMember.tournament_id == tournament.id,
                    TeamMember.is_active.is_(True),
                )
                member = (await session.execute(member_q)).scalar_one_or_none()
                if not member:
                    await interaction.followup.send(embed=discord.Embed(title="No Team", description="You are not on a team in this tournament.", color=discord.Color.light_grey()), ephemeral=True)
                    return
                team = await session.get(Team, member.team_id)
                teams = [team] if team else []

        if not teams:
            await interaction.followup.send(embed=discord.Embed(title="🔍 No Teams Found", description="No teams matched your search.", color=discord.Color.light_grey()), ephemeral=True)
            return

        embed = discord.Embed(title=f"👥 Teams — {tournament.name}", color=discord.Color.blue())
        for team in teams:
            icon = "✅" if team.checkin_status == "checked_in" else "⏳"
            embed.add_field(
                name=f"{icon} {team.name}" + (f" [{team.tag}]" if team.tag else ""),
                value=f"Check-in: `{team.checkin_status}` | Seed: `{team.seed or 'N/A'}` | ID: `{team.id[:8]}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


class _MatchSearchModal(discord.ui.Modal, title="🎮 Search Matches"):
    tournament_id = discord.ui.TextInput(label="Tournament ID (first 8 chars is fine)", min_length=4, max_length=36)
    round_num     = discord.ui.TextInput(label="Round number (blank = all open matches)", required=False)

    def __init__(self, org_id: str):
        super().__init__()
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match, MatchStatus
        from app.database.models.team import Team
        from app.database.models.tournament import Tournament
        from sqlalchemy import select

        t_raw = self.tournament_id.value.strip()
        r_raw = (self.round_num.value or "").strip()
        round_n: int | None = int(r_raw) if r_raw.isdigit() else None

        async with AsyncSessionLocal() as session:
            tq = select(Tournament).where(
                Tournament.organization_id == self._org_id,
                Tournament.deleted_at.is_(None),
                (Tournament.id == t_raw) | Tournament.id.startswith(t_raw),
            ).limit(1)
            tournament = (await session.execute(tq)).scalar_one_or_none()
            if not tournament:
                await interaction.followup.send(embed=discord.Embed(title="❌ Not Found", description="Tournament not found.", color=discord.Color.red()), ephemeral=True)
                return

            mq = select(Match).where(
                Match.organization_id == self._org_id,
                Match.tournament_id   == tournament.id,
                Match.deleted_at.is_(None),
            ).order_by(Match.round, Match.created_at).limit(15)
            if round_n is not None:
                mq = mq.where(Match.round == round_n)
            else:
                mq = mq.where(Match.status.in_(["pending", "in_progress", "protested"]))
            matches = list((await session.execute(mq)).scalars().all())

            team_ids = {m.team1_id for m in matches} | {m.team2_id for m in matches}
            team_ids.discard(None)
            team_map: dict[str, str] = {}
            if team_ids:
                t_q = select(Team).where(Team.id.in_(team_ids))
                for team in (await session.execute(t_q)).scalars().all():
                    team_map[team.id] = team.name

        if not matches:
            desc = f"Round {round_n}" if round_n else "any open round"
            await interaction.followup.send(embed=discord.Embed(title="🔍 No Matches", description=f"No matches in {desc} for **{tournament.name}**.", color=discord.Color.light_grey()), ephemeral=True)
            return

        embed = discord.Embed(title=f"🎮 Matches — {tournament.name}", color=discord.Color.blue())
        _STATUS_ICONS = {"pending": "⏳", "in_progress": "🔴", "completed": "✅", "protested": "⚠️", "bye": "⏭️", "cancelled": "❌"}
        for m in matches:
            t1   = team_map.get(m.team1_id or "", "TBD")
            t2   = team_map.get(m.team2_id or "", "TBD")
            icon = _STATUS_ICONS.get(m.status.value if m.status else "pending", "❓")
            score = ""
            if m.score_team1 and m.score_team2:
                score = f" | **{m.score_team1.get('score','?')} – {m.score_team2.get('score','?')}**"
            embed.add_field(
                name=f"{icon} R{m.round}: {t1} vs {t2}{score}",
                value=f"Status: `{m.status.value if m.status else 'pending'}` | ID: `{m.id[:8]}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Main View ─────────────────────────────────────────────────────────────────

class SearchPanelView(discord.ui.View):
    """Search sub-panel — works for both staff (control panel) and players (player hub)."""

    def __init__(self, org_id: str):
        super().__init__(timeout=120)
        self.org_id = org_id

    @discord.ui.button(label="📅 Find Tournament", style=discord.ButtonStyle.primary, row=0)
    async def search_tournament(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_TournamentSearchModal(self.org_id))

    @discord.ui.button(label="👥 Find Team", style=discord.ButtonStyle.primary, row=0)
    async def search_team(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_TeamSearchModal(self.org_id))

    @discord.ui.button(label="🎮 Find Matches", style=discord.ButtonStyle.primary, row=0)
    async def search_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_MatchSearchModal(self.org_id))
