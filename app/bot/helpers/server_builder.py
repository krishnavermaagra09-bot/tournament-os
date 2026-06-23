"""
ServerBuilder — creates the full Tournament OS Discord server structure.

Roles (7):  Tournament Admin, Manager, Referee, Verifier, Moderator, Support, Analyst
Categories: 📢 TOURNAMENT INFO · 🎮 PLAYER HUB · 🏆 MATCHES · 👨‍💼 STAFF CENTER · 🤖 SYSTEM LOGS
Channels:   20+ channels organised by category with correct permission overwrites
"""
import asyncio
import logging
from dataclasses import dataclass, field

import discord

logger = logging.getLogger(__name__)

# Small delay between Discord API calls to avoid rate-limit bursts.
_API_DELAY = 0.4  # seconds


STAFF_ROLES: list[dict] = [
    {"name": "Tournament Admin",   "db_role": "tournament_admin",   "color": discord.Color.red(),    "hoist": True,  "mentionable": True},
    {"name": "Tournament Manager", "db_role": "tournament_manager", "color": discord.Color.orange(), "hoist": True,  "mentionable": True},
    {"name": "Referee",            "db_role": "referee",            "color": discord.Color.blue(),   "hoist": True,  "mentionable": True},
    {"name": "Verifier",           "db_role": "verifier",           "color": discord.Color.teal(),   "hoist": False, "mentionable": True},
    {"name": "Moderator",          "db_role": "moderator",          "color": discord.Color.green(),  "hoist": False, "mentionable": True},
    {"name": "Support",            "db_role": "support",            "color": discord.Color.purple(), "hoist": False, "mentionable": True},
    {"name": "Analyst",            "db_role": "analyst",            "color": discord.Color.gold(),   "hoist": False, "mentionable": False},
]


@dataclass
class BuildResult:
    roles: dict[str, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class ServerBuilder:
    def __init__(self, guild: discord.Guild) -> None:
        self.guild = guild
        self.everyone = guild.default_role

    async def create_roles(self) -> dict[str, int]:
        """Create all staff roles. Returns {db_role: discord_role_id}."""
        result: dict[str, int] = {}
        for r in STAFF_ROLES:
            try:
                role = await self.guild.create_role(
                    name=r["name"],
                    color=r["color"],
                    hoist=r["hoist"],
                    mentionable=r["mentionable"],
                    reason="Tournament OS: staff role",
                )
                result[r["db_role"]] = role.id
                logger.info("Created role: %s (%s)", r["name"], role.id)
                await asyncio.sleep(_API_DELAY)
            except discord.Forbidden:
                logger.warning("No permission to create role: %s", r["name"])
            except discord.HTTPException as exc:
                logger.error("Role creation failed (%s): %s", r["name"], exc)
            except Exception as exc:
                logger.error("Role creation failed (%s): %s", r["name"], exc)
        return result

    def _roles(self, role_ids: dict[str, int]) -> dict[str, discord.Role | None]:
        return {k: self.guild.get_role(v) for k, v in role_ids.items()}

    def _staff_write_ow(self, roles: dict[str, discord.Role | None]) -> dict:
        """Everyone reads; staff can write."""
        ow: dict = {self.everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False)}
        for key in ("tournament_admin", "tournament_manager", "referee", "moderator", "verifier", "support"):
            r = roles.get(key)
            if r:
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        return ow

    def _staff_only_ow(self, roles: dict[str, discord.Role | None]) -> dict:
        """Hidden from @everyone; visible to all staff."""
        ow: dict = {self.everyone: discord.PermissionOverwrite(view_channel=False)}
        for key in ("tournament_admin", "tournament_manager", "referee", "moderator", "verifier", "support", "analyst"):
            r = roles.get(key)
            if r:
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        return ow

    def _admin_only_ow(self, roles: dict[str, discord.Role | None]) -> dict:
        """Hidden from @everyone; only Tournament Admin sees it."""
        ow: dict = {self.everyone: discord.PermissionOverwrite(view_channel=False)}
        r = roles.get("tournament_admin")
        if r:
            ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        return ow

    def _public_ro_ow(self) -> dict:
        """Public read-only — everyone sees, nobody types (bot handles it)."""
        return {self.everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False)}

    async def _create_category(self, name: str, overwrites: dict, result: BuildResult) -> discord.CategoryChannel | None:
        """Create a single category with error handling."""
        try:
            cat = await self.guild.create_category(name, overwrites=overwrites, reason="Tournament OS")
            await asyncio.sleep(_API_DELAY)
            return cat
        except discord.Forbidden:
            msg = f"Missing permission to create category: {name}"
            logger.warning(msg)
            result.errors.append(msg)
            return None
        except discord.HTTPException as exc:
            msg = f"Failed to create category {name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None

    async def _create_channel(self, name: str, key: str, category: discord.CategoryChannel, result: BuildResult) -> None:
        """Create a single text channel with error handling."""
        try:
            ch = await self.guild.create_text_channel(name, category=category, reason="Tournament OS")
            result.channels[key] = ch.id
            logger.info("Created channel: %s (%s)", name, ch.id)
            await asyncio.sleep(_API_DELAY)
        except discord.Forbidden:
            msg = f"Missing permission to create channel: {name}"
            logger.warning(msg)
            result.errors.append(msg)
        except discord.HTTPException as exc:
            msg = f"Failed to create channel {name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)

    async def build_server_structure(self, role_ids: dict[str, int]) -> BuildResult:
        result = BuildResult(roles=role_ids)
        roles = self._roles(role_ids)

        # ── 📢 TOURNAMENT INFO ────────────────────────────────────────────────
        cat = await self._create_category("📢 TOURNAMENT INFO", self._staff_write_ow(roles), result)
        if cat:
            result.categories["tournament_info"] = cat.id
            for ch_name, key in [
                ("📢-announcements", "announcements"),
                ("📋-rules",         "rules"),
                ("📅-schedule",      "schedule"),
                ("🏆-results",       "results"),
                ("📊-standings",     "standings"),
                ("🎯-live-brackets", "live_brackets"),
            ]:
                await self._create_channel(ch_name, key, cat, result)

        # ── 🎮 PLAYER HUB ─────────────────────────────────────────────────────
        player_hub_ow = self._public_ro_ow()
        # AI assistant channel: everyone can send messages (it's a chatbot)
        ai_ch_ow = {self.everyone: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        cat = await self._create_category("🎮 PLAYER HUB", player_hub_ow, result)
        if cat:
            result.categories["player_hub"] = cat.id
            for ch_name, key in [
                ("📝-register",          "register"),
                ("✅-check-in",           "check_in"),
                ("🎫-support",            "support"),
                ("❓-faq",                "faq"),
            ]:
                await self._create_channel(ch_name, key, cat, result)
            # AI chatbot channel (players can type here)
            try:
                ai_ch = await self.guild.create_text_channel(
                    "🤖-ai-assistant",
                    category=cat,
                    overwrites=ai_ch_ow,
                    topic="Ask me anything about the tournament! I'm your AI assistant. 🤖",
                    reason="Tournament OS: AI assistant channel",
                )
                result.channels["ai_assistant"] = ai_ch.id
                logger.info("Created AI assistant channel: %s", ai_ch.id)
                await asyncio.sleep(_API_DELAY)
            except Exception as exc:
                logger.warning("Could not create AI assistant channel: %s", exc)
                result.errors.append(f"AI assistant channel: {exc}")

        # ── 🏆 MATCHES ────────────────────────────────────────────────────────
        cat = await self._create_category("🏆 MATCHES", self._public_ro_ow(), result)
        if cat:
            result.categories["matches"] = cat.id
            for ch_name, key in [
                ("📡-match-feed",       "match_feed"),
                ("🔴-live-matches",     "live_matches"),
                ("🎯-score-submission", "score_submission"),
            ]:
                await self._create_channel(ch_name, key, cat, result)

        # ── 👨‍💼 STAFF CENTER (hidden) ──────────────────────────────────────────
        cat = await self._create_category("👨‍💼 STAFF CENTER", self._staff_only_ow(roles), result)
        if cat:
            result.categories["staff_center"] = cat.id
            for ch_name, key in [
                ("📋-verification-queue", "verification_queue"),
                ("🚩-duplicate-flags",    "duplicate_flags"),
                ("🎮-match-control",      "match_control"),
                ("⚖️-disputes",           "disputes_staff"),
                ("💬-staff-chat",         "staff_chat"),
                ("📋-create-tournament",  "create_tournament"),
                ("📜-audit-logs",         "audit_logs"),
            ]:
                await self._create_channel(ch_name, key, cat, result)

        # ── 🤖 SYSTEM LOGS (admin only) ───────────────────────────────────────
        cat = await self._create_category("🤖 SYSTEM LOGS", self._admin_only_ow(roles), result)
        if cat:
            result.categories["system_logs"] = cat.id
            for ch_name, key in [
                ("🤖-bot-logs",      "bot_logs"),
                ("❌-error-logs",    "error_logs"),
                ("⚙️-system-events", "system_events"),
            ]:
                await self._create_channel(ch_name, key, cat, result)

        logger.info(
            "ServerBuilder done: %d categories, %d channels, %d errors",
            len(result.categories), len(result.channels), len(result.errors),
        )
        return result
