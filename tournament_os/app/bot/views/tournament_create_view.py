"""
Persistent "Create Tournament" button — opens the 6-step TournamentWizard.

custom_id format: "create_t:<org_id>:<guild_db_id>"
Max length: 8+1+36+1+36 = 82 chars.
"""
import logging
import re

import discord

from app.database.models.tournament import TournamentFormat

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "create_t"

_BATTLE_ROYALE_FORMATS = {TournamentFormat.BATTLE_ROYALE, TournamentFormat.FREE_FOR_ALL}


def _make_custom_id(org_id: str, guild_db_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{org_id}:{guild_db_id}"


def _parse_custom_id(custom_id: str) -> tuple[str, str] | None:
    parts = custom_id.split(":", 2)
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    return parts[1], parts[2]


def _channel_name(text: str, max_len: int = 90) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len] or "channel"


class TournamentCreateView(discord.ui.View):
    """Persistent view — survives bot restarts via bot.add_view()."""

    def __init__(self, org_id: str, guild_db_id: str):
        super().__init__(timeout=None)
        self.org_id = org_id
        self.guild_db_id = guild_db_id

        btn = discord.ui.Button(
            label="Create Tournament",
            style=discord.ButtonStyle.success,
            emoji="🏆",
            custom_id=_make_custom_id(org_id, guild_db_id),
        )
        btn.callback = self._open_modal
        self.add_item(btn)

    async def _open_modal(self, interaction: discord.Interaction) -> None:
        raw = interaction.data.get("custom_id", "")
        parsed = _parse_custom_id(raw)
        if not parsed:
            await interaction.response.send_message("Invalid button state. Contact admin.", ephemeral=True)
            return
        org_id, guild_db_id = parsed

        # Open the new 6-step wizard
        from app.bot.views.tournament_wizard import TournamentWizardStep1Modal
        await interaction.response.send_modal(TournamentWizardStep1Modal(org_id=org_id, guild_db_id=guild_db_id))


# ── Legacy modal kept for backward compatibility ──────────────────────────────

class TournamentCreateModal(discord.ui.Modal, title="Create Tournament"):
    """
    Legacy single-step modal — kept for backward compat.
    New tournaments go through TournamentWizardStep1Modal instead.
    """
    t_name = discord.ui.TextInput(label="Tournament Name", placeholder="e.g. Season 1 Grand Finals", required=True, max_length=100)
    game   = discord.ui.TextInput(label="Game",            placeholder="e.g. Apex Legends",          required=True, max_length=100)
    fmt    = discord.ui.TextInput(label="Format",          placeholder="single_elimination / double / round_robin / swiss / battle_royale", required=True, max_length=50)
    max_teams = discord.ui.TextInput(label="Max Teams (optional)", placeholder="e.g. 16 — leave blank for unlimited", required=False, max_length=10)

    _FORMAT_ALIASES: dict[str, str] = {
        "single_elimination": "single_elimination", "single": "single_elimination", "se": "single_elimination",
        "double_elimination": "double_elimination", "double": "double_elimination", "de": "double_elimination",
        "round_robin": "round_robin", "round": "round_robin", "rr": "round_robin",
        "swiss": "swiss", "sw": "swiss",
        "battle_royale": "battle_royale", "battle": "battle_royale", "br": "battle_royale",
    }

    def __init__(self, org_id: str, guild_db_id: str):
        super().__init__()
        self.org_id = org_id
        self.guild_db_id = guild_db_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        fmt_raw = self.fmt.value.strip().lower().replace(" ", "_").replace("-", "_")
        fmt_value = self._FORMAT_ALIASES.get(fmt_raw)
        if not fmt_value:
            from app.bot.helpers.formatters import error_embed
            await interaction.followup.send(embed=error_embed("Unknown format. Use: single_elimination, double_elimination, round_robin, swiss, battle_royale"), ephemeral=True)
            return

        max_t: int | None = None
        if self.max_teams.value.strip():
            try:
                max_t = int(self.max_teams.value.strip())
            except ValueError:
                from app.bot.helpers.formatters import error_embed
                await interaction.followup.send(embed=error_embed("Max Teams must be a number."), ephemeral=True)
                return

        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import Tournament
        from app.database.repositories.user import UserRepository
        from app.services.tournament.creation import TournamentCreationService
        from app.bot.views.tournament_manage_view import TournamentManageView, _make_manage_message
        from app.bot.views.control_panel_view import ControlPanelView
        from sqlalchemy import select

        try:
            guild_settings: dict = {}
            t_id = ""
            t_name = ""
            t_format_obj = TournamentFormat(fmt_value)

            async with AsyncSessionLocal() as session:
                async with session.begin():
                    guild_q = select(Guild).where(Guild.id == self.guild_db_id)
                    guild_record = (await session.execute(guild_q)).scalar_one_or_none()
                    if not guild_record:
                        from app.bot.helpers.formatters import error_embed
                        await interaction.followup.send(embed=error_embed("Guild record not found."), ephemeral=True)
                        return
                    guild_settings = dict(guild_record.settings or {})

                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                    kwargs: dict = {}
                    if max_t:
                        kwargs["max_teams"] = max_t

                    svc = TournamentCreationService(session)
                    tournament = await svc.create(
                        organization_id=self.org_id,
                        guild_id=self.guild_db_id,
                        created_by=user.id,
                        name=self.t_name.value.strip(),
                        game=self.game.value.strip(),
                        format=t_format_obj,
                        **kwargs,
                    )
                    t_id = tournament.id
                    t_name = tournament.name

            d_guild = interaction.guild
            manage_ch: discord.TextChannel | None = None
            t_category: discord.CategoryChannel | None = None

            if d_guild and guild_settings:
                setup_cat_id = guild_settings.get("setup_category_id")
                staff_role_ids: dict = guild_settings.get("staff_role_ids", {})
                setup_cat = d_guild.get_channel(int(setup_cat_id)) if setup_cat_id else None
                everyone = d_guild.default_role
                hidden_ow: dict = {everyone: discord.PermissionOverwrite(view_channel=False)}
                for key in ("tournament_admin", "tournament_manager"):
                    rid = staff_role_ids.get(key)
                    if rid:
                        r = d_guild.get_role(int(rid))
                        if r:
                            hidden_ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

                if isinstance(setup_cat, discord.CategoryChannel):
                    manage_ch = await d_guild.create_text_channel(
                        name=f"⚙️-{_channel_name(t_name)}",
                        category=setup_cat,
                        reason=f"Tournament OS: {t_name}",
                    )

                t_category = await d_guild.create_category(
                    name=f"🏆 {t_name}"[:100],
                    overwrites=hidden_ow,
                    reason=f"Tournament OS: {t_name}",
                )
                for ch_name, topic in [
                    ("📢-announcements", "Tournament announcements"),
                    ("📋-rules",         "Tournament rules"),
                    ("🏆-bracket",       "Bracket and schedule"),
                    ("🎯-scores",        "Match results"),
                ]:
                    if t_format_obj in _BATTLE_ROYALE_FORMATS and ch_name == "🏆-bracket":
                        await d_guild.create_text_channel("🎮-lobby-info", category=t_category, reason=f"Tournament OS: {t_name}")
                    await d_guild.create_text_channel(ch_name, category=t_category, topic=topic, reason=f"Tournament OS: {t_name}")

            t_settings_save: dict = {}
            if manage_ch:
                t_settings_save["manage_channel_id"] = str(manage_ch.id)
            if t_category:
                t_settings_save["tournament_category_id"] = str(t_category.id)

            async with AsyncSessionLocal() as session:
                async with session.begin():
                    t_row = await session.get(Tournament, t_id)
                    if t_row:
                        t_row.channel_config = t_settings_save

            if manage_ch:
                cp_view = ControlPanelView(tournament_id=t_id, org_id=self.org_id)
                interaction.client.add_view(cp_view)
                from app.bot.views.tournament_wizard import _make_control_panel_embed
                cp_embed = _make_control_panel_embed(t_name, t_id, "draft", fmt_value)
                await manage_ch.send(embed=cp_embed, view=cp_view)

                manage_view = TournamentManageView(t_id, self.org_id)
                interaction.client.add_view(manage_view)
                embed = _make_manage_message(t_name, t_id, "draft", fmt_value)
                await manage_ch.send(embed=embed, view=manage_view)

            confirm = discord.Embed(title="✅ Tournament Created!", color=discord.Color.green())
            confirm.add_field(name="Name", value=t_name, inline=True)
            confirm.add_field(name="Game", value=self.game.value.strip(), inline=True)
            confirm.add_field(name="Format", value=fmt_value.replace("_", " ").title(), inline=True)
            confirm.add_field(name="ID", value=f"`{t_id[:8]}`", inline=True)
            if manage_ch:
                confirm.add_field(name="Management Channel", value=manage_ch.mention, inline=False)
            confirm.set_footer(text=f"Full ID: {t_id}")
            await interaction.followup.send(embed=confirm, ephemeral=True)

        except Exception as exc:
            logger.exception("TournamentCreateModal error: %s", exc)
            from app.bot.helpers.formatters import error_embed
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
