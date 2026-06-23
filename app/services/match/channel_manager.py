"""
Match Channel Manager — 2.0 feature.

Before each match starts, automatically create a private text channel
visible only to the two competing teams and staff.

Channel name format:  match-{teamA-slug}-vs-{teamB-slug}
                      e.g.  match-team-alpha-vs-team-bravo

After match completion, the channel is archived (locked + renamed).
"""
import logging
import re

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.match import Match

logger = logging.getLogger(__name__)


def _slug(text: str, max_len: int = 20) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")[:max_len] or "team"


class MatchChannelManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_match_channel(
        self,
        bot: discord.Client,
        match: Match,
        team1_name: str,
        team2_name: str,
        guild_id_str: str,
        tournament_category_id: str | None,
        staff_role_ids: dict | None = None,
        team1_discord_role_id: str | None = None,
        team2_discord_role_id: str | None = None,
    ) -> int | None:
        """
        Create a private match channel. Returns the Discord channel ID or None on failure.
        """
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            logger.warning("MatchChannelManager: guild %s not found", guild_id_str)
            return None

        ch_name = f"🎮-match-{_slug(team1_name)}-vs-{_slug(team2_name)}"[:100]

        everyone = guild.default_role
        overwrites: dict = {everyone: discord.PermissionOverwrite(view_channel=False)}

        # Staff roles
        for key in ("tournament_admin", "tournament_manager", "referee"):
            rid = (staff_role_ids or {}).get(key)
            if rid:
                role = guild.get_role(int(rid))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True,
                    )

        # Team roles (if Discord roles were created for the teams)
        for role_id in filter(None, [team1_discord_role_id, team2_discord_role_id]):
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        category = None
        if tournament_category_id:
            cat = guild.get_channel(int(tournament_category_id))
            if isinstance(cat, discord.CategoryChannel):
                category = cat

        try:
            ch = await guild.create_text_channel(
                name=ch_name,
                category=category,
                topic=f"Match room — {team1_name} vs {team2_name} | Round {match.round} #{match.match_number}",
                overwrites=overwrites,
                reason=f"Tournament OS: match {match.id[:8]}",
            )
            logger.info(
                "Match channel created: %s (id=%s) for match %s",
                ch.name, ch.id, match.id[:8],
            )
            return ch.id
        except discord.HTTPException as exc:
            logger.error("Failed to create match channel for match %s: %s", match.id[:8], exc)
            return None

    async def post_match_info(
        self,
        bot: discord.Client,
        channel_id: int,
        match: Match,
        team1_name: str,
        team2_name: str,
        rules: str | None = None,
    ) -> None:
        """Post match info embed to the match channel."""
        ch = bot.get_channel(channel_id)
        if not isinstance(ch, discord.TextChannel):
            return

        e = discord.Embed(
            title=f"🎮 Match #{match.match_number} — Round {match.round}",
            color=discord.Color.blue(),
        )
        e.add_field(name="🔵 Team 1", value=team1_name, inline=True)
        e.add_field(name="🔴 Team 2", value=team2_name, inline=True)
        e.add_field(name="Status", value=match.status.value.replace("_", " ").title(), inline=True)
        if rules:
            e.add_field(name="📜 Match Rules", value=rules[:500], inline=False)
        e.set_footer(text=f"Match ID: {match.id[:8]} | Submit your score using /score or the score button")

        try:
            await ch.send(embed=e)
        except discord.HTTPException as exc:
            logger.warning("Failed to post match info to channel %s: %s", channel_id, exc)

    async def archive_match_channel(
        self,
        bot: discord.Client,
        channel_id: int,
        winner_name: str | None = None,
    ) -> None:
        """Lock and archive a match channel after the match completes."""
        ch = bot.get_channel(channel_id)
        if not isinstance(ch, discord.TextChannel):
            return

        try:
            await ch.set_permissions(ch.guild.default_role, send_messages=False)
            new_name = f"📦-{ch.name.lstrip('🎮-')}"[:100]
            await ch.edit(name=new_name)
            if winner_name:
                await ch.send(
                    embed=discord.Embed(
                        title="✅ Match Complete",
                        description=f"**Winner: {winner_name}**\nThis channel has been archived.",
                        color=discord.Color.green(),
                    )
                )
        except discord.HTTPException as exc:
            logger.warning("Failed to archive match channel %s: %s", channel_id, exc)
