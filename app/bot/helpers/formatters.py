"""
Discord message formatting helpers — top-class embed UI.
"""
import discord
from datetime import datetime, timezone


# ── Timestamp helper ──────────────────────────────────────────────────────────

def _discord_ts(dt: datetime | None, style: str = "F") -> str:
    """Return a Discord timestamp string <t:UNIX:style> or 'Not set'."""
    if not dt:
        return "Not set"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"<t:{int(dt.timestamp())}:{style}>"


# ── Status helpers ────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "draft":               discord.Color.from_str("#4B5563"),  # grey
    "scheduled":           discord.Color.from_str("#6366F1"),  # indigo
    "registration_open":   discord.Color.from_str("#10B981"),  # emerald
    "registration_closed": discord.Color.from_str("#F59E0B"),  # amber
    "checkin_open":        discord.Color.from_str("#3B82F6"),  # blue
    "checkin_closed":      discord.Color.from_str("#F97316"),  # orange
    "live":                discord.Color.from_str("#EF4444"),  # red
    "under_review":        discord.Color.from_str("#8B5CF6"),  # violet
    "completed":           discord.Color.from_str("#6B7280"),  # grey
    "cancelled":           discord.Color.from_str("#1F2937"),  # dark
    "archived":            discord.Color.from_str("#374151"),  # dark grey
}

_STATUS_ICON = {
    "draft":               "📝",
    "scheduled":           "📅",
    "registration_open":   "📋",
    "registration_closed": "🔒",
    "checkin_open":        "✅",
    "checkin_closed":      "⏰",
    "live":                "🔴",
    "under_review":        "🔍",
    "completed":           "🏁",
    "cancelled":           "❌",
    "archived":            "📦",
}

_FORMAT_ICON = {
    "single_elimination":  "🗡️ Single Elimination",
    "double_elimination":  "⚔️ Double Elimination",
    "swiss":               "🔄 Swiss",
    "round_robin":         "🔁 Round Robin",
    "group_stage":         "👥 Group Stage",
    "battle_royale":       "💥 Battle Royale",
}


def _status_color(status_val: str) -> discord.Color:
    return _STATUS_COLOR.get(status_val, discord.Color.blurple())


def _status_icon(status_val: str) -> str:
    return _STATUS_ICON.get(status_val, "🏆")


# ── Tournament embed ──────────────────────────────────────────────────────────

def tournament_embed(tournament) -> discord.Embed:
    sv = tournament.status.value
    icon = _status_icon(sv)
    label = sv.replace("_", " ").title()

    embed = discord.Embed(
        title=f"🏆 {tournament.name}",
        description=tournament.description or "*No description provided.*",
        color=_status_color(sv),
    )

    fmt_val = tournament.format.value if tournament.format else "unknown"
    embed.add_field(
        name="🎮 Game",
        value=f"**{tournament.game}**" if tournament.game else "Not set",
        inline=True,
    )
    embed.add_field(
        name="📐 Format",
        value=_FORMAT_ICON.get(fmt_val, fmt_val.replace("_", " ").title()),
        inline=True,
    )
    embed.add_field(
        name="⚡ Status",
        value=f"{icon} **{label}**",
        inline=True,
    )

    if tournament.prize_pool:
        embed.add_field(name="🏅 Prize Pool", value=f"**{tournament.prize_pool}**", inline=True)
    if tournament.max_teams:
        embed.add_field(name="👥 Max Teams", value=str(tournament.max_teams), inline=True)
    if tournament.region:
        embed.add_field(name="🌐 Region", value=tournament.region, inline=True)
    if tournament.platform:
        embed.add_field(name="🖥️ Platform", value=tournament.platform, inline=True)

    # Timeline
    timeline_parts: list[str] = []
    if tournament.registration_open_at:
        timeline_parts.append(f"📋 Reg opens: {_discord_ts(tournament.registration_open_at, 'f')}")
    if tournament.registration_close_at:
        timeline_parts.append(f"🔒 Reg closes: {_discord_ts(tournament.registration_close_at, 'f')}")
    if tournament.checkin_open_at:
        timeline_parts.append(f"✅ Check-in: {_discord_ts(tournament.checkin_open_at, 'f')}")
    if tournament.match_start_at:
        timeline_parts.append(f"🎮 Matches start: {_discord_ts(tournament.match_start_at, 'f')}")
    if timeline_parts:
        embed.add_field(name="📅 Timeline", value="\n".join(timeline_parts), inline=False)

    embed.set_footer(text=f"ID: {tournament.id[:8]}  •  🤖 Autonomous: {'ON' if tournament.autonomous_mode else 'OFF'}")
    return embed


# ── Registration embed ────────────────────────────────────────────────────────

def registration_embed(registration, status_override: str | None = None) -> discord.Embed:
    status = status_override or registration.status.value
    color_map = {
        "pending":            discord.Color.from_str("#F59E0B"),
        "auto_approved":      discord.Color.from_str("#10B981"),
        "manually_approved":  discord.Color.from_str("#10B981"),
        "rejected":           discord.Color.from_str("#EF4444"),
        "flagged":            discord.Color.from_str("#F97316"),
        "changes_requested":  discord.Color.from_str("#F97316"),
        "hold":               discord.Color.from_str("#6B7280"),
        "waitlisted":         discord.Color.from_str("#6366F1"),
    }
    icon_map = {
        "pending":           "⏳",
        "auto_approved":     "✅",
        "manually_approved": "✅",
        "rejected":          "❌",
        "flagged":           "🚩",
        "changes_requested": "✏️",
        "hold":              "⏸️",
        "waitlisted":        "🕐",
    }
    icon = icon_map.get(status, "📋")
    label = status.replace("_", " ").title()
    embed = discord.Embed(
        title=f"{icon} Registration — {label}",
        color=color_map.get(status, discord.Color.blurple()),
    )
    embed.add_field(name="Status",          value=f"**{label}**",        inline=True)
    embed.add_field(name="Registration ID", value=f"`{registration.id[:8]}`", inline=True)
    if registration.rejection_reason:
        embed.add_field(name="📋 Reason", value=registration.rejection_reason, inline=False)
    if registration.notes:
        embed.add_field(name="📝 Staff Notes", value=registration.notes[:200], inline=False)
    submitted = _discord_ts(registration.created_at, style="R")
    embed.set_footer(text=f"Submitted {submitted}")
    return embed


# ── Match embed ───────────────────────────────────────────────────────────────

def match_embed(match, team1_name: str = "Team 1", team2_name: str = "Team 2") -> discord.Embed:
    status_map = {
        "live":           (discord.Color.from_str("#EF4444"), "🔴 Live"),
        "completed":      (discord.Color.from_str("#10B981"), "✅ Completed"),
        "scheduled":      (discord.Color.from_str("#3B82F6"), "📅 Scheduled"),
        "awaiting_score": (discord.Color.from_str("#F59E0B"), "⏳ Awaiting Score"),
        "disputed":       (discord.Color.from_str("#F97316"), "⚖️ Disputed"),
        "voided":         (discord.Color.from_str("#6B7280"), "🚫 Voided"),
    }
    color, status_label = status_map.get(match.status.value, (discord.Color.blurple(), match.status.value.replace("_", " ").title()))

    embed = discord.Embed(
        title=f"⚔️ Match — Round {match.round or '?'} · #{match.match_number or '?'}",
        color=color,
    )
    embed.add_field(name="🔵 Team 1", value=f"**{team1_name}**", inline=True)
    embed.add_field(name="⚔️",        value="**vs**",            inline=True)
    embed.add_field(name="🔴 Team 2", value=f"**{team2_name}**", inline=True)
    embed.add_field(name="Status", value=status_label, inline=True)

    if match.scheduled_at:
        embed.add_field(name="🕐 Scheduled", value=_discord_ts(match.scheduled_at, "f"), inline=True)

    def _sv(raw) -> int:
        if isinstance(raw, dict):
            return int(raw.get("score", 0))
        return int(raw or 0)

    if match.score_team1 and match.score_team2:
        embed.add_field(
            name="📊 Score",
            value=f"**{_sv(match.score_team1)}** — **{_sv(match.score_team2)}**",
            inline=True,
        )

    if match.winner_id:
        winner = team1_name if match.winner_id == match.team1_id else team2_name
        embed.add_field(name="🏆 Winner", value=f"**{winner}**", inline=False)

    embed.set_footer(text=f"Match ID: {match.id[:8]}")
    return embed


# ── Match result embed (posted in match channel after score confirmed) ─────────

def match_result_embed(
    team1_name: str,
    team2_name: str,
    score_team1: int,
    score_team2: int,
    winner_name: str,
    round_num: int,
    match_num: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="🏆 Match Result Confirmed",
        color=discord.Color.from_str("#10B981"),
    )
    embed.description = (
        f"**Round {round_num} · Match #{match_num}**\n\n"
        f"🔵 **{team1_name}** `{score_team1}` — `{score_team2}` **{team2_name}** 🔴\n\n"
        f"🏆 Winner: **{winner_name}**"
    )
    embed.set_footer(text="GG! The winner advances to the next round.")
    return embed


# ── Standings embed ───────────────────────────────────────────────────────────

def standings_embed(standings_list: list, tournament_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 Live Standings — {tournament_name}",
        color=discord.Color.from_str("#F59E0B"),
    )
    if not standings_list:
        embed.description = "No standings yet — matches in progress."
        return embed

    lines: list[str] = []
    for s in standings_list[:20]:
        rank = s.get("rank")
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        rank_display = medals.get(rank, f"**#{rank or '?'}**")
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        points = s.get("points", 0)
        name = s.get("team_name", "Unknown")
        lines.append(f"{rank_display} **{name}** · {wins}W {losses}L · {points} pts")

    embed.description = "\n".join(lines)
    embed.set_footer(text="Updated after every match result")
    return embed


# ── Round summary embed ───────────────────────────────────────────────────────

def round_complete_embed(
    tournament_name: str,
    round_num: int,
    next_round_num: int,
    match_count: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"⏩ Round {round_num} Complete!",
        description=(
            f"All **{match_count}** match{'es' if match_count != 1 else ''} in Round {round_num} "
            f"of **{tournament_name}** are done.\n\n"
            f"Round **{next_round_num}** is now being generated — match channels will appear shortly."
        ),
        color=discord.Color.from_str("#6366F1"),
    )
    embed.set_footer(text="🤖 Autonomous Engine · Results auto-processed")
    return embed


# ── Tournament complete embed ─────────────────────────────────────────────────

def tournament_complete_embed(
    tournament_name: str,
    winner_name: str | None,
    standings_summary: str | None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏁 Tournament Complete — {tournament_name}",
        color=discord.Color.from_str("#10B981"),
    )
    if winner_name:
        embed.description = f"🏆 **{winner_name}** wins the tournament! Congratulations!"
    else:
        embed.description = "Tournament has concluded!"

    if standings_summary:
        embed.add_field(name="🏅 Final Standings", value=standings_summary, inline=False)

    embed.set_footer(text="Thank you to all participants!")
    return embed


# ── Score prompt embed (pinned in match channels) ─────────────────────────────

def score_prompt_embed(
    team1_name: str,
    team2_name: str,
    round_num: int,
    match_num: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📝 Submit Your Score — Round {round_num} · Match #{match_num}",
        description=(
            f"**{team1_name}** vs **{team2_name}**\n\n"
            "Both team captains must submit matching scores to confirm the result.\n"
            "If scores disagree, a dispute will be opened automatically.\n\n"
            "Use the button below to submit your team's score."
        ),
        color=discord.Color.from_str("#3B82F6"),
    )
    embed.set_footer(text="💡 Tip: Use /match score if the button is unavailable")
    return embed


# ── Bracket progress embed ────────────────────────────────────────────────────

def bracket_progress_embed(
    tournament_name: str,
    current_round: int,
    total_rounds: int | None,
    teams_remaining: int,
) -> discord.Embed:
    progress = ""
    if total_rounds:
        done = current_round - 1
        remaining = total_rounds - done
        bar_filled = "█" * done
        bar_empty = "░" * remaining
        pct = int((done / total_rounds) * 100) if total_rounds else 0
        progress = f"\n`{bar_filled}{bar_empty}` {pct}% complete"

    embed = discord.Embed(
        title=f"🏆 Bracket Update — {tournament_name}",
        description=(
            f"**Round {current_round}** is now underway.{progress}\n\n"
            f"👥 Teams remaining: **{teams_remaining}**"
        ),
        color=discord.Color.from_str("#EF4444"),
    )
    embed.set_footer(text="🤖 Auto-generated · Autonomous Mode")
    return embed


# ── Utility embeds ────────────────────────────────────────────────────────────

def error_embed(message: str, title: str = "❌ Error") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.from_str("#EF4444"))


def success_embed(message: str, title: str = "✅ Success") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.from_str("#10B981"))


def info_embed(message: str, title: str = "ℹ️ Info") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.from_str("#3B82F6"))


def warning_embed(message: str, title: str = "⚠️ Warning") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.from_str("#F59E0B"))
