"""
Persistent tournament management view posted in each tournament's private channel.

Contains a "Change Status" button that opens an ephemeral dropdown with valid
next-status options. After a status change, Discord side effects are applied
via the central discord_effects module (announcements, check-in button, etc.)

custom_id format: "manage_t:<tournament_id>:<org_id>"
Max length: 8+1+36+1+36 = 82 chars.
"""
import logging

import discord

from app.database.models.tournament import TournamentStatus, VALID_TRANSITIONS

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "manage_t"

_STATUS_EMOJI = {
    "draft": "📝",
    "hidden": "👁️",
    "testing": "🧪",
    "scheduled": "📅",
    "registration_open": "📋",
    "registration_closed": "🔒",
    "checkin_open": "✅",
    "checkin_closed": "🔒",
    "live": "🔴",
    "under_review": "🔍",
    "completed": "🏆",
    "archived": "📦",
    "cancelled": "❌",
}


def _make_custom_id(tournament_id: str, org_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{tournament_id}:{org_id}"


def _parse_custom_id(custom_id: str) -> tuple[str, str] | None:
    parts = custom_id.split(":", 2)
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    return parts[1], parts[2]


def _make_manage_message(t_name: str, t_id: str, status: str, fmt: str) -> discord.Embed:
    emoji = _STATUS_EMOJI.get(status, "⚙️")
    embed = discord.Embed(
        title=f"⚙️ {t_name} — Management",
        color={
            "live": discord.Color.red(),
            "registration_open": discord.Color.green(),
            "completed": discord.Color.gold(),
            "cancelled": discord.Color.dark_red(),
        }.get(status, discord.Color.blurple()),
    )
    embed.add_field(name="Status", value=f"{emoji} {status.replace('_', ' ').title()}", inline=True)
    embed.add_field(name="Format", value=fmt.replace("_", " ").title(), inline=True)
    embed.add_field(name="ID", value=f"`{t_id[:8]}`", inline=True)
    embed.set_footer(text="Use the button below to change the tournament status.")
    return embed


class TournamentManageView(discord.ui.View):
    """Persistent view — survives bot restarts."""

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.org_id = org_id

        btn = discord.ui.Button(
            label="Change Status",
            style=discord.ButtonStyle.primary,
            emoji="📊",
            custom_id=_make_custom_id(tournament_id, org_id),
        )
        btn.callback = self._open_status_picker
        self.add_item(btn)

    async def _open_status_picker(self, interaction: discord.Interaction) -> None:
        raw = interaction.data.get("custom_id", "")
        parsed = _parse_custom_id(raw)
        if not parsed:
            await interaction.response.send_message("Invalid button. Contact admin.", ephemeral=True)
            return
        tournament_id, org_id = parsed

        from app.database.session import AsyncSessionLocal
        from app.database.repositories.tournament import TournamentRepository
        from app.bot.helpers.formatters import error_embed

        async with AsyncSessionLocal() as session:
            t_repo = TournamentRepository(session)
            tournament = await t_repo.get_by_id(tournament_id, org_id)
            if not tournament:
                await interaction.response.send_message(embed=error_embed("Tournament not found."), ephemeral=True)
                return
            current_status = tournament.status
            t_name = tournament.name
            t_fmt = tournament.format.value

        valid_nexts = VALID_TRANSITIONS.get(current_status, [])
        if not valid_nexts:
            await interaction.response.send_message(
                embed=error_embed(f"No valid transitions from **{current_status.value}**."),
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=s.value.replace("_", " ").title(),
                value=s.value,
                emoji=_STATUS_EMOJI.get(s.value, "⚙️"),
            )
            for s in valid_nexts
        ]

        select_view = _StatusSelectView(
            tournament_id=tournament_id,
            org_id=org_id,
            t_name=t_name,
            t_fmt=t_fmt,
            options=options,
            bot=interaction.client,
        )

        embed = discord.Embed(
            title="📊 Change Tournament Status",
            description=f"**{t_name}** is currently **{current_status.value.replace('_', ' ').title()}**.\nSelect a new status below.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=select_view, ephemeral=True)


class _StatusSelectView(discord.ui.View):
    """Ephemeral select menu — not persistent (timeout=120s)."""

    def __init__(
        self,
        tournament_id: str,
        org_id: str,
        t_name: str,
        t_fmt: str,
        options: list[discord.SelectOption] | None = None,
        bot: discord.Client | None = None,
    ):
        super().__init__(timeout=120)
        self.tournament_id = tournament_id
        self.org_id = org_id
        self.t_name = t_name
        self.t_fmt = t_fmt
        self.bot = bot

        select = discord.ui.Select(
            placeholder="Select new status…",
            options=options or [],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        new_status_value: str = interaction.data["values"][0]

        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import TournamentStatus, Tournament
        from app.database.repositories.user import UserRepository
        from app.services.tournament.lifecycle import TournamentLifecycleService
        from app.bot.helpers.formatters import error_embed

        try:
            old_status_value = ""
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Read fresh from DB to avoid stale t_settings
                    t_fresh = await session.get(Tournament, self.tournament_id)
                    if t_fresh:
                        old_status_value = t_fresh.status.value
                        t_settings_fresh: dict = dict(t_fresh.channel_config or {})
                    else:
                        t_settings_fresh = {}

                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)
                    svc = TournamentLifecycleService(session)
                    updated = await svc.transition_status(
                        tournament_id=self.tournament_id,
                        organization_id=self.org_id,
                        new_status=TournamentStatus(new_status_value),
                        actor_id=user.id,
                    )
                    new_status = updated.status

            # ── Apply Discord side effects (announcements, check-in button, etc.) ──
            try:
                import asyncio
                from app.services.discord_effects import apply_status_effects
                asyncio.create_task(
                    apply_status_effects(
                        tournament_id=self.tournament_id,
                        organization_id=self.org_id,
                        new_status=new_status_value,
                        old_status=old_status_value,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to apply discord effects: %s", exc)

            # ── Lock channels on completion / cancellation (immediate, not async) ──
            if new_status in (TournamentStatus.COMPLETED, TournamentStatus.CANCELLED):
                if interaction.guild:
                    await self._lock_tournament_channels(
                        interaction.guild, new_status_value, t_settings_fresh
                    )

            # ── Post status log in management channel ──────────────────────────────
            await self._update_manage_channel(interaction, new_status_value, t_settings_fresh)

            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ Status Updated",
                    description=f"**{self.t_name}** is now **{new_status_value.replace('_', ' ').title()}**.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )

        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        except Exception as exc:
            logger.exception("Status change error: %s", exc)
            from app.bot.helpers.formatters import error_embed as ef
            await interaction.followup.send(embed=ef("An unexpected error occurred."), ephemeral=True)

    async def _lock_tournament_channels(
        self, guild: discord.Guild, reason_status: str, t_settings: dict
    ) -> None:
        """Lock channels when tournament ends or is cancelled."""
        try:
            t_cat_id = t_settings.get("tournament_category_id")
            if not t_cat_id:
                return
            t_cat = guild.get_channel(int(t_cat_id))
            if not isinstance(t_cat, discord.CategoryChannel):
                return

            prefix = "🏆" if reason_status == "completed" else "❌"
            new_name = f"{prefix} {t_cat.name.lstrip('🏆 ').lstrip('❌ ')}"[:100]
            await t_cat.edit(name=new_name)

            for ch in t_cat.channels:
                if "announcement" in ch.name and isinstance(ch, discord.TextChannel):
                    msg = (
                        "🏆 **Tournament Complete!** Thanks to all participants."
                        if reason_status == "completed"
                        else "❌ **Tournament Cancelled.** Apologies to all participants."
                    )
                    await ch.send(msg)
                    break

            logger.info("Locked tournament category %s (%s)", t_cat_id, reason_status)
        except Exception as exc:
            logger.error("Failed to lock tournament channels: %s", exc, exc_info=True)

    async def _update_manage_channel(
        self, interaction: discord.Interaction, new_status_value: str, t_settings: dict
    ) -> None:
        """Post a status-change log in the management channel."""
        try:
            manage_ch_id = t_settings.get("manage_channel_id")
            if not manage_ch_id or not interaction.guild:
                return
            ch = interaction.guild.get_channel(int(manage_ch_id))
            if not isinstance(ch, discord.TextChannel):
                return

            embed = _make_manage_message(self.t_name, self.tournament_id, new_status_value, self.t_fmt)
            await ch.send(
                content=f"📊 Status changed to **{new_status_value.replace('_', ' ').title()}** by {interaction.user.mention}",
                embed=embed,
            )
        except Exception as exc:
            logger.warning("Could not update manage channel: %s", exc)
