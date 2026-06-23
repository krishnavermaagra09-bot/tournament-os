"""
Team Hub Service — 2.0 feature.

When a team is approved, automatically create a private Discord category
with dedicated channels visible only to team members, captains, and staff.

Category structure:
  🏅 Team Name
    ├── 💬 team-chat
    ├── 🧠 strategy-room
    ├── 📋 lineup
    ├── 📜 match-history
    └── 🔊 team-voice (optional)
"""
import logging
import re

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.team import Team
from app.database.models.tournament import Tournament

logger = logging.getLogger(__name__)


def _slug(text: str, max_len: int = 90) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")[:max_len] or "team"


class TeamHubService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def provision(
        self,
        bot: discord.Client,
        tournament: Tournament,
        team: Team,
        hub_config: dict,
    ) -> dict:
        """
        Create a private Discord category + channels for an approved team.

        hub_config keys:
          enabled (bool)          — master switch
          create_voice (bool)     — whether to create a voice channel
          guild_id (str)          — Discord guild ID (snowflake string)
          staff_role_ids (dict)   — {role_key: snowflake_string}

        Returns a dict with channel/category IDs that can be stored on the Team.
        """
        guild_id_str = hub_config.get("guild_id") or (tournament.channel_config or {}).get("guild_discord_id")
        if not guild_id_str:
            logger.warning("TeamHubService: no guild_id in hub_config — skipping hub creation")
            return {}

        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            logger.warning("TeamHubService: guild %s not found in bot cache", guild_id_str)
            return {}

        create_voice: bool = hub_config.get("create_voice", False)
        staff_role_ids: dict = hub_config.get("staff_role_ids", {})

        everyone = guild.default_role
        overwrites: dict = {everyone: discord.PermissionOverwrite(view_channel=False)}

        # Grant staff roles full access
        for key in ("tournament_admin", "tournament_manager", "referee"):
            rid = staff_role_ids.get(key)
            if rid:
                role = guild.get_role(int(rid))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True,
                    )

        category_name = f"🏅 {team.name}"[:100]
        try:
            category = await guild.create_category(
                name=category_name,
                overwrites=overwrites,
                reason=f"Tournament OS: team hub for {team.name}",
            )
        except discord.HTTPException as exc:
            logger.error("Failed to create team hub category for %s: %s", team.name, exc)
            return {}

        channels_created: dict[str, int] = {"category_id": category.id}

        text_channels = [
            ("💬-team-chat",    "Team communication channel"),
            ("🧠-strategy-room", "Match strategy and planning"),
            ("📋-lineup",        "Roster and lineup management"),
            ("📜-match-history", "Completed match results"),
        ]

        for ch_name, topic in text_channels:
            try:
                ch = await guild.create_text_channel(
                    name=ch_name,
                    category=category,
                    topic=topic,
                    reason=f"Tournament OS: team hub for {team.name}",
                )
                key = ch_name.split("-", 1)[-1].replace("-", "_").strip()
                channels_created[f"ch_{key}"] = ch.id
            except discord.HTTPException as exc:
                logger.warning("Failed to create channel %s: %s", ch_name, exc)

        if create_voice:
            try:
                vc = await guild.create_voice_channel(
                    name="🔊 Team Voice",
                    category=category,
                    reason=f"Tournament OS: team hub voice for {team.name}",
                )
                channels_created["voice_channel_id"] = vc.id
            except discord.HTTPException as exc:
                logger.warning("Failed to create voice channel for %s: %s", team.name, exc)

        logger.info(
            "Team hub created for team %s in guild %s (category %s)",
            team.id, guild_id_str, category.id,
        )
        return channels_created

    async def add_member(
        self,
        bot: discord.Client,
        hub_channels: dict,
        discord_user_id: str,
        guild_id_str: str,
    ) -> None:
        """Grant a Discord user access to an existing team hub category."""
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            return
        member = guild.get_member(int(discord_user_id))
        if not member:
            try:
                member = await guild.fetch_member(int(discord_user_id))
            except discord.NotFound:
                return

        category_id = hub_channels.get("category_id")
        if not category_id:
            return
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return

        try:
            await category.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Failed to add member %s to team hub: %s", discord_user_id, exc)

    async def remove_member(
        self,
        bot: discord.Client,
        hub_channels: dict,
        discord_user_id: str,
        guild_id_str: str,
    ) -> None:
        """Revoke a Discord user's access to a team hub."""
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            return
        member = guild.get_member(int(discord_user_id))
        if not member:
            return
        category_id = hub_channels.get("category_id")
        if not category_id:
            return
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return
        try:
            await category.set_permissions(member, overwrite=None)
        except discord.HTTPException as exc:
            logger.warning("Failed to remove member %s from team hub: %s", discord_user_id, exc)

    async def archive_hub(
        self,
        bot: discord.Client,
        hub_channels: dict,
        guild_id_str: str,
    ) -> None:
        """Lock all team hub channels after tournament ends."""
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            return
        category_id = hub_channels.get("category_id")
        if not category_id:
            return
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return
        try:
            await category.edit(name=f"📦 {category.name.lstrip('🏅 ')}")
            for ch in category.channels:
                if isinstance(ch, discord.TextChannel):
                    await ch.set_permissions(guild.default_role, send_messages=False)
        except discord.HTTPException as exc:
            logger.warning("Failed to archive team hub %s: %s", category_id, exc)
