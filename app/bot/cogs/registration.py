"""
Registration cog — player-facing commands.

Slash commands kept:
  /my_registration — check your own registration status

Removed (replaced by buttons):
  /register            → Registration button in #register channel
  /registration_review → Registration card Approve/Reject/Flag buttons
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class RegistrationCog(commands.Cog, name="registration"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="my_registration", description="Check your registration status for a tournament")
    @app_commands.describe(tournament_id="Tournament ID")
    async def my_registration(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.repositories.registration import RegistrationRepository
        from app.database.models.registration import Registration
        from app.database.models.user import User
        from app.bot.helpers.formatters import registration_embed, error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
            result = await session.execute(guild_q)
            guild = result.scalar_one_or_none()
            if not guild:
                await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                return

            q = (
                select(Registration)
                .join(User, Registration.submitted_by == User.id)
                .where(Registration.tournament_id == tournament_id)
                .where(Registration.organization_id == guild.organization_id)
                .where(User.discord_user_id == str(interaction.user.id))
                .where(Registration.deleted_at.is_(None))
            )
            result2 = await session.execute(q)
            reg = result2.scalar_one_or_none()
            if not reg:
                await interaction.followup.send(
                    embed=error_embed("You are not registered for this tournament."), ephemeral=True
                )
                return
            await interaction.followup.send(embed=registration_embed(reg), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegistrationCog(bot))
