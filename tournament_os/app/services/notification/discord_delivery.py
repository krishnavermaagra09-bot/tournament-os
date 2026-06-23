"""
Discord Notification Delivery Service.

Stores a single bot reference (set via set_bot() in on_ready) and provides
async helpers for delivering real Discord notifications — DMs, channel embeds,
and announcements — in response to tournament lifecycle events.

Never import the bot class here; only accept the already-constructed instance.
"""
import logging
from typing import Any

import discord

logger = logging.getLogger(__name__)

_bot: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    """Register the running bot instance. Call from on_ready."""
    global _bot
    _bot = bot
    logger.info("Discord notification delivery service: bot registered")


def get_bot() -> discord.Client | None:
    return _bot


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _dm_user(discord_id: str, embed: discord.Embed) -> None:
    if not _bot:
        return
    try:
        user = await _bot.fetch_user(int(discord_id))
        if user:
            await user.send(embed=embed)
    except discord.Forbidden:
        logger.debug("Cannot DM user %s (DMs disabled)", discord_id)
    except Exception as exc:
        logger.warning("Failed to DM user %s: %s", discord_id, exc)


async def _post_to_channel(channel_id: int | str, embed: discord.Embed, content: str | None = None) -> None:
    if not _bot or not channel_id:
        return
    try:
        ch = _bot.get_channel(int(channel_id))
        if ch and isinstance(ch, discord.TextChannel):
            await ch.send(content=content, embed=embed)
    except Exception as exc:
        logger.warning("Failed to post to channel %s: %s", channel_id, exc)


# ── Public delivery functions ─────────────────────────────────────────────────

async def notify_registration_approved(
    discord_id: str,
    tournament_name: str,
    team_name: str | None = None,
) -> None:
    """DM player that their registration was approved."""
    e = discord.Embed(
        title="✅ Registration Approved!",
        description=f"Your registration for **{tournament_name}** has been approved.",
        color=discord.Color.green(),
    )
    if team_name:
        e.add_field(name="Team", value=team_name, inline=True)
    e.set_footer(text="Good luck in the tournament!")
    await _dm_user(discord_id, e)


async def notify_registration_rejected(
    discord_id: str,
    tournament_name: str,
    reason: str | None = None,
) -> None:
    """DM player that their registration was rejected."""
    e = discord.Embed(
        title="❌ Registration Rejected",
        description=f"Your registration for **{tournament_name}** has been rejected.",
        color=discord.Color.red(),
    )
    if reason:
        e.add_field(name="Reason", value=reason, inline=False)
    e.set_footer(text="Contact staff if you believe this is an error.")
    await _dm_user(discord_id, e)


async def notify_match_assigned(
    match_id_short: str,
    round_num: int,
    match_num: int,
    tournament_name: str,
    team1_name: str,
    team2_name: str,
    match_channel_id: int | str | None,
    captain1_discord_id: str | None,
    captain2_discord_id: str | None,
    scheduled_at_str: str | None = None,
) -> None:
    """Notify teams that a match has been assigned — post to channel + DM captains."""
    e = discord.Embed(
        title=f"🎮 Match #{match_num} — Round {round_num}",
        description=f"**{team1_name}** vs **{team2_name}**",
        color=discord.Color.blue(),
    )
    e.add_field(name="Tournament", value=tournament_name, inline=True)
    e.add_field(name="Match ID", value=f"`{match_id_short}`", inline=True)
    if scheduled_at_str:
        e.add_field(name="Scheduled", value=scheduled_at_str, inline=True)
    if match_channel_id:
        e.set_footer(text="Submit your score in the match channel when done.")
    else:
        e.set_footer(text="Use /score to submit your result when done.")

    # Post to match channel
    if match_channel_id:
        await _post_to_channel(match_channel_id, e)

    # DM captains
    for discord_id in filter(None, [captain1_discord_id, captain2_discord_id]):
        await _dm_user(discord_id, e)


async def notify_tournament_status(
    tournament_name: str,
    new_status: str,
    announcements_channel_id: int | str | None,
    extra_info: str | None = None,
) -> None:
    """Post a tournament status announcement to the designated channel."""
    if not announcements_channel_id:
        return

    _STATUS_MAP: dict[str, tuple[str, discord.Color]] = {
        "registration_open":   ("📝 Registration is now **OPEN**! Register now before spots fill up.", discord.Color.green()),
        "registration_closed": ("🔒 Registration has **CLOSED**.", discord.Color.orange()),
        "checkin_open":        ("✅ **Check-In is OPEN!** Click the check-in button to confirm your spot!", discord.Color.green()),
        "checkin_closed":      ("⏰ Check-In has **CLOSED**. Bracket generation in progress…", discord.Color.orange()),
        "live":                ("🚀 The tournament is now **LIVE**! Matches are starting. Good luck!", discord.Color.gold()),
        "under_review":        ("⚖️ The tournament is currently **UNDER REVIEW**.", discord.Color.orange()),
        "completed":           ("🏆 The tournament has **COMPLETED**! Congratulations to all participants!", discord.Color.purple()),
        "cancelled":           ("❌ The tournament has been **CANCELLED**. Refunds / re-entry info will follow.", discord.Color.red()),
    }

    desc, color = _STATUS_MAP.get(
        new_status,
        (f"📢 Tournament status updated: **{new_status.replace('_', ' ').title()}**", discord.Color.blurple()),
    )

    e = discord.Embed(
        title=f"📢 {tournament_name}",
        description=desc,
        color=color,
    )
    if extra_info:
        e.add_field(name="ℹ️ Details", value=extra_info, inline=False)

    await _post_to_channel(announcements_channel_id, e)


async def notify_round_started(
    tournament_name: str,
    round_num: int,
    match_count: int,
    schedule_channel_id: int | str | None,
) -> None:
    """Announce that a new round of matches has been generated."""
    if not schedule_channel_id:
        return

    e = discord.Embed(
        title=f"🎮 Round {round_num} — {match_count} Match{'es' if match_count != 1 else ''} Started",
        description=f"Round {round_num} of **{tournament_name}** is underway!",
        color=discord.Color.blue(),
    )
    e.set_footer(text="Check your match channel for details and submit your score when done.")
    await _post_to_channel(schedule_channel_id, e)


async def notify_dispute_opened(
    dispute_id_short: str,
    tournament_name: str,
    case_type: str,
    description: str,
    staff_alerts_channel_id: int | str | None,
    opener_discord_id: str | None = None,
) -> None:
    """Alert staff that a dispute was opened."""
    e = discord.Embed(
        title=f"⚖️ Dispute Opened — {case_type.replace('_', ' ').title()}",
        description=description[:500],
        color=discord.Color.orange(),
    )
    e.add_field(name="Tournament", value=tournament_name, inline=True)
    e.add_field(name="Case ID", value=f"`{dispute_id_short}`", inline=True)
    e.set_footer(text="Use the Disputes panel in the Control Panel to review.")

    if staff_alerts_channel_id:
        await _post_to_channel(staff_alerts_channel_id, e)


async def notify_tournament_completed(
    tournament_name: str,
    winner_team_name: str | None,
    announcements_channel_id: int | str | None,
    standings_summary: str | None = None,
) -> None:
    """Post the final results when a tournament completes."""
    if not announcements_channel_id:
        return

    e = discord.Embed(
        title=f"🏆 {tournament_name} — Tournament Complete!",
        color=discord.Color.gold(),
    )
    if winner_team_name:
        e.description = f"🥇 **Winner: {winner_team_name}**\n\nCongratulations to all participants!"
    else:
        e.description = "🏆 The tournament has concluded! Congratulations to all participants!"

    if standings_summary:
        e.add_field(name="📊 Final Standings", value=standings_summary[:1000], inline=False)

    await _post_to_channel(announcements_channel_id, e)
