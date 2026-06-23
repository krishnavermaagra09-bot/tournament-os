"""
Tournament Control Panel — persistent embed + buttons posted in ⚙️-{tournament} channel.

Buttons (persistent, custom_ids encode tournament_id):
  [📋 Registration] [👥 Teams]    [✅ Check-In]   [🎮 Matches]
  [🏆 Bracket]      [📊 Analytics] [⚖️ Disputes]   [📢 Announce]
  [📝 Reg Fields]   [🔄 Change Status]

Each section button opens an ephemeral sub-panel.
custom_id format: "cp_{section}:{tournament_id}"   e.g. "cp_reg:550e8400…"
Max: 10+36 = 46 chars ✓
"""
import logging
import re

import discord

logger = logging.getLogger(__name__)

_SECTIONS = {
    "cp_reg":      ("📋 Registration", discord.ButtonStyle.primary),
    "cp_teams":    ("👥 Teams",         discord.ButtonStyle.primary),
    "cp_checkin":  ("✅ Check-In",      discord.ButtonStyle.primary),
    "cp_matches":  ("🎮 Matches",       discord.ButtonStyle.primary),
    "cp_bracket":  ("🏆 Bracket",       discord.ButtonStyle.secondary),
    "cp_analytics":("📊 Analytics",     discord.ButtonStyle.secondary),
    "cp_disputes": ("⚖️ Disputes",      discord.ButtonStyle.danger),
    "cp_announce": ("📢 Announce",      discord.ButtonStyle.secondary),
    "cp_fields":   ("📝 Reg Fields",    discord.ButtonStyle.primary),
    "cp_status":   ("🔄 Change Status", discord.ButtonStyle.success),
    "cp_audit":    ("📜 Audit Trail",   discord.ButtonStyle.secondary),
    "cp_snap":     ("📸 Snapshots",     discord.ButtonStyle.secondary),
    "cp_override": ("🛠️ Overrides",    discord.ButtonStyle.danger),
    "cp_settings": ("⚙️ Settings",      discord.ButtonStyle.secondary),
    "cp_search":   ("🔍 Search",        discord.ButtonStyle.primary),
}


def _cid(section: str, t_id: str) -> str:
    return f"{section}:{t_id}"


class ControlPanelView(discord.ui.View):
    """Persistent view — survives bot restarts."""

    def __init__(self, tournament_id: str, org_id: str) -> None:
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.org_id = org_id

        for section, (label, style) in _SECTIONS.items():
            btn = discord.ui.Button(
                label=label,
                style=style,
                custom_id=_cid(section, tournament_id),
            )
            btn.callback = self._dispatch
            self.add_item(btn)

    async def _dispatch(self, interaction: discord.Interaction) -> None:
        custom_id: str = interaction.data.get("custom_id", "")
        if ":" not in custom_id:
            return
        section, t_id = custom_id.rsplit(":", 1)

        handlers = {
            "cp_reg":      _panel_registration,
            "cp_teams":    _panel_teams,
            "cp_checkin":  _panel_checkin,
            "cp_matches":  _panel_matches,
            "cp_bracket":  _panel_bracket,
            "cp_analytics":_panel_analytics,
            "cp_disputes": _panel_disputes,
            "cp_announce": _panel_announce,
            "cp_fields":   _panel_fields,
            "cp_status":   _panel_status,
            "cp_audit":    _panel_audit,
            "cp_snap":     _panel_snapshots,
            "cp_override": _panel_overrides,
            "cp_settings": _panel_settings,
            "cp_search":   _panel_search,
        }
        handler = handlers.get(section)
        if handler:
            await handler(interaction, t_id)
        else:
            await interaction.response.send_message("Unknown section.", ephemeral=True)


# ── Sub-panels ────────────────────────────────────────────────────────────────

async def _get_tournament(session, t_id: str, guild_id: int):
    from app.database.models.guild import Guild
    from app.database.repositories.tournament import TournamentRepository
    from sqlalchemy import select

    guild_q = select(Guild).where(
        Guild.discord_guild_id == str(guild_id),
        Guild.deleted_at.is_(None),
    )
    guild = (await session.execute(guild_q)).scalar_one_or_none()
    if not guild:
        return None, None
    t_repo = TournamentRepository(session)
    t = await t_repo.get_by_id(t_id, guild.organization_id)
    return guild, t


async def _panel_registration(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.repositories.registration import RegistrationRepository

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        repo = RegistrationRepository(session)
        regs = await repo.list_by_tournament(t.organization_id, t.id)

    counts: dict[str, int] = {}
    for r in regs:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1

    e = discord.Embed(title=f"📋 Registrations — {t.name}", color=discord.Color.blurple())
    e.add_field(name="Total",    value=str(len(regs)), inline=True)
    e.add_field(name="✅ Approved", value=str(counts.get("manually_approved", 0) + counts.get("auto_approved", 0)), inline=True)
    e.add_field(name="⏳ Pending", value=str(counts.get("pending", 0)), inline=True)
    e.add_field(name="🚩 Flagged", value=str(counts.get("flagged", 0)), inline=True)
    e.add_field(name="❌ Rejected",value=str(counts.get("rejected", 0)), inline=True)
    e.add_field(name="⏸ Hold",    value=str(counts.get("hold", 0)), inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)


async def _panel_teams(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.models.team import Team
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return

        q = select(Team).where(
            Team.tournament_id == t.id,
            Team.organization_id == t.organization_id,
            Team.deleted_at.is_(None),
        )
        teams = (await session.execute(q)).scalars().all()

    e = discord.Embed(title=f"👥 Teams — {t.name}", color=discord.Color.blue())
    e.add_field(name="Total Teams", value=str(len(teams)), inline=True)
    e.add_field(name="Max Teams",   value=str(t.max_teams or "Unlimited"), inline=True)
    if teams:
        team_list = "\n".join(f"• {tm.name}" for tm in teams[:20])
        e.add_field(name="Teams", value=team_list or "None yet", inline=False)
    else:
        e.description = "No teams yet. Approve registrations to create teams."
    await interaction.followup.send(embed=e, ephemeral=True)


async def _panel_checkin(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.services.analytics.aggregator import AnalyticsAggregator

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        agg = AnalyticsAggregator(session)
        data = await agg.tournament_summary(t.organization_id, t.id)

    teams = data.get("teams", {})
    e = discord.Embed(title=f"✅ Check-In — {t.name}", color=discord.Color.green())
    e.add_field(name="Total Teams",   value=str(teams.get("total", 0)), inline=True)
    e.add_field(name="Checked In",    value=str(teams.get("checked_in", 0)), inline=True)
    e.add_field(name="Check-In Rate", value=f"{teams.get('checkin_rate', 0)}%", inline=True)

    view = _CheckInActionsView(t_id, t.organization_id)
    await interaction.followup.send(embed=e, view=view, ephemeral=True)


async def _panel_matches(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.services.analytics.aggregator import AnalyticsAggregator

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        agg = AnalyticsAggregator(session)
        data = await agg.tournament_summary(t.organization_id, t.id)

    matches = data.get("matches", {})
    e = discord.Embed(title=f"🎮 Matches — {t.name}", color=discord.Color.blue())
    e.add_field(name="Total",     value=str(matches.get("total", 0)), inline=True)
    e.add_field(name="Completed", value=str(matches.get("completed", 0)), inline=True)
    e.add_field(name="🔴 Live",   value=str(matches.get("live", 0)), inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)


async def _panel_bracket(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.models.staff import StaffRole
    from app.bot.helpers.permissions import has_permission

    async with AsyncSessionLocal() as session:
        if not await has_permission(session, interaction.user, str(interaction.guild_id), StaffRole.TOURNAMENT_ADMIN):
            await interaction.followup.send("❌ Insufficient permissions.", ephemeral=True)
            return
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return

    e = discord.Embed(
        title=f"🏆 Bracket — {t.name}",
        description="Use the button below to generate the bracket.\n\n⚠️ **Warning:** This action cannot be undone. Make sure all teams are confirmed.",
        color=discord.Color.gold(),
    )
    view = _BracketActionsView(t_id, t.organization_id)
    await interaction.followup.send(embed=e, view=view, ephemeral=True)


async def _panel_analytics(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.services.analytics.aggregator import AnalyticsAggregator

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        agg = AnalyticsAggregator(session)
        data = await agg.tournament_summary(t.organization_id, t.id)

    reg  = data.get("registrations", {})
    teams = data.get("teams", {})
    matches = data.get("matches", {})
    disputes = data.get("disputes", {})

    e = discord.Embed(title=f"📊 Analytics — {t.name}", color=discord.Color.gold())
    e.add_field(name="Registrations", value=f"Total: **{reg.get('total',0)}** | ✅ {reg.get('approved',0)} | ⏳ {reg.get('pending',0)} | 🚩 {reg.get('flagged',0)}", inline=False)
    e.add_field(name="Teams",         value=f"Total: **{teams.get('total',0)}** | Checked In: {teams.get('checked_in',0)} ({teams.get('checkin_rate',0)}%)", inline=False)
    e.add_field(name="Matches",       value=f"Total: **{matches.get('total',0)}** | Done: {matches.get('completed',0)} | 🔴 Live: {matches.get('live',0)}", inline=False)
    e.add_field(name="Open Disputes", value=str(disputes.get("total", 0)), inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)


async def _panel_disputes(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.repositories.dispute import DisputeRepository

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        repo = DisputeRepository(session)
        disputes = await repo.list_open(t.organization_id, t.id)

    e = discord.Embed(title=f"⚖️ Open Disputes — {t.name}", color=discord.Color.orange())
    if not disputes:
        e.description = "✅ No open disputes!"
    else:
        for d in disputes[:10]:
            e.add_field(
                name=f"`{d.id[:8]}` — {d.case_type.value.replace('_',' ').title()}",
                value=f"Status: {d.status.value} | {d.description[:80]}",
                inline=False,
            )
    await interaction.followup.send(embed=e, ephemeral=True)


async def _panel_announce(interaction: discord.Interaction, t_id: str) -> None:
    await interaction.response.send_modal(_AnnouncementModal(t_id))


async def _panel_fields(interaction: discord.Interaction, t_id: str) -> None:
    """Show current registration fields + buttons to add/reset."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.services.registration.form_builder import FormBuilderService

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return

        fb = FormBuilderService(session)
        form = await fb.get_active_form(t.organization_id, t.id)
        fields = list(form.fields) if (form and form.fields) else []
        t_name = t.name
        org_id = t.organization_id

    e = discord.Embed(
        title=f"📝 Registration Fields — {t_name}",
        color=discord.Color.blurple(),
    )
    if fields:
        for i, f in enumerate(fields, 1):
            req = "✅ Required" if f.is_required else "⬜ Optional"
            e.add_field(
                name=f"{i}. {f.label}",
                value=f"`{f.field_key}` | {f.field_type.value} | {req}",
                inline=False,
            )
        e.set_footer(text=f"{len(fields)}/5 fields configured (Discord modal limit: 5)")
    else:
        e.description = (
            "No custom fields configured yet.\n"
            "Players will only see the default **In-Game Name** field.\n\n"
            "Add up to 5 fields using the button below."
        )

    view = _FieldManageView(t_id, org_id)
    await interaction.followup.send(embed=e, view=view, ephemeral=True)


async def _panel_audit(interaction: discord.Interaction, t_id: str) -> None:
    """Show recent audit events for this tournament."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.repositories.audit import AuditRepository

    _ACTION_ICONS: dict[str, str] = {
        "tournament.status_changed": "🔄",
        "team.disqualified":         "🚫",
        "match.override_winner":     "⚔️",
        "bracket.advanced":          "⏩",
        "noshow.processed":          "👻",
        "registration.approved":     "✅",
        "registration.rejected":     "❌",
        "registration.flagged":      "🚩",
        "score.submitted":           "📝",
        "score.override":            "⚠️",
        "snapshot.created":          "📸",
    }

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        audit_repo = AuditRepository(session)
        entries = await audit_repo.list_for_tournament(t.organization_id, t.id, limit=15)

    embed = discord.Embed(
        title=f"📜 Audit Trail — {t.name}",
        color=discord.Color.blurple(),
        description=f"Last **{len(entries)}** events (newest first)" if entries else "No events recorded yet.",
    )
    lines = []
    for entry in entries:
        icon = _ACTION_ICONS.get(entry.action, "📋")
        ts = f"<t:{int(entry.created_at.timestamp())}:R>" if entry.created_at else ""
        action_label = entry.action.replace(".", " › ").replace("_", " ").title()
        detail = ""
        if entry.payload:
            if "old_status" in entry.payload and "new_status" in entry.payload:
                detail = f" `{entry.payload['old_status']}→{entry.payload['new_status']}`"
            elif "reason" in entry.payload:
                detail = f" — {entry.payload['reason'][:30]}"
        actor = f"`{entry.actor_type or 'system'}`"
        lines.append(f"{icon} {ts} **{action_label}**{detail} by {actor}")

    if lines:
        embed.description = "\n".join(lines)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def _panel_snapshots(interaction: discord.Interaction, t_id: str) -> None:
    """Show available snapshots for this tournament."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.models.snapshot import TournamentSnapshot
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        snap_q = (
            select(TournamentSnapshot)
            .where(TournamentSnapshot.tournament_id == t.id)
            .order_by(TournamentSnapshot.created_at.desc())
            .limit(10)
        )
        snapshots = (await session.execute(snap_q)).scalars().all()

    embed = discord.Embed(title=f"📸 Snapshots — {t.name}", color=discord.Color.blurple())
    if not snapshots:
        embed.description = "No snapshots yet. Auto-taken at key lifecycle events.\nUse **🛠️ Overrides → 📸 Take Snapshot** to create one."
    else:
        for snap in snapshots:
            ts = f"<t:{int(snap.created_at.timestamp())}:f>" if snap.created_at else "unknown"
            embed.add_field(
                name=f"📸 `{snap.id[:8]}` — {snap.label or snap.trigger or 'snapshot'}",
                value=f"Taken: {ts}  •  Trigger: `{snap.trigger}`",
                inline=False,
            )
    await interaction.followup.send(embed=embed, ephemeral=True)


async def _panel_status(interaction: discord.Interaction, t_id: str) -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.tournament import VALID_TRANSITIONS
    from app.bot.views.tournament_manage_view import _StatusSelectView, _STATUS_EMOJI

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.response.send_message("Tournament not found.", ephemeral=True)
            return
        t_settings = dict(t.channel_config or {})
        current = t.status
        t_name = t.name
        t_fmt = t.format.value

    valid = VALID_TRANSITIONS.get(current, [])
    if not valid:
        await interaction.response.send_message(f"No valid transitions from **{current.value}**.", ephemeral=True)
        return

    options = [
        discord.SelectOption(
            label=s.value.replace("_", " ").title(),
            value=s.value,
            emoji=_STATUS_EMOJI.get(s.value, "⚙️"),
        )
        for s in valid
    ]
    view = _StatusSelectView(
        tournament_id=t_id,
        org_id=guild.organization_id if guild else "",
        t_name=t_name,
        t_fmt=t_fmt,
        t_settings=t_settings,
        options=options,
        bot=interaction.client,
    )
    e = discord.Embed(
        title="🔄 Change Status",
        description=f"**{t_name}** is currently **{current.value.replace('_',' ').title()}**.\nSelect a new status:",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=e, view=view, ephemeral=True)


# ── Action sub-views ──────────────────────────────────────────────────────────

class _CheckInActionsView(discord.ui.View):
    def __init__(self, t_id: str, org_id: str) -> None:
        super().__init__(timeout=60)
        self.t_id = t_id
        self.org_id = org_id

    @discord.ui.button(label="📢 Post Check-In Button", style=discord.ButtonStyle.success)
    async def post_checkin(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.bot.views.checkin_button import CheckInView

        async with AsyncSessionLocal() as session:
            t = await session.get(Tournament, self.t_id)
            t_settings = dict(t.channel_config or {}) if t else {}

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            g_q = select(Guild).where(Guild.discord_guild_id == str(guild.id), Guild.deleted_at.is_(None))
            g = (await session.execute(g_q)).scalar_one_or_none()
            channel_ids: dict = (g.settings or {}).get("channel_ids", {}) if g else {}

        ch_id = channel_ids.get("check_in") or t_settings.get("registration_channel_id")
        ch = guild.get_channel(int(ch_id)) if ch_id else interaction.channel

        if not isinstance(ch, discord.TextChannel):
            ch = interaction.channel

        view = CheckInView(tournament_id=self.t_id, organization_id=self.org_id)
        interaction.client.add_view(view)
        e = discord.Embed(title="✅ Check-In Open!", description="Click the button below to check in.", color=discord.Color.green())
        await ch.send(embed=e, view=view)
        await interaction.followup.send(f"✅ Check-in button posted in {ch.mention}", ephemeral=True)


class _BracketActionsView(discord.ui.View):
    def __init__(self, t_id: str, org_id: str) -> None:
        super().__init__(timeout=60)
        self.t_id = t_id
        self.org_id = org_id

    @discord.ui.button(label="⚡ Generate Bracket", style=discord.ButtonStyle.success)
    async def generate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.repositories.tournament import TournamentRepository
        from app.services.bracket.generator import BracketGenerator
        from app.bot.helpers.formatters import error_embed

        bracket = None
        t_name = ""
        t_fmt = ""
        match_count = 0

        async with AsyncSessionLocal() as session:
            async with session.begin():
                t_repo = TournamentRepository(session)
                t = await t_repo.get_by_id(self.t_id, self.org_id)
                if not t:
                    await interaction.followup.send(embed=error_embed("Tournament not found."), ephemeral=True)
                    return
                gen = BracketGenerator(session)
                try:
                    bracket = await gen.generate(self.org_id, t.id, t.format)
                    t_name = t.name
                    t_fmt = t.format.value.replace("_", " ").title()
                except ValueError as exc:
                    await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
                    return

        if not bracket:
            return

        # ── Create match channels for Round 1 ────────────────────────────────
        from app.services.notification.discord_delivery import get_bot
        bot = get_bot()
        channels_created = 0

        if bot:
            try:
                from app.database.session import AsyncSessionLocal
                from app.database.models.match import Match, MatchStatus
                from app.database.models.team import Team
                from app.database.models.guild import Guild
                from app.database.models.tournament import Tournament
                from app.services.match.channel_manager import MatchChannelManager
                from app.bot.helpers.formatters import score_prompt_embed
                from app.bot.views.match_channel_view import MatchScoreButtonView
                from sqlalchemy import select

                async with AsyncSessionLocal() as session:
                    # Fetch round-1 matches from the bracket
                    r1_q = (
                        select(Match)
                        .where(
                            Match.tournament_id == self.t_id,
                            Match.organization_id == self.org_id,
                            Match.round == 1,
                            Match.status != MatchStatus.COMPLETED,
                            Match.deleted_at.is_(None),
                        )
                    )
                    r1_matches = (await session.execute(r1_q)).scalars().all()
                    match_count = len(r1_matches)

                    # Get guild + tournament config
                    guild_q = select(Guild).where(
                        Guild.organization_id == self.org_id,
                        Guild.deleted_at.is_(None),
                    ).limit(1)
                    guild_row = (await session.execute(guild_q)).scalar_one_or_none()
                    tournament = await session.get(Tournament, self.t_id)

                    if guild_row and tournament:
                        tc = dict(tournament.channel_config or {})
                        gs = dict(guild_row.settings or {})
                        staff_role_ids = gs.get("staff_role_ids", {})
                        t_cat_id = tc.get("tournament_category_id")
                        discord_guild_id = guild_row.discord_guild_id

                for match in r1_matches:
                    try:
                        async with AsyncSessionLocal() as session:
                            async with session.begin():
                                team1 = await session.get(Team, match.team1_id) if match.team1_id else None
                                team2 = await session.get(Team, match.team2_id) if match.team2_id else None
                                t1_name = team1.name if team1 else "Team 1"
                                t2_name = team2.name if team2 else "Team 2"
                                t1_role = str(team1.discord_role_id) if (team1 and getattr(team1, "discord_role_id", None)) else None
                                t2_role = str(team2.discord_role_id) if (team2 and getattr(team2, "discord_role_id", None)) else None

                                m = await session.get(Match, match.id)
                                if not m or m.private_channel_id:
                                    continue

                                mgr = MatchChannelManager(session)
                                ch_id = await mgr.create_match_channel(
                                    bot=bot,
                                    match=m,
                                    team1_name=t1_name,
                                    team2_name=t2_name,
                                    guild_id_str=discord_guild_id,
                                    tournament_category_id=t_cat_id,
                                    staff_role_ids=staff_role_ids,
                                    team1_discord_role_id=t1_role,
                                    team2_discord_role_id=t2_role,
                                )
                                if ch_id:
                                    m.private_channel_id = str(ch_id)
                                    channels_created += 1

                        # Post match info + score button
                        if ch_id:
                            import discord as _discord
                            ch = bot.get_channel(ch_id)
                            if isinstance(ch, _discord.TextChannel):
                                async with AsyncSessionLocal() as session:
                                    mgr = MatchChannelManager(session)
                                    m2 = await session.get(Match, match.id)
                                    if m2:
                                        await mgr.post_match_info(
                                            bot=bot,
                                            channel_id=ch_id,
                                            match=m2,
                                            team1_name=t1_name,
                                            team2_name=t2_name,
                                        )
                                score_view = MatchScoreButtonView()
                                bot.add_view(score_view)
                                prompt = score_prompt_embed(
                                    team1_name=t1_name,
                                    team2_name=t2_name,
                                    round_num=match.round or 1,
                                    match_num=match.match_number or 1,
                                )
                                await ch.send(embed=prompt, view=score_view)
                    except Exception as exc:
                        logger.warning("Could not create channel for match %s: %s", match.id[:8], exc)

            except Exception as exc:
                logger.warning("Match channel creation after bracket gen failed: %s", exc)

        desc = f"Format: **{t_fmt}**\nBracket ID: `{bracket.id[:8]}`"
        if channels_created:
            desc += f"\n\n📬 **{channels_created}** match channel(s) created for Round 1."
        else:
            desc += "\n\n_Match channels will be created automatically when matches begin._"

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Bracket Generated!",
                description=desc,
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class _FieldManageView(discord.ui.View):
    """Ephemeral view for managing registration form fields."""

    def __init__(self, t_id: str, org_id: str) -> None:
        super().__init__(timeout=120)
        self.t_id = t_id
        self.org_id = org_id

    @discord.ui.button(label="➕ Add Field", style=discord.ButtonStyle.success)
    async def add_field(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_AddFieldModal(self.t_id, self.org_id))

    @discord.ui.button(label="🗑 Reset All Fields", style=discord.ButtonStyle.danger)
    async def reset_fields(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.registration import RegistrationForm
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            async with session.begin():
                q = (
                    select(RegistrationForm)
                    .where(RegistrationForm.organization_id == self.org_id)
                    .where(RegistrationForm.tournament_id == self.t_id)
                    .where(RegistrationForm.is_active.is_(True))
                )
                form = (await session.execute(q)).scalar_one_or_none()
                if form:
                    form.is_active = False

        await interaction.followup.send(
            "✅ Registration form reset. Players will see the default **In-Game Name** field.",
            ephemeral=True,
        )


class _AddFieldModal(discord.ui.Modal, title="Add Registration Field"):
    field_label = discord.ui.TextInput(
        label="Field Label (shown to players)",
        placeholder="e.g. In-Game Name, Discord Tag, Team Name",
        required=True,
        max_length=80,
    )
    field_key = discord.ui.TextInput(
        label="Field Key (lowercase, underscores only)",
        placeholder="e.g. in_game_name, discord_tag",
        required=True,
        max_length=50,
    )
    field_type = discord.ui.TextInput(
        label="Type: text / long_text / number",
        placeholder="text",
        required=False,
        max_length=20,
    )
    is_required = discord.ui.TextInput(
        label="Required? (yes / no)",
        placeholder="yes",
        required=False,
        max_length=3,
    )

    def __init__(self, t_id: str, org_id: str) -> None:
        super().__init__()
        self.t_id = t_id
        self.org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.services.registration.form_builder import FormBuilderService

        raw_type = self.field_type.value.strip().lower() or "text"
        type_map = {
            "text": "text", "short": "text",
            "long_text": "long_text", "paragraph": "long_text", "long": "long_text",
            "number": "number", "numeric": "number", "int": "number",
        }
        resolved_type = type_map.get(raw_type, "text")

        raw_key = self.field_key.value.strip().lower()
        safe_key = re.sub(r"[^a-z0-9_]", "_", raw_key)[:50] or "field"

        required_val = self.is_required.value.strip().lower()
        required = required_val not in ("no", "n", "false", "0", "")

        field_def = {
            "field_key": safe_key,
            "label": self.field_label.value.strip(),
            "field_type": resolved_type,
            "is_required": required,
        }

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    fb = FormBuilderService(session)
                    form = await fb.get_active_form(self.org_id, self.t_id)
                    existing_fields: list[dict] = []
                    if form and form.fields:
                        if len(form.fields) >= 5:
                            await interaction.followup.send(
                                "❌ Maximum of **5 fields** already configured (Discord modal limit).\n"
                                "Use **Reset All Fields** to start over.",
                                ephemeral=True,
                            )
                            return
                        existing_fields = [
                            {
                                "field_key": f.field_key,
                                "label": f.label,
                                "field_type": f.field_type.value,
                                "is_required": f.is_required,
                            }
                            for f in sorted(form.fields, key=lambda x: x.display_order)
                        ]
                    existing_fields.append(field_def)
                    await fb.create_form(self.org_id, self.t_id, existing_fields)

            await interaction.followup.send(
                f"✅ Field **{field_def['label']}** (`{safe_key}`, {resolved_type}, "
                f"{'required' if required else 'optional'}) added!\n"
                "Players will see this field when they register.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.error("_AddFieldModal.on_submit failed: %s", exc, exc_info=True)
            await interaction.followup.send(f"❌ Error saving field: {exc}", ephemeral=True)


class _AnnouncementModal(discord.ui.Modal, title="Post Announcement"):
    content = discord.ui.TextInput(
        label="Announcement Text",
        placeholder="Write your announcement here…",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    channel_name = discord.ui.TextInput(
        label="Channel (name or blank for auto-detect)",
        placeholder="📢-announcements  — leave blank to use tournament announcements",
        required=False,
        max_length=100,
    )
    ping = discord.ui.TextInput(
        label="Ping (@everyone, @here, role name, or blank)",
        placeholder="@everyone",
        required=False,
        max_length=50,
    )

    def __init__(self, t_id: str) -> None:
        super().__init__()
        self.t_id = t_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament
        from sqlalchemy import select

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        async with AsyncSessionLocal() as session:
            g_q = select(Guild).where(Guild.discord_guild_id == str(guild.id), Guild.deleted_at.is_(None))
            g = (await session.execute(g_q)).scalar_one_or_none()
            t = await session.get(Tournament, self.t_id)

        channel_ids: dict = (g.settings or {}).get("channel_ids", {}) if g else {}
        t_settings: dict = (t.channel_config or {}) if t else {}

        # 1. If staff typed a channel name/mention, resolve it
        ann_ch: discord.TextChannel | None = None
        typed_name = self.channel_name.value.strip().lstrip("#").lower()
        if typed_name:
            for ch in guild.text_channels:
                if ch.name.lower() == typed_name or ch.name.lstrip("⁠").lower() == typed_name:
                    ann_ch = ch
                    break
            if not ann_ch:
                # partial match
                for ch in guild.text_channels:
                    if typed_name in ch.name.lower():
                        ann_ch = ch
                        break

        # 2. Tournament-specific announcements channel (in tournament category)
        if not ann_ch:
            t_cat_id = t_settings.get("tournament_category_id")
            if t_cat_id:
                cat = guild.get_channel(int(t_cat_id))
                if isinstance(cat, discord.CategoryChannel):
                    for ch in cat.channels:
                        if "announc" in ch.name and isinstance(ch, discord.TextChannel):
                            ann_ch = ch
                            break

        # 3. Global announcements channel
        if not ann_ch:
            ann_ch_id = channel_ids.get("announcements")
            if ann_ch_id:
                ann_ch = guild.get_channel(int(ann_ch_id))

        if not isinstance(ann_ch, discord.TextChannel):
            await interaction.followup.send(
                "❌ Could not find an announcements channel.\n"
                "Type the exact channel name in the **Channel** field.",
                ephemeral=True,
            )
            return

        ping_text = ""
        ping_val = self.ping.value.strip()
        if ping_val in ("@everyone", "@here"):
            ping_text = ping_val + " "
        elif ping_val:
            ping_text = f"{ping_val} "

        embed = discord.Embed(
            title="📢 Announcement",
            description=self.content.value,
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Posted by {interaction.user.display_name}")

        await ann_ch.send(content=ping_text, embed=embed)
        await interaction.followup.send(f"✅ Announcement posted in {ann_ch.mention}.", ephemeral=True)


# ── Override / Settings / Search panels ───────────────────────────────────────

async def _panel_overrides(interaction: discord.Interaction, t_id: str) -> None:
    """Open the Override sub-panel — all staff override operations as buttons."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.models.staff import StaffRole
    from app.bot.helpers.permissions import has_permission
    from app.bot.views.override_panel_view import OverridePanelView

    async with AsyncSessionLocal() as session:
        if not await has_permission(session, interaction.user, str(interaction.guild_id), StaffRole.TOURNAMENT_ADMIN):
            await interaction.followup.send("❌ Tournament Admin role required.", ephemeral=True)
            return
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        t_name = t.name
        org_id = t.organization_id

    embed = discord.Embed(
        title=f"🛠️ Override Tools — {t_name}",
        description=(
            "Use the buttons below to perform staff overrides.\n"
            "All actions are **logged to the audit trail**.\n\n"
            "🚫 **DQ Team** — disqualify a team\n"
            "⚔️ **Set Winner** — force-declare a match winner\n"
            "⏩ **Advance Round** — skip to next round\n"
            "👻 **Forfeit No-shows** — remove absent teams\n"
            "📸 **Take Snapshot** — capture current state\n"
            "🔁 **Restore Snapshot** — roll back to a snapshot"
        ),
        color=discord.Color.red(),
    )
    view = OverridePanelView(tournament_id=t_id, org_id=org_id, tournament_name=t_name)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def _panel_settings(interaction: discord.Interaction, t_id: str) -> None:
    """Open the Settings sub-panel — feature flags + webhook management."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.database.models.staff import StaffRole
    from app.bot.helpers.permissions import has_permission
    from app.bot.views.settings_panel_view import SettingsPanelView, _KNOWN_FLAGS

    async with AsyncSessionLocal() as session:
        if not await has_permission(session, interaction.user, str(interaction.guild_id), StaffRole.TOURNAMENT_ADMIN):
            await interaction.followup.send("❌ Tournament Admin role required.", ephemeral=True)
            return
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        current_flags = dict(t.feature_flags or {})
        t_name = t.name
        org_id = t.organization_id

    embed = discord.Embed(
        title=f"⚙️ Settings — {t_name}",
        color=discord.Color.greyple(),
    )
    for key, desc in _KNOWN_FLAGS.items():
        val = current_flags.get(key)
        icon = "✅" if val is True else ("❌" if val is False else "⬜ default")
        embed.add_field(name=f"{icon}  `{key}`", value=desc, inline=False)

    embed.set_footer(text="Click a flag button to toggle it. Use the webhook buttons to manage outbound webhooks.")
    view = SettingsPanelView(
        tournament_id=t_id,
        org_id=org_id,
        tournament_name=t_name,
        current_flags=current_flags,
    )
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def _panel_search(interaction: discord.Interaction, t_id: str) -> None:
    """Open the Search sub-panel — find tournaments, teams, matches."""
    await interaction.response.defer(ephemeral=True)
    from app.database.session import AsyncSessionLocal
    from app.bot.views.search_panel_view import SearchPanelView

    async with AsyncSessionLocal() as session:
        guild, t = await _get_tournament(session, t_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        org_id = t.organization_id

    embed = discord.Embed(
        title="🔍 Search",
        description=(
            "📅 **Find Tournament** — search by name or game\n"
            "👥 **Find Team** — look up a team, or find your own team\n"
            "🎮 **Find Matches** — list matches by tournament and round"
        ),
        color=discord.Color.blurple(),
    )
    view = SearchPanelView(org_id=org_id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
