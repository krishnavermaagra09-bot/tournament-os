"""
Discord role → StaffRole permission mapping.
Checks the user's Discord roles against the staff_members table.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import discord

from app.database.models.staff import StaffMember, StaffRole
from app.database.models.guild import Guild

logger = logging.getLogger(__name__)

# Roles that automatically get staff access without DB entry (guild owner)
OWNER_BYPASS = True


async def get_staff_member(
    session: AsyncSession,
    discord_user_id: str,
    discord_guild_id: str,
    tournament_id: str | None = None,
) -> StaffMember | None:
    """Get the most permissive staff role for a user in a guild."""
    # Resolve guild -> org
    guild_q = select(Guild).where(Guild.discord_guild_id == discord_guild_id).where(Guild.deleted_at.is_(None))
    result = await session.execute(guild_q)
    guild = result.scalar_one_or_none()
    if not guild:
        return None

    from app.database.models.user import User
    user_q = select(User).where(User.discord_user_id == discord_user_id).where(User.deleted_at.is_(None))
    user_result = await session.execute(user_q)
    user = user_result.scalar_one_or_none()
    if not user:
        return None

    # Look for tournament-scoped or org-wide staff membership
    q = (
        select(StaffMember)
        .where(StaffMember.organization_id == guild.organization_id)
        .where(StaffMember.user_id == user.id)
        .where(StaffMember.deleted_at.is_(None))
    )
    if tournament_id:
        q = q.where(
            (StaffMember.tournament_id == tournament_id) | StaffMember.tournament_id.is_(None)
        )
    q = q.order_by(StaffMember.role.asc())
    result = await session.execute(q)
    return result.scalar_one_or_none()


async def has_permission(
    session: AsyncSession,
    discord_member: discord.Member,
    discord_guild_id: str,
    required_role: StaffRole,
    tournament_id: str | None = None,
) -> bool:
    """Returns True if the member has at least the required staff role."""
    # Guild owner bypass
    if OWNER_BYPASS and discord_member.guild.owner_id == discord_member.id:
        return True

    staff = await get_staff_member(
        session, str(discord_member.id), discord_guild_id, tournament_id
    )
    if not staff:
        return False

    ROLE_LEVELS = {
        StaffRole.OWNER: 0,
        StaffRole.SUPER_ADMIN: 1,
        StaffRole.TOURNAMENT_ADMIN: 2,
        StaffRole.TOURNAMENT_MANAGER: 3,
        StaffRole.REFEREE: 4,
        StaffRole.MODERATOR: 5,
        StaffRole.VERIFIER: 6,
        StaffRole.HELPER: 7,
        StaffRole.SUPPORT: 8,
        StaffRole.ANALYST: 9,
    }
    return ROLE_LEVELS.get(staff.role, 99) <= ROLE_LEVELS.get(required_role, 99)
