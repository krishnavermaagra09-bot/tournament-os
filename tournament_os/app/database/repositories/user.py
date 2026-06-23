from sqlalchemy import select

from app.database.models.user import User
from app.database.models.base import Base


class UserRepository:
    def __init__(self, session):
        self.session = session

    async def get_by_discord_id(self, discord_user_id: str) -> User | None:
        q = select(User).where(User.discord_user_id == discord_user_id).where(User.deleted_at.is_(None))
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        q = select(User).where(User.id == user_id).where(User.deleted_at.is_(None))
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def get_or_create(
        self, discord_user_id: str, username: str,
        discriminator: str | None = None, avatar_url: str | None = None
    ) -> tuple[User, bool]:
        """Returns (user, created). Updates username/avatar if user already exists."""
        user = await self.get_by_discord_id(discord_user_id)
        if user:
            user.username = username
            if avatar_url:
                user.avatar_url = avatar_url
            await self.session.flush()
            return user, False
        user = User(
            discord_user_id=discord_user_id,
            username=username,
            discriminator=discriminator,
            avatar_url=avatar_url,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user, True
