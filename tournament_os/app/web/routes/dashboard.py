"""
Organizer dashboard API routes — staff only, V1 bearer auth.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.web.middleware.auth import require_admin
from app.database.repositories.tournament import TournamentRepository
from app.database.repositories.registration import RegistrationRepository
from app.database.repositories.team import TeamRepository
from app.database.repositories.match import MatchRepository
from app.database.repositories.dispute import DisputeRepository
from app.database.repositories.audit import AuditRepository
from app.database.models.tournament import TournamentFormat, TournamentStatus, TeamSizeType, EventType
from app.database.models.registration import RegistrationStatus
from app.services.analytics.aggregator import AnalyticsAggregator

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ══════════════════════════════════════════════════════════════════════
# Tournaments
# ══════════════════════════════════════════════════════════════════════

class TournamentCreate(BaseModel):
    organization_id: str
    guild_id: str
    created_by: str
    name: str
    game: str
    format: str
    team_size_type: str = "solo"
    event_type: str = "open"
    description: str | None = None
    max_teams: int | None = None
    prize_pool: str | None = None
    region: str | None = None
    platform: str | None = None
    rules: str | None = None
    autonomous_mode: bool = False


@router.post("/tournaments", dependencies=[Depends(require_admin)])
async def create_tournament(
    body: TournamentCreate,
    session: AsyncSession = Depends(get_session),
):
    from app.services.tournament.creation import TournamentCreationService
    async with session.begin():
        svc = TournamentCreationService(session)
        t = await svc.create(
            organization_id=body.organization_id,
            guild_id=body.guild_id,
            created_by=body.created_by,
            name=body.name,
            game=body.game,
            format=TournamentFormat(body.format),
            team_size_type=TeamSizeType(body.team_size_type),
            event_type=EventType(body.event_type),
            description=body.description,
            max_teams=body.max_teams,
            prize_pool=body.prize_pool,
            region=body.region,
            platform=body.platform,
            rules=body.rules,
        )
        if body.autonomous_mode:
            t.autonomous_mode = True
    return {"id": t.id, "name": t.name, "slug": t.slug, "status": t.status.value}


@router.get("/tournaments", dependencies=[Depends(require_admin)])
async def list_tournaments(
    organization_id: str,
    status: str | None = None,
    limit: int = 50, offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    repo = TournamentRepository(session)
    if status:
        tournaments = await repo.list_by_status(organization_id, TournamentStatus(status), limit, offset)
    else:
        tournaments = await repo.list_all(organization_id, limit=limit, offset=offset)
    return {
        "tournaments": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.value,
                "game": t.game,
                "format": t.format.value,
                "autonomous_mode": t.autonomous_mode,
            }
            for t in tournaments
        ]
    }


@router.get("/tournaments/{tournament_id}", dependencies=[Depends(require_admin)])
async def get_tournament(
    tournament_id: str, organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = TournamentRepository(session)
    t = await repo.get_by_id(tournament_id, organization_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {
        "id": t.id, "name": t.name, "slug": t.slug, "game": t.game,
        "format": t.format.value, "status": t.status.value,
        "description": t.description, "rules": t.rules,
        "prize_pool": t.prize_pool, "max_teams": t.max_teams,
        "allow_duplicates": t.allow_duplicates,
        "autonomous_mode": t.autonomous_mode,
        "registration_open_at": str(t.registration_open_at or ""),
        "registration_close_at": str(t.registration_close_at or ""),
        "checkin_open_at": str(t.checkin_open_at or ""),
        "match_start_at": str(t.match_start_at or ""),
    }


class StatusChange(BaseModel):
    new_status: str
    actor_id: str


@router.post("/tournaments/{tournament_id}/status", dependencies=[Depends(require_admin)])
async def change_tournament_status(
    tournament_id: str, organization_id: str, body: StatusChange,
    session: AsyncSession = Depends(get_session),
):
    from app.services.tournament.lifecycle import TournamentLifecycleService
    async with session.begin():
        svc = TournamentLifecycleService(session)
        try:
            t = await svc.transition_status(
                tournament_id=tournament_id,
                organization_id=organization_id,
                new_status=TournamentStatus(body.new_status),
                actor_id=body.actor_id,
                actor_type="dashboard",
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"id": t.id, "status": t.status.value}


class AutonomousModeBody(BaseModel):
    enabled: bool
    actor_id: str


@router.post("/tournaments/{tournament_id}/autonomous", dependencies=[Depends(require_admin)])
async def set_autonomous_mode(
    tournament_id: str, organization_id: str, body: AutonomousModeBody,
    session: AsyncSession = Depends(get_session),
):
    """Enable or disable autonomous mode for a tournament."""
    from app.database.models.tournament import Tournament
    async with session.begin():
        t = await session.get(Tournament, tournament_id)
        if not t or t.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Tournament not found")
        t.autonomous_mode = body.enabled
        from app.database.repositories.audit import AuditRepository
        audit = AuditRepository(session)
        await audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="tournament.autonomous_mode_changed",
            actor_id=body.actor_id,
            actor_type="dashboard",
            target_type="tournament",
            target_id=tournament_id,
            payload={"enabled": body.enabled},
        )
    return {"tournament_id": tournament_id, "autonomous_mode": body.enabled}


# ══════════════════════════════════════════════════════════════════════
# Registrations
# ══════════════════════════════════════════════════════════════════════

@router.get("/tournaments/{tournament_id}/registrations", dependencies=[Depends(require_admin)])
async def list_registrations(
    tournament_id: str, organization_id: str,
    status: str | None = None, limit: int = 100, offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    repo = RegistrationRepository(session)
    if status:
        regs = await repo.list_by_status(organization_id, tournament_id, RegistrationStatus(status), limit, offset)
    else:
        regs = await repo.list_all(organization_id, tournament_id, limit=limit, offset=offset)
    return {
        "registrations": [
            {
                "id": r.id, "status": r.status.value,
                "submitted_by": r.submitted_by,
                "flags": len(r.duplicate_flags),
                "notes": r.notes,
                "rejection_reason": r.rejection_reason,
                "created_at": str(r.created_at),
            }
            for r in regs
        ]
    }


class RegistrationAction(BaseModel):
    action: str  # approve | reject | flag | waitlist | checkin
    reviewer_id: str
    reason: str = ""
    notes: str = ""


@router.post(
    "/tournaments/{tournament_id}/registrations/{registration_id}/action",
    dependencies=[Depends(require_admin)],
)
async def registration_action(
    tournament_id: str, registration_id: str, organization_id: str,
    body: RegistrationAction,
    session: AsyncSession = Depends(get_session),
):
    from app.database.repositories.tournament import TournamentRepository
    from app.services.registration.approvals import RegistrationApprovalService
    async with session.begin():
        t_repo = TournamentRepository(session)
        tournament = await t_repo.get_by_id(tournament_id, organization_id)
        if not tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")

        svc = RegistrationApprovalService(session)
        try:
            if body.action == "approve":
                await svc.approve(registration_id, tournament, body.reviewer_id, notes=body.notes or None)
            elif body.action == "reject":
                await svc.reject(registration_id, tournament, body.reviewer_id, body.reason)
            elif body.action == "flag":
                await svc.flag(registration_id, tournament, body.reviewer_id, notes=body.notes or None)
            elif body.action == "waitlist":
                await svc.waitlist(registration_id, tournament, body.reviewer_id, notes=body.notes or None)
            elif body.action == "checkin":
                await svc.checkin(registration_id, tournament, body.reviewer_id)
            else:
                raise HTTPException(status_code=422, detail=f"Invalid action '{body.action}'. Valid: approve, reject, flag, waitlist, checkin")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════
# Analytics
# ══════════════════════════════════════════════════════════════════════

@router.get("/tournaments/{tournament_id}/analytics", dependencies=[Depends(require_admin)])
async def tournament_analytics(
    tournament_id: str, organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    agg = AnalyticsAggregator(session)
    return await agg.tournament_summary(organization_id, tournament_id)


# ══════════════════════════════════════════════════════════════════════
# Disputes — nested + top-level org-scoped routes
# ══════════════════════════════════════════════════════════════════════

@router.get("/tournaments/{tournament_id}/disputes", dependencies=[Depends(require_admin)])
async def list_disputes(
    tournament_id: str, organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = DisputeRepository(session)
    disputes = await repo.list_open(organization_id, tournament_id)
    return {
        "disputes": [
            {
                "id": d.id, "case_type": d.case_type.value,
                "status": d.status.value, "description": d.description[:200],
                "opened_by": d.opened_by, "match_id": d.match_id,
                "created_at": str(d.created_at),
            }
            for d in disputes
        ]
    }


@router.get("/disputes", dependencies=[Depends(require_admin)])
async def list_all_disputes(
    organization_id: str,
    tournament_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Top-level disputes route — org-scoped, optionally filtered by tournament."""
    from sqlalchemy import select
    from app.database.models.dispute import Dispute

    q = select(Dispute).where(
        Dispute.organization_id == organization_id,
        Dispute.deleted_at.is_(None) if hasattr(Dispute, "deleted_at") else True,
    )
    if tournament_id:
        q = q.where(Dispute.tournament_id == tournament_id)
    q = q.order_by(Dispute.created_at.desc()).limit(100)
    disputes = (await session.execute(q)).scalars().all()
    return {
        "disputes": [
            {
                "id": d.id, "tournament_id": d.tournament_id,
                "case_type": d.case_type.value, "status": d.status.value,
                "description": d.description[:200], "opened_by": d.opened_by,
                "match_id": d.match_id, "created_at": str(d.created_at),
            }
            for d in disputes
        ]
    }


class DisputeResolveBody(BaseModel):
    resolved_by: str
    resolution: str
    status: str = "resolved"


@router.post("/tournaments/{tournament_id}/disputes/{dispute_id}/resolve",
             dependencies=[Depends(require_admin)])
async def resolve_dispute(
    tournament_id: str, dispute_id: str, organization_id: str,
    body: DisputeResolveBody,
    session: AsyncSession = Depends(get_session),
):
    from app.services.dispute.case_manager import DisputeCaseManager
    from app.database.models.dispute import DisputeStatus
    async with session.begin():
        svc = DisputeCaseManager(session)
        try:
            await svc.resolve(
                dispute_id=dispute_id,
                organization_id=organization_id,
                tournament_id=tournament_id,
                resolved_by=body.resolved_by,
                resolution=body.resolution,
                status=DisputeStatus(body.status),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════
# Audit Log
# ══════════════════════════════════════════════════════════════════════

@router.get("/tournaments/{tournament_id}/audit", dependencies=[Depends(require_admin)])
async def audit_log(
    tournament_id: str, organization_id: str,
    limit: int = 100, offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    repo = AuditRepository(session)
    entries = await repo.list_for_tournament(organization_id, tournament_id, limit, offset)
    return {
        "entries": [
            {
                "id": e.id, "action": e.action,
                "actor_id": e.actor_id, "actor_type": e.actor_type,
                "target_type": e.target_type, "target_id": e.target_id,
                "created_at": str(e.created_at),
                "payload": e.payload,
            }
            for e in entries
        ]
    }


# ══════════════════════════════════════════════════════════════════════
# Bracket & Matches — nested + top-level org-scoped routes
# ══════════════════════════════════════════════════════════════════════

@router.post("/tournaments/{tournament_id}/bracket/generate", dependencies=[Depends(require_admin)])
async def generate_bracket(
    tournament_id: str, organization_id: str,
    seeding_method: str = "seed",
    session: AsyncSession = Depends(get_session),
):
    from app.database.repositories.tournament import TournamentRepository
    from app.services.bracket.generator import BracketGenerator
    async with session.begin():
        t_repo = TournamentRepository(session)
        t = await t_repo.get_by_id(tournament_id, organization_id)
        if not t:
            raise HTTPException(status_code=404, detail="Tournament not found")
        gen = BracketGenerator(session)
        try:
            bracket = await gen.generate(organization_id, tournament_id, t.format, seeding_method)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"bracket_id": bracket.id, "name": bracket.name, "type": bracket.bracket_type}


@router.get("/tournaments/{tournament_id}/matches", dependencies=[Depends(require_admin)])
async def list_matches_for_tournament(
    tournament_id: str, organization_id: str,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    from app.database.models.match import MatchStatus
    repo = MatchRepository(session)
    if status:
        matches = await repo.list_by_status(organization_id, tournament_id, MatchStatus(status))
    else:
        matches = await repo.list_all(organization_id, tournament_id)
    return {
        "matches": [
            {
                "id": m.id, "round": m.round, "match_number": m.match_number,
                "status": m.status.value, "team1_id": m.team1_id, "team2_id": m.team2_id,
                "winner_id": m.winner_id, "scheduled_at": str(m.scheduled_at or ""),
            }
            for m in matches
        ]
    }


@router.get("/matches", dependencies=[Depends(require_admin)])
async def list_all_matches(
    organization_id: str,
    tournament_id: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Top-level matches route — org-scoped, optionally filtered by tournament and status."""
    from app.database.models.match import Match, MatchStatus
    from sqlalchemy import select

    q = select(Match).where(Match.organization_id == organization_id)
    if tournament_id:
        q = q.where(Match.tournament_id == tournament_id)
    if status:
        q = q.where(Match.status == MatchStatus(status))
    q = q.order_by(Match.round, Match.match_number).limit(200)

    matches = (await session.execute(q)).scalars().all()
    return {
        "matches": [
            {
                "id": m.id, "tournament_id": m.tournament_id,
                "round": m.round, "match_number": m.match_number,
                "status": m.status.value, "team1_id": m.team1_id, "team2_id": m.team2_id,
                "winner_id": m.winner_id, "scheduled_at": str(m.scheduled_at or ""),
            }
            for m in matches
        ]
    }


# ══════════════════════════════════════════════════════════════════════
# Teams
# ══════════════════════════════════════════════════════════════════════

@router.get("/tournaments/{tournament_id}/teams", dependencies=[Depends(require_admin)])
async def list_teams(
    tournament_id: str, organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = TeamRepository(session)
    teams = await repo.list_all(organization_id, tournament_id)
    return {
        "teams": [
            {
                "id": t.id, "name": t.name, "seed": t.seed,
                "checkin_status": t.checkin_status, "is_reserve": t.is_reserve,
            }
            for t in teams
        ]
    }


# ══════════════════════════════════════════════════════════════════════
# No-Show Processing
# ══════════════════════════════════════════════════════════════════════

@router.post("/tournaments/{tournament_id}/process_noshows", dependencies=[Depends(require_admin)])
async def process_noshows(
    tournament_id: str, organization_id: str,
    session: AsyncSession = Depends(get_session),
):
    from app.services.checkin.noshow_handler import NoShowHandler
    async with session.begin():
        handler = NoShowHandler(session)
        result = await handler.process_noshows(organization_id, tournament_id)
    return result
