"""
Notification event subscribers — listen for domain events and dispatch
real Discord notifications via discord_delivery.

Registered at startup by importing this module (decorators fire at import time).
Call register_all() explicitly if you need a no-op hook (e.g. for testing).
"""
import logging

from app.events.bus import event_bus

logger = logging.getLogger(__name__)


# ── Internal DB helpers ───────────────────────────────────────────────────────

async def _get_tournament_info(tournament_id: str, organization_id: str) -> dict:
    """Fetch tournament name + guild channel config for notification delivery."""
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            t = await session.get(Tournament, tournament_id)
            if not t:
                return {}

            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            guild_settings: dict = (guild.settings or {}) if guild else {}
            channel_ids: dict = guild_settings.get("channel_ids", {})
            tc: dict = t.channel_config or {}

            return {
                "name": t.name,
                "format": t.format.value if t.format else None,
                "announcements_channel_id": (
                    channel_ids.get("announcements")
                    or tc.get("announcements_channel_id")
                ),
                "schedule_channel_id": (
                    channel_ids.get("schedule")
                    or tc.get("schedule_channel_id")
                ),
                "staff_alerts_channel_id": (
                    channel_ids.get("staff_alerts")
                    or channel_ids.get("admin")
                    or tc.get("control_channel_id")
                ),
            }
    except Exception as exc:
        logger.warning("_get_tournament_info failed: %s", exc)
        return {}


async def _get_user_discord_id(registration_id: str) -> tuple[str | None, str | None]:
    """Return (discord_user_id, team_name) for a registration."""
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.registration import Registration
        from app.database.models.team import Team
        from app.database.models.user import User

        async with AsyncSessionLocal() as session:
            reg = await session.get(Registration, registration_id)
            if not reg:
                return None, None

            user = await session.get(User, reg.submitted_by)
            discord_id = user.discord_user_id if user else None

            team_name: str | None = None
            if reg.team_id:
                team = await session.get(Team, reg.team_id)
                if team:
                    team_name = team.name

            return discord_id, team_name
    except Exception as exc:
        logger.warning("_get_user_discord_id failed: %s", exc)
        return None, None


async def _get_match_context(
    match_id: str, tournament_id: str, organization_id: str
) -> dict | None:
    """
    Return everything needed to create a match channel and notify captains.
    All fetched in a single DB session for efficiency.
    """
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match
        from app.database.models.team import Team
        from app.database.models.user import User
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            match = await session.get(Match, match_id)
            if not match:
                return None

            tournament_id = match.tournament_id
            organization_id = match.organization_id

            team1 = await session.get(Team, match.team1_id) if match.team1_id else None
            team2 = await session.get(Team, match.team2_id) if match.team2_id else None

            cap1_discord_id: str | None = None
            cap2_discord_id: str | None = None
            if team1 and team1.captain_id:
                cap1 = await session.get(User, team1.captain_id)
                cap1_discord_id = cap1.discord_user_id if cap1 else None
            if team2 and team2.captain_id:
                cap2 = await session.get(User, team2.captain_id)
                cap2_discord_id = cap2.discord_user_id if cap2 else None

            tournament = await session.get(Tournament, tournament_id)
            if not tournament:
                return None
            tc = dict(tournament.channel_config or {})

            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                return None

            gs = dict(guild.settings or {})
            channel_ids: dict = gs.get("channel_ids", {})
            staff_role_ids: dict = gs.get("staff_role_ids", {})

            winner_team_id = match.winner_id
            winner_name: str | None = None
            if winner_team_id:
                wt = await session.get(Team, winner_team_id)
                winner_name = wt.name if wt else None

            return {
                "match_id": match.id,
                "tournament_id": tournament_id,
                "organization_id": organization_id,
                "round": match.round,
                "match_number": match.match_number,
                "team1_id": match.team1_id,
                "team2_id": match.team2_id,
                "team1_name": team1.name if team1 else "Team 1",
                "team2_name": team2.name if team2 else "Team 2",
                "team1_captain_discord_id": cap1_discord_id,
                "team2_captain_discord_id": cap2_discord_id,
                "team1_discord_role_id": str(team1.discord_role_id) if (team1 and getattr(team1, "discord_role_id", None)) else None,
                "team2_discord_role_id": str(team2.discord_role_id) if (team2 and getattr(team2, "discord_role_id", None)) else None,
                "discord_guild_id": guild.discord_guild_id,
                "tournament_category_id": tc.get("tournament_category_id"),
                "staff_role_ids": staff_role_ids,
                "rules": tournament.rules if hasattr(tournament, "rules") else None,
                "announcements_channel_id": channel_ids.get("announcements"),
                "results_channel_id": channel_ids.get("results"),
                "schedule_channel_id": channel_ids.get("schedule"),
                "private_channel_id": match.private_channel_id,
                "winner_name": winner_name,
                "tournament_name": tournament.name,
            }
    except Exception as exc:
        logger.warning("_get_match_context failed: %s", exc)
        return None


# ── Event subscribers ─────────────────────────────────────────────────────────

@event_bus.subscribe("RegistrationSubmitted")
async def on_registration_submitted(payload: dict) -> None:
    logger.info(
        "Registration submitted: reg_id=%s tournament_id=%s duplicates=%s",
        payload.get("registration_id"),
        payload.get("tournament_id"),
        payload.get("has_duplicates"),
    )
    t_info = await _get_tournament_info(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )
    if t_info.get("staff_alerts_channel_id") and payload.get("has_duplicates"):
        from app.services.notification.discord_delivery import _post_to_channel
        import discord
        e = discord.Embed(
            title="⚠️ Duplicate Registration Detected",
            description=f"A registration with possible duplicates was submitted for **{t_info.get('name', 'tournament')}**.",
            color=discord.Color.yellow(),
        )
        e.add_field(name="Reg ID", value=payload.get("registration_id", "")[:8], inline=True)
        e.set_footer(text="Review in the Registration panel.")
        await _post_to_channel(t_info["staff_alerts_channel_id"], e)


@event_bus.subscribe("RegistrationApproved")
async def on_registration_approved(payload: dict) -> None:
    logger.info(
        "Registration approved: reg_id=%s by=%s",
        payload.get("registration_id"),
        payload.get("reviewed_by"),
    )
    reg_id = payload.get("registration_id", "")
    t_info = await _get_tournament_info(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )
    discord_id, team_name = await _get_user_discord_id(reg_id)
    if discord_id and t_info.get("name"):
        from app.services.notification.discord_delivery import notify_registration_approved
        await notify_registration_approved(
            discord_id=discord_id,
            tournament_name=t_info["name"],
            team_name=team_name,
        )


@event_bus.subscribe("RegistrationRejected")
async def on_registration_rejected(payload: dict) -> None:
    logger.info(
        "Registration rejected: reg_id=%s reason=%s",
        payload.get("registration_id"),
        payload.get("reason"),
    )
    reg_id = payload.get("registration_id", "")
    t_info = await _get_tournament_info(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )
    discord_id, _ = await _get_user_discord_id(reg_id)
    if discord_id and t_info.get("name"):
        from app.services.notification.discord_delivery import notify_registration_rejected
        await notify_registration_rejected(
            discord_id=discord_id,
            tournament_name=t_info["name"],
            reason=payload.get("reason"),
        )


@event_bus.subscribe("MatchStarted")
async def on_match_started(payload: dict) -> None:
    match_id = payload.get("match_id", "")
    tournament_id = payload.get("tournament_id", "")
    organization_id = payload.get("organization_id", "")
    logger.info("MatchStarted: match_id=%s tournament_id=%s", match_id, tournament_id)

    ctx = await _get_match_context(match_id, tournament_id, organization_id)
    if not ctx:
        logger.warning("MatchStarted: no context found for match %s", match_id)
        return

    from app.services.notification.discord_delivery import get_bot
    bot = get_bot()
    if not bot:
        logger.warning("MatchStarted: bot not available, skipping channel creation")
        return

    # ── Create match channel ──────────────────────────────────────────────────
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match
        from app.services.match.channel_manager import MatchChannelManager
        from app.bot.helpers.formatters import score_prompt_embed
        from app.bot.views.match_channel_view import MatchScoreButtonView
        import discord

        async with AsyncSessionLocal() as session:
            async with session.begin():
                match = await session.get(Match, match_id)
                if not match:
                    return

                mgr = MatchChannelManager(session)
                ch_id = await mgr.create_match_channel(
                    bot=bot,
                    match=match,
                    team1_name=ctx["team1_name"],
                    team2_name=ctx["team2_name"],
                    guild_id_str=ctx["discord_guild_id"],
                    tournament_category_id=ctx.get("tournament_category_id"),
                    staff_role_ids=ctx.get("staff_role_ids"),
                    team1_discord_role_id=ctx.get("team1_discord_role_id"),
                    team2_discord_role_id=ctx.get("team2_discord_role_id"),
                )

                if ch_id:
                    match.private_channel_id = str(ch_id)
                    logger.info("Match %s channel created: %s", match_id[:8], ch_id)

        # Post match info + score button to the channel
        if ch_id:
            async with AsyncSessionLocal() as session:
                match = await session.get(Match, match_id)
                if match:
                    mgr = MatchChannelManager(session)
                    await mgr.post_match_info(
                        bot=bot,
                        channel_id=ch_id,
                        match=match,
                        team1_name=ctx["team1_name"],
                        team2_name=ctx["team2_name"],
                        rules=ctx.get("rules"),
                    )

            # Post score prompt embed with submit button
            ch = bot.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                score_view = MatchScoreButtonView()
                bot.add_view(score_view)
                prompt = score_prompt_embed(
                    team1_name=ctx["team1_name"],
                    team2_name=ctx["team2_name"],
                    round_num=ctx["round"] or 1,
                    match_num=ctx["match_number"] or 1,
                )
                await ch.send(embed=prompt, view=score_view)

    except Exception as exc:
        logger.error("MatchStarted channel creation failed for %s: %s", match_id[:8], exc, exc_info=True)

    # ── DM captains ───────────────────────────────────────────────────────────
    t_name = ctx.get("tournament_name", "the tournament")
    round_num = ctx.get("round") or 1
    match_num = ctx.get("match_number") or 1
    team1_name = ctx["team1_name"]
    team2_name = ctx["team2_name"]

    for discord_id, team_name, opp_name in [
        (ctx.get("team1_captain_discord_id"), team1_name, team2_name),
        (ctx.get("team2_captain_discord_id"), team2_name, team1_name),
    ]:
        if not discord_id:
            continue
        try:
            import discord
            user = await bot.fetch_user(int(discord_id))
            dm_embed = discord.Embed(
                title=f"⚔️ Your Match is Starting! — {t_name}",
                description=(
                    f"**{team1_name}** vs **{team2_name}**\n\n"
                    f"Round **{round_num}** · Match **#{match_num}**\n\n"
                    f"Check your private match channel for details and use the "
                    f"**📝 Submit Score** button once the game is done."
                ),
                color=discord.Color.red(),
            )
            dm_embed.set_footer(text="Good luck! 🏆")
            await user.send(embed=dm_embed)
        except Exception as exc:
            logger.debug("Could not DM captain %s: %s", discord_id, exc)


@event_bus.subscribe("MatchCompleted")
async def on_match_completed(payload: dict) -> None:
    match_id = payload.get("match_id", "")
    tournament_id = payload.get("tournament_id", "")
    organization_id = payload.get("organization_id", "")
    winner_id = payload.get("winner_id")
    logger.info(
        "MatchCompleted: match_id=%s winner=%s",
        match_id, winner_id,
    )

    ctx = await _get_match_context(match_id, tournament_id, organization_id)
    if not ctx:
        return

    from app.services.notification.discord_delivery import get_bot
    bot = get_bot()

    # ── Recalculate standings ─────────────────────────────────────────────────
    try:
        from app.database.session import AsyncSessionLocal
        from app.services.standings.calculator import StandingsCalculator

        async with AsyncSessionLocal() as session:
            async with session.begin():
                calc = StandingsCalculator(session)
                await calc.recalculate(organization_id, tournament_id)
        logger.info("Standings recalculated for tournament %s", tournament_id[:8])
    except Exception as exc:
        logger.warning("Standings recalculation failed for %s: %s", tournament_id[:8], exc)

    # ── Archive match channel ─────────────────────────────────────────────────
    private_ch_id = ctx.get("private_channel_id")
    if bot and private_ch_id:
        try:
            from app.services.match.channel_manager import MatchChannelManager
            from app.database.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                mgr = MatchChannelManager(session)
                await mgr.archive_match_channel(
                    bot=bot,
                    channel_id=int(private_ch_id),
                    winner_name=ctx.get("winner_name"),
                )
        except Exception as exc:
            logger.warning("Could not archive match channel %s: %s", private_ch_id, exc)

    # ── Post results to results channel ──────────────────────────────────────
    if not bot:
        return

    results_ch_id = ctx.get("results_channel_id")
    if results_ch_id:
        try:
            import discord
            from app.bot.helpers.formatters import match_result_embed

            ch = bot.get_channel(int(results_ch_id))
            if isinstance(ch, discord.TextChannel):
                # Fetch fresh match data for scores
                from app.database.session import AsyncSessionLocal
                from app.database.models.match import Match
                async with AsyncSessionLocal() as session:
                    match = await session.get(Match, match_id)

                    def _score_val(raw) -> int:
                        if isinstance(raw, dict):
                            return int(raw.get("score", 0))
                        return int(raw or 0)

                    s1 = _score_val(match.score_team1) if match else 0
                    s2 = _score_val(match.score_team2) if match else 0

                result_embed = match_result_embed(
                    team1_name=ctx["team1_name"],
                    team2_name=ctx["team2_name"],
                    score_team1=s1 or 0,
                    score_team2=s2 or 0,
                    winner_name=ctx.get("winner_name") or "TBD",
                    round_num=ctx.get("round") or 1,
                    match_num=ctx.get("match_number") or 1,
                )
                await ch.send(embed=result_embed)
        except Exception as exc:
            logger.warning("Could not post match result: %s", exc)

    # ── Post updated standings ────────────────────────────────────────────────
    schedule_ch_id = ctx.get("schedule_channel_id")
    if schedule_ch_id:
        try:
            import discord
            from app.bot.helpers.formatters import standings_embed
            from app.database.session import AsyncSessionLocal
            from app.database.models.standings import Standings
            from app.database.models.team import Team
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                sq = (
                    select(Standings)
                    .where(
                        Standings.tournament_id == tournament_id,
                        Standings.organization_id == organization_id,
                    )
                    .order_by(Standings.wins.desc(), Standings.points.desc())
                    .limit(10)
                )
                standings_rows = (await session.execute(sq)).scalars().all()

                standings_list = []
                for i, st in enumerate(standings_rows):
                    team = await session.get(Team, st.team_id)
                    standings_list.append({
                        "rank": i + 1,
                        "team_name": team.name if team else st.team_id[:8],
                        "wins": st.wins,
                        "losses": st.losses,
                        "points": st.points,
                    })

            ch = bot.get_channel(int(schedule_ch_id))
            if isinstance(ch, discord.TextChannel) and standings_list:
                embed = standings_embed(standings_list, ctx.get("tournament_name", "Tournament"))
                await ch.send(embed=embed)
        except Exception as exc:
            logger.warning("Could not post standings update: %s", exc)


@event_bus.subscribe("DisputeOpened")
async def on_dispute_opened(payload: dict) -> None:
    logger.info(
        "Dispute opened: dispute_id=%s type=%s",
        payload.get("dispute_id"),
        payload.get("case_type"),
    )
    t_info = await _get_tournament_info(
        payload.get("tournament_id", ""),
        payload.get("organization_id", ""),
    )
    if t_info.get("staff_alerts_channel_id"):
        from app.services.notification.discord_delivery import notify_dispute_opened
        await notify_dispute_opened(
            dispute_id_short=payload.get("dispute_id", "")[:8],
            tournament_name=t_info.get("name", "Tournament"),
            case_type=payload.get("case_type", "unknown"),
            description=payload.get("description", "A new dispute has been opened."),
            staff_alerts_channel_id=t_info["staff_alerts_channel_id"],
            opener_discord_id=payload.get("opener_discord_id"),
        )


@event_bus.subscribe("TournamentStatusChanged")
async def on_tournament_status_changed(payload: dict) -> None:
    old = payload.get("old_status", "")
    new = payload.get("new_status", "")
    tournament_id = payload.get("tournament_id", "")
    organization_id = payload.get("organization_id", "")
    logger.info(
        "Tournament status changed: tournament_id=%s %s -> %s",
        tournament_id, old, new,
    )
    t_info = await _get_tournament_info(tournament_id, organization_id)
    if t_info.get("announcements_channel_id") and t_info.get("name"):
        from app.services.notification.discord_delivery import notify_tournament_status
        await notify_tournament_status(
            tournament_name=t_info["name"],
            new_status=new,
            announcements_channel_id=t_info["announcements_channel_id"],
            extra_info=payload.get("extra_info"),
        )

    if new in ("completed", "live") and tournament_id and organization_id:
        try:
            from app.database.session import AsyncSessionLocal
            from app.services.snapshot.snapshot_service import SnapshotService
            trigger = "tournament_completed" if new == "completed" else "tournament_live"
            label = f"Auto: {old} → {new}"
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    svc = SnapshotService(s)
                    await svc.take(organization_id, tournament_id, trigger=trigger, label=label)
        except Exception as exc:
            logger.warning("Auto-snapshot failed for tournament %s: %s", tournament_id[:8], exc)


def register_all() -> None:
    """Called at startup to ensure all subscribers are imported and registered."""
    pass
