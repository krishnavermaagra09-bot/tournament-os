"""
Override Panel — ephemeral sub-panel with buttons for all staff override operations.
Triggered from the Control Panel "🛠️ Overrides" button.

Operations (all via modal):
  🚫 DQ Team | ⚔️ Set Winner | ⏩ Advance Round | 👻 Forfeit No-shows
  📸 Snapshot | 🔁 Restore Snapshot
"""
import logging
import discord

logger = logging.getLogger(__name__)


# ── Modals ────────────────────────────────────────────────────────────────────

class _DQModal(discord.ui.Modal, title="🚫 Disqualify Team"):
    team_id  = discord.ui.TextInput(label="Team ID (first 8 chars is fine)", min_length=4, max_length=36)
    reason   = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=False, default="Disqualified by staff")

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.team import Team
        from app.database.models.audit_log import AuditLog
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select

        raw_id = self.team_id.value.strip()
        reason = self.reason.value.strip() or "Disqualified by staff"

        async with AsyncSessionLocal() as session:
            async with session.begin():
                q = select(Team).where(
                    Team.organization_id == self._org_id,
                    Team.tournament_id   == self._tournament_id,
                    Team.deleted_at.is_(None),
                    (Team.id == raw_id) | Team.id.startswith(raw_id),
                ).limit(1)
                team = (await session.execute(q)).scalar_one_or_none()
                if not team:
                    await interaction.followup.send(embed=error_embed(f"Team `{raw_id}` not found."), ephemeral=True)
                    return

                team.is_disqualified = True
                team.disqualification_reason = reason
                session.add(AuditLog(
                    organization_id=self._org_id,
                    tournament_id=self._tournament_id,
                    actor_id=str(interaction.user.id),
                    actor_type="staff",
                    action="team.disqualified",
                    details={"team_id": team.id, "team_name": team.name, "reason": reason},
                ))

        await interaction.followup.send(
            embed=success_embed(f"Team **{team.name}** has been disqualified.\nReason: {reason}", title="🚫 Team DQ'd"),
            ephemeral=True,
        )
        logger.info("override.dq: team=%s tournament=%s by=%s", team.id[:8], self._tournament_id[:8], interaction.user.id)


class _SetWinnerModal(discord.ui.Modal, title="⚔️ Force-Set Match Winner"):
    match_id        = discord.ui.TextInput(label="Match ID (first 8 chars is fine)", min_length=4, max_length=36)
    winner_team_id  = discord.ui.TextInput(label="Winner Team ID (first 8 chars is fine)", min_length=4, max_length=36)
    reason          = discord.ui.TextInput(label="Reason (optional)", required=False, default="Staff override")

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match, MatchStatus
        from app.database.models.team import Team
        from app.database.models.audit_log import AuditLog
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select

        m_raw = self.match_id.value.strip()
        w_raw = self.winner_team_id.value.strip()
        reason = self.reason.value.strip() or "Staff override"

        async with AsyncSessionLocal() as session:
            async with session.begin():
                mq = select(Match).where(
                    Match.organization_id == self._org_id,
                    Match.tournament_id   == self._tournament_id,
                    Match.deleted_at.is_(None),
                    (Match.id == m_raw) | Match.id.startswith(m_raw),
                ).limit(1)
                match = (await session.execute(mq)).scalar_one_or_none()
                if not match:
                    await interaction.followup.send(embed=error_embed(f"Match `{m_raw}` not found."), ephemeral=True)
                    return

                tq = select(Team).where(
                    Team.organization_id == self._org_id,
                    Team.deleted_at.is_(None),
                    (Team.id == w_raw) | Team.id.startswith(w_raw),
                ).limit(1)
                winner = (await session.execute(tq)).scalar_one_or_none()
                if not winner:
                    await interaction.followup.send(embed=error_embed(f"Team `{w_raw}` not found."), ephemeral=True)
                    return

                match.winner_id = winner.id
                match.status = MatchStatus.COMPLETED
                session.add(AuditLog(
                    organization_id=self._org_id,
                    tournament_id=self._tournament_id,
                    actor_id=str(interaction.user.id),
                    actor_type="staff",
                    action="match.override_winner",
                    details={"match_id": match.id, "winner_id": winner.id, "winner_name": winner.name, "reason": reason},
                ))

        await interaction.followup.send(
            embed=success_embed(
                f"Match `{match.id[:8]}` winner set to **{winner.name}**.\nReason: {reason}",
                title="⚔️ Match Winner Set",
            ),
            ephemeral=True,
        )
        logger.info("override.set_winner: match=%s winner=%s by=%s", match.id[:8], winner.id[:8], interaction.user.id)


class _AdvanceModal(discord.ui.Modal, title="⏩ Force-Advance Round"):
    bracket_id = discord.ui.TextInput(
        label="Bracket ID (leave blank to auto-detect)",
        required=False,
        placeholder="Leave blank to use the active bracket",
    )

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.bracket import Bracket
        from app.database.models.audit_log import AuditLog
        from app.services.bracket.advancement import BracketAdvancementService
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select

        b_raw = (self.bracket_id.value or "").strip()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                if b_raw:
                    bq = select(Bracket).where(
                        (Bracket.id == b_raw) | Bracket.id.startswith(b_raw),
                        Bracket.tournament_id == self._tournament_id,
                    ).limit(1)
                    bracket = (await session.execute(bq)).scalar_one_or_none()
                else:
                    bq = select(Bracket).where(
                        Bracket.tournament_id   == self._tournament_id,
                        Bracket.organization_id == self._org_id,
                    ).order_by(Bracket.stage.desc()).limit(1)
                    bracket = (await session.execute(bq)).scalar_one_or_none()

                if not bracket:
                    await interaction.followup.send(embed=error_embed("No bracket found for this tournament."), ephemeral=True)
                    return

                try:
                    adv = BracketAdvancementService(session)
                    new_matches = await adv.generate_next_round(self._org_id, self._tournament_id, bracket.id)
                except ValueError as exc:
                    await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
                    return

                session.add(AuditLog(
                    organization_id=self._org_id,
                    tournament_id=self._tournament_id,
                    actor_id=str(interaction.user.id),
                    actor_type="staff",
                    action="bracket.advanced",
                    details={"bracket_id": bracket.id, "new_matches": len(new_matches)},
                ))

        await interaction.followup.send(
            embed=success_embed(
                f"Round advanced. **{len(new_matches)}** new match(es) created.",
                title="⏩ Bracket Advanced",
            ),
            ephemeral=True,
        )
        logger.info("override.advance: tournament=%s matches=%d by=%s", self._tournament_id[:8], len(new_matches), interaction.user.id)


class _SnapshotModal(discord.ui.Modal, title="📸 Take Snapshot"):
    label = discord.ui.TextInput(label="Label (optional)", required=False, default="manual", max_length=80)

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.services.snapshot.snapshot_service import SnapshotService
        from app.bot.helpers.formatters import success_embed, error_embed

        label = self.label.value.strip() or "manual"
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    svc = SnapshotService(session)
                    snap = await svc.take(
                        organization_id=self._org_id,
                        tournament_id=self._tournament_id,
                        trigger="manual",
                        label=label,
                    )
        except Exception as exc:
            await interaction.followup.send(embed=error_embed(f"Snapshot failed: {exc}"), ephemeral=True)
            return

        await interaction.followup.send(
            embed=success_embed(
                f"Snapshot `{snap.id[:8]}` saved.\nLabel: **{label}**\nView via **📸 Snapshots** in the control panel.",
                title="📸 Snapshot Taken",
            ),
            ephemeral=True,
        )


class _RestoreModal(discord.ui.Modal, title="🔁 Restore Snapshot"):
    snapshot_id = discord.ui.TextInput(label="Snapshot ID (first 8 chars is fine)", min_length=4, max_length=36)
    confirm     = discord.ui.TextInput(label='Type  CONFIRM  to proceed', placeholder="CONFIRM")

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.snapshot import TournamentSnapshot
        from app.database.models.tournament import TournamentStatus
        from app.database.models.standings import Standings
        from app.database.models.audit_log import AuditLog
        from app.bot.helpers.formatters import success_embed, error_embed
        from sqlalchemy import select

        if self.confirm.value.strip().upper() != "CONFIRM":
            await interaction.followup.send(embed=error_embed("You must type **CONFIRM** exactly to restore."), ephemeral=True)
            return

        raw = self.snapshot_id.value.strip()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                sq = select(TournamentSnapshot).where(
                    TournamentSnapshot.organization_id == self._org_id,
                    (TournamentSnapshot.id == raw) | TournamentSnapshot.id.startswith(raw),
                ).limit(1)
                snap = (await session.execute(sq)).scalar_one_or_none()
                if not snap:
                    await interaction.followup.send(embed=error_embed(f"Snapshot `{raw}` not found."), ephemeral=True)
                    return

                from app.database.models.tournament import Tournament
                tournament = await session.get(Tournament, self._tournament_id)
                state = snap.state or {}
                t_meta = state.get("tournament", {})

                if t_meta.get("status") and tournament:
                    try:
                        tournament.status = TournamentStatus(t_meta["status"])
                    except ValueError:
                        pass

                snap_standings = state.get("standings", [])
                if snap_standings:
                    existing_q = select(Standings).where(
                        Standings.organization_id == self._org_id,
                        Standings.tournament_id   == self._tournament_id,
                    )
                    existing = {s.team_id: s for s in (await session.execute(existing_q)).scalars().all()}
                    for row in snap_standings:
                        s = existing.get(row["team_id"])
                        if s:
                            s.rank   = row.get("rank")
                            s.wins   = row.get("wins", 0)
                            s.losses = row.get("losses", 0)
                            s.points = row.get("points", 0)

                session.add(AuditLog(
                    organization_id=self._org_id,
                    tournament_id=self._tournament_id,
                    actor_id=str(interaction.user.id),
                    actor_type="staff",
                    action="snapshot_restore",
                    details={"snapshot_id": snap.id, "restored_status": t_meta.get("status")},
                ))

        t_name = tournament.name if tournament else self._tournament_id[:8]
        await interaction.followup.send(
            embed=success_embed(
                f"Tournament **{t_name}** restored to snapshot `{snap.id[:8]}`.\n"
                f"Label: **{snap.label or snap.trigger}** | Status: **{t_meta.get('status','unchanged')}**\n"
                f"Standings restored: **{len(snap_standings)} teams**",
                title="🔁 Snapshot Restored",
            ),
            ephemeral=True,
        )
        logger.info("override.restore: snap=%s tournament=%s by=%s", snap.id[:8], self._tournament_id[:8], interaction.user.id)


class _ForfeitConfirmView(discord.ui.View):
    def __init__(self, tournament_id: str, org_id: str):
        super().__init__(timeout=60)
        self._tournament_id = tournament_id
        self._org_id = org_id

    @discord.ui.button(label="✅ Yes, forfeit all no-shows", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.services.match.no_show_handler import NoShowHandler
        from app.bot.helpers.formatters import success_embed, error_embed

        async with AsyncSessionLocal() as session:
            async with session.begin():
                handler = NoShowHandler(session)
                try:
                    removed, promoted = await handler.process_noshows(self._org_id, self._tournament_id)
                except Exception as exc:
                    await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
                    return

        await interaction.followup.send(
            embed=success_embed(
                f"No-show processing complete.\nTeams removed: **{len(removed)}** | Reserves promoted: **{len(promoted)}**",
                title="👻 No-shows Forfeited",
            ),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)
        self.stop()


# ── Main View ─────────────────────────────────────────────────────────────────

class OverridePanelView(discord.ui.View):
    """Ephemeral override sub-panel — opened from the Control Panel."""

    def __init__(self, tournament_id: str, org_id: str, tournament_name: str):
        super().__init__(timeout=120)
        self.tournament_id   = tournament_id
        self.org_id          = org_id
        self.tournament_name = tournament_name

    @discord.ui.button(label="🚫 DQ Team", style=discord.ButtonStyle.danger, row=0)
    async def dq_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_DQModal(self.tournament_id, self.org_id))

    @discord.ui.button(label="⚔️ Set Winner", style=discord.ButtonStyle.danger, row=0)
    async def winner_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_SetWinnerModal(self.tournament_id, self.org_id))

    @discord.ui.button(label="⏩ Advance Round", style=discord.ButtonStyle.primary, row=0)
    async def advance_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_AdvanceModal(self.tournament_id, self.org_id))

    @discord.ui.button(label="👻 Forfeit No-shows", style=discord.ButtonStyle.secondary, row=1)
    async def forfeit_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        e = discord.Embed(
            title="👻 Forfeit No-shows",
            description=(
                f"This will forfeit all no-show teams in **{self.tournament_name}** "
                "and promote reserves to fill their spots.\n\n⚠️ **This cannot be undone.**"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=e,
            view=_ForfeitConfirmView(self.tournament_id, self.org_id),
            ephemeral=True,
        )

    @discord.ui.button(label="📸 Take Snapshot", style=discord.ButtonStyle.secondary, row=1)
    async def snap_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_SnapshotModal(self.tournament_id, self.org_id))

    @discord.ui.button(label="🔁 Restore Snapshot", style=discord.ButtonStyle.secondary, row=1)
    async def restore_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_RestoreModal(self.tournament_id, self.org_id))
