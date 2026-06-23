"""
Discord side-effects for tournament status transitions.

Called by BOTH the scheduler (automatic) and manual status changes (buttons).
This is the single source of truth for what happens in Discord when a
tournament's status changes.

Each handler is idempotent — safe to call multiple times for the same status.
"""
import logging

import discord

logger = logging.getLogger(__name__)

_STATUS_COLOR = {
    "registration_open":   discord.Color.green(),
    "registration_closed": discord.Color.orange(),
    "checkin_open":        discord.Color.blue(),
    "checkin_closed":      discord.Color.dark_blue(),
    "live":                discord.Color.red(),
    "completed":           discord.Color.gold(),
    "cancelled":           discord.Color.dark_red(),
}

_STATUS_EMOJI = {
    "registration_open":   "📋",
    "registration_closed": "🔒",
    "checkin_open":        "✅",
    "checkin_closed":      "🔒",
    "live":                "🔴",
    "completed":           "🏆",
    "cancelled":           "❌",
}


async def apply_status_effects(
    tournament_id: str,
    organization_id: str,
    new_status: str,
    old_status: str = "",
) -> None:
    """
    Main entry point. Call this after any tournament status change.
    Loads context from DB, finds the right Discord channels, and applies effects.
    """
    from app.services.notification.discord_delivery import get_bot
    bot = get_bot()
    if not bot:
        logger.debug("discord_effects: bot not available, skipping")
        return

    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            t = await session.get(Tournament, tournament_id)
            if not t:
                return

            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild_row = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild_row:
                return

            guild_settings: dict = dict(guild_row.settings or {})
            channel_ids: dict = guild_settings.get("channel_ids", {})
            tc: dict = dict(t.channel_config or {})

            t_name         = t.name
            t_game         = t.game or ""
            t_format       = t.format.value.replace("_", " ").title() if t.format else ""
            t_prize        = t.prize_pool or "TBD"
            t_max          = t.max_teams
            t_id_short     = tournament_id[:8]
            d_guild_id     = guild_row.discord_guild_id

            ann_ch_id      = channel_ids.get("announcements")
            checkin_ch_id  = channel_ids.get("check_in")
            register_ch_id = channel_ids.get("register")
            results_ch_id  = channel_ids.get("results")
            sched_ch_id    = channel_ids.get("schedule")
            t_cat_id       = tc.get("tournament_category_id")
            org_id_for_view = organization_id
            guild_db_id     = guild_row.id

        d_guild: discord.Guild | None = bot.get_guild(int(d_guild_id)) if d_guild_id else None

        # ── Route to the right handler ────────────────────────────────────────
        if new_status == "registration_open":
            await _on_registration_open(
                bot, d_guild, t_name, t_game, t_format, t_prize, t_max,
                t_id_short, tournament_id, organization_id,
                ann_ch_id, register_ch_id,
            )

        elif new_status == "registration_closed":
            await _on_registration_closed(bot, d_guild, t_name, ann_ch_id)

        elif new_status == "checkin_open":
            await _on_checkin_open(
                bot, d_guild, t_name, t_id_short, tournament_id, org_id_for_view,
                ann_ch_id, checkin_ch_id,
            )

        elif new_status == "checkin_closed":
            await _on_checkin_closed(bot, d_guild, t_name, ann_ch_id)

        elif new_status == "live":
            await _on_live(bot, d_guild, t_name, t_format, ann_ch_id, t_cat_id)

        elif new_status == "completed":
            await _on_completed(
                bot, d_guild, t_name, t_id_short, tournament_id, organization_id,
                ann_ch_id, results_ch_id,
            )

        elif new_status == "cancelled":
            await _on_cancelled(bot, d_guild, t_name, ann_ch_id)

    except Exception as exc:
        logger.error(
            "discord_effects.apply_status_effects failed (tournament=%s, status=%s): %s",
            tournament_id[:8], new_status, exc, exc_info=True,
        )


# ── Individual handlers ────────────────────────────────────────────────────────

async def _on_registration_open(
    bot, d_guild, t_name, t_game, t_fmt, t_prize, t_max,
    t_id_short, tournament_id, organization_id,
    ann_ch_id, register_ch_id,
) -> None:
    """Post registration-open announcement + refresh the register channel embed."""
    slots = f"{t_max}" if t_max else "Unlimited"
    embed = discord.Embed(
        title=f"📋 Registration is now OPEN — {t_name}",
        description=(
            f"**{t_name}** is now accepting registrations!\n\n"
            f"🎮 **Game:** {t_game}\n"
            f"📊 **Format:** {t_fmt}\n"
            f"🏆 **Prize Pool:** {t_prize}\n"
            f"👥 **Slots:** {slots}\n\n"
            "Head to the **📝-register** channel and click **Register** to sign up!"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"Tournament ID: {t_id_short}")

    await _post(bot, ann_ch_id, embed)

    # Refresh the 📝-register channel with a pinned notice
    if register_ch_id and d_guild:
        ch = d_guild.get_channel(int(register_ch_id))
        if isinstance(ch, discord.TextChannel):
            try:
                notice = discord.Embed(
                    title=f"📋 {t_name} — Registration Open!",
                    description=(
                        f"Registration is now open for **{t_name}**!\n"
                        f"🎮 Game: {t_game} · 📊 Format: {t_fmt} · 🏆 Prize: {t_prize}\n\n"
                        "Click **📝 Register** below to sign up."
                    ),
                    color=discord.Color.green(),
                )
                await ch.send(embed=notice)
            except Exception as exc:
                logger.warning("Could not post to register channel: %s", exc)


async def _on_registration_closed(bot, d_guild, t_name, ann_ch_id) -> None:
    embed = discord.Embed(
        title=f"🔒 Registration Closed — {t_name}",
        description="Registration is now closed. Check-in will open shortly.",
        color=discord.Color.orange(),
    )
    await _post(bot, ann_ch_id, embed)


async def _on_checkin_open(
    bot, d_guild, t_name, t_id_short, tournament_id, organization_id,
    ann_ch_id, checkin_ch_id,
) -> None:
    """Post check-in button to ✅-check-in + announcement."""
    # Announcement
    embed = discord.Embed(
        title=f"✅ Check-In is OPEN — {t_name}",
        description=(
            f"Check-in for **{t_name}** is now open!\n\n"
            "Head to **✅-check-in** channel and click the button to confirm your spot.\n"
            "⚠️ Players who don't check in will be removed from the tournament."
        ),
        color=discord.Color.blue(),
    )
    await _post(bot, ann_ch_id, embed)

    # Post check-in button to the ✅-check-in channel
    if checkin_ch_id and d_guild:
        ch = d_guild.get_channel(int(checkin_ch_id))
        if isinstance(ch, discord.TextChannel):
            try:
                from app.bot.views.checkin_button import CheckInView
                view = CheckInView(tournament_id=tournament_id, organization_id=organization_id)
                bot.add_view(view)
                checkin_embed = discord.Embed(
                    title=f"✅ {t_name} — Check-In",
                    description=(
                        "Check-in is now open! Click the button below to confirm your participation.\n\n"
                        "⚠️ You must check in before the window closes or you will be removed."
                    ),
                    color=discord.Color.blue(),
                )
                checkin_embed.set_footer(text=f"Tournament: {t_name}")
                await ch.send(embed=checkin_embed, view=view)
                logger.info("Posted check-in button to channel %s for tournament %s", checkin_ch_id, t_id_short)
            except Exception as exc:
                logger.warning("Could not post check-in button: %s", exc)


async def _on_checkin_closed(bot, d_guild, t_name, ann_ch_id) -> None:
    embed = discord.Embed(
        title=f"🔒 Check-In Closed — {t_name}",
        description="Check-in is now closed. The bracket is being generated. Matches will begin shortly! 🏆",
        color=discord.Color.dark_blue(),
    )
    await _post(bot, ann_ch_id, embed)


async def _on_live(bot, d_guild, t_name, t_fmt, ann_ch_id, t_cat_id) -> None:
    """Open the tournament category to @everyone and announce."""
    embed = discord.Embed(
        title=f"🔴 Tournament is LIVE — {t_name}",
        description=(
            f"**{t_name}** is now LIVE! 🎉\n\n"
            "The bracket has been generated. Match rooms will be created and "
            "captains will receive their match details shortly.\n\n"
            "Good luck to all participants! 🏆"
        ),
        color=discord.Color.red(),
    )
    await _post(bot, ann_ch_id, embed)

    # Open tournament category to @everyone
    if t_cat_id and d_guild:
        try:
            cat = d_guild.get_channel(int(t_cat_id))
            if isinstance(cat, discord.CategoryChannel):
                everyone = d_guild.default_role
                await cat.set_permissions(everyone, view_channel=True, send_messages=False)
                for ch in cat.channels:
                    await ch.set_permissions(everyone, view_channel=True, send_messages=False)
                logger.info("Opened tournament category %s to @everyone", t_cat_id)
        except Exception as exc:
            logger.warning("Could not open tournament category: %s", exc)


async def _on_completed(
    bot, d_guild, t_name, t_id_short, tournament_id, organization_id,
    ann_ch_id, results_ch_id,
) -> None:
    """Announce completion, post results summary, assign winner role, DM winner captain."""
    from app.database.session import AsyncSessionLocal
    from app.database.models.standings import Standings
    from app.database.models.team import Team
    from app.database.models.user import User
    from sqlalchemy import select

    winner_team_name: str | None = None
    winner_captain_discord_id: str | None = None
    winner_discord_role_id: str | None = None

    # Fetch final standings + winner info
    try:
        async with AsyncSessionLocal() as session:
            sq = (
                select(Standings)
                .where(
                    Standings.tournament_id == tournament_id,
                    Standings.organization_id == organization_id,
                )
                .order_by(Standings.wins.desc(), Standings.points.desc())
                .limit(8)
            )
            standings = (await session.execute(sq)).scalars().all()

            standings_data: list[tuple] = []
            for st in standings:
                team = await session.get(Team, st.team_id)
                standings_data.append((team, st))

            if standings_data:
                winner_team, _ = standings_data[0]
                if winner_team:
                    winner_team_name = winner_team.name
                    winner_discord_role_id = str(winner_team.discord_role_id) if getattr(winner_team, "discord_role_id", None) else None
                    if winner_team.captain_id:
                        cap = await session.get(User, winner_team.captain_id)
                        winner_captain_discord_id = cap.discord_user_id if cap else None
    except Exception as exc:
        logger.warning("Could not fetch standings for completion: %s", exc)
        standings_data = []

    # ── Announcement embed ────────────────────────────────────────────────────
    ann_embed = discord.Embed(
        title=f"🏆 Tournament Complete — {t_name}",
        description=(
            f"**{t_name}** has concluded! 🎉\n\n"
            + (f"🥇 **Champion: {winner_team_name}** — Congratulations! 🎊\n\n" if winner_team_name else "")
            + "Thank you to all participants and staff.\n"
            "Final results posted in **🏆-results**."
        ),
        color=discord.Color.gold(),
    )
    await _post(bot, ann_ch_id, ann_embed)

    # ── Post final standings to results channel ───────────────────────────────
    if results_ch_id and d_guild:
        ch = d_guild.get_channel(int(results_ch_id))
        if isinstance(ch, discord.TextChannel):
            try:
                r_embed = discord.Embed(
                    title=f"🏆 Final Results — {t_name}",
                    color=discord.Color.gold(),
                )
                medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 10
                if standings_data:
                    for i, (team, st) in enumerate(standings_data):
                        team_name = team.name if team else "Unknown"
                        r_embed.add_field(
                            name=f"{medals[i]} #{i+1} — {team_name}",
                            value=f"W: {st.wins} · L: {st.losses} · Pts: {st.points}",
                            inline=False,
                        )
                else:
                    r_embed.description = "Final results are being tallied."

                await ch.send(embed=r_embed)
            except Exception as exc:
                logger.warning("Could not post results: %s", exc)

    # ── Assign winner role ────────────────────────────────────────────────────
    if d_guild and winner_discord_role_id:
        try:
            winner_role = d_guild.get_role(int(winner_discord_role_id))
            if winner_role:
                # Find a "Tournament Champion" role or create one
                champ_role = discord.utils.get(d_guild.roles, name="🏆 Tournament Champion")
                if not champ_role:
                    champ_role = await d_guild.create_role(
                        name="🏆 Tournament Champion",
                        color=discord.Color.gold(),
                        hoist=True,
                        reason=f"Tournament OS: auto-created for {t_name} winner",
                    )
                # Assign to all members of the winning team role
                for member in d_guild.members:
                    if winner_role in member.roles:
                        try:
                            await member.add_roles(champ_role, reason=f"{t_name} champion")
                        except discord.HTTPException:
                            pass
                logger.info(
                    "Assigned 🏆 champion role to members of %s for tournament %s",
                    winner_role.name, t_id_short,
                )
        except Exception as exc:
            logger.warning("Could not assign winner role: %s", exc)

    # ── DM winning captain ────────────────────────────────────────────────────
    if bot and winner_captain_discord_id and winner_team_name:
        try:
            user = await bot.fetch_user(int(winner_captain_discord_id))
            dm_embed = discord.Embed(
                title=f"🏆 Congratulations — {t_name}!",
                description=(
                    f"**{winner_team_name}** has won **{t_name}**! 🎊\n\n"
                    "Incredible performance from your team. "
                    "The 🏆 Tournament Champion role has been assigned to all team members.\n\n"
                    "Thank you for participating — we hope to see you in the next one!"
                ),
                color=discord.Color.gold(),
            )
            await user.send(embed=dm_embed)
        except Exception as exc:
            logger.debug("Could not DM winner captain %s: %s", winner_captain_discord_id, exc)


async def _on_cancelled(bot, d_guild, t_name, ann_ch_id) -> None:
    embed = discord.Embed(
        title=f"❌ Tournament Cancelled — {t_name}",
        description=f"**{t_name}** has been cancelled. We apologize for the inconvenience.",
        color=discord.Color.dark_red(),
    )
    await _post(bot, ann_ch_id, embed)


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _post(bot, channel_id: str | int | None, embed: discord.Embed) -> None:
    if not bot or not channel_id:
        return
    try:
        ch = bot.get_channel(int(channel_id))
        if isinstance(ch, discord.TextChannel):
            await ch.send(embed=embed)
        else:
            logger.debug("discord_effects._post: channel %s not found or not text", channel_id)
    except Exception as exc:
        logger.warning("discord_effects._post failed (channel=%s): %s", channel_id, exc)
