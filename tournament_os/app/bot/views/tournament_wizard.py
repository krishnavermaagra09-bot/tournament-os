"""
6-step Tournament Creation Wizard — replaces the single-step TournamentCreateModal.

Flow:
  Step 1 — Modal:  Name, Game, Description, Region, Prize Pool
  Step 2 — Select: Format (SE / DE / Swiss / RR / Battle Royale / League / Custom)
  Step 3 — View:   Team size select + Max/Reserve inputs modal
  Step 4 — Modal:  Registration dates, Allow Duplicates, Auto Verification
  Step 5 — Select: Check-in enabled? + No-Show policy
  Step 6 — Modal:  Match Rules, Scoring, Tiebreakers, Dispute Policy
             Then: Preview embed + [🚀 Publish] [💾 Save Draft]

State is stored on bot._tournament_wizard_states keyed by "tw:{guild_id}:{user_id}".
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord

from app.database.models.tournament import TournamentFormat

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class TournamentWizardState:
    org_id: str = ""
    guild_db_id: str = ""
    # Step 1
    name: str = ""
    game: str = ""
    description: str = ""
    region: str = ""
    prize_pool: str = ""
    # Step 2
    format: str = "single_elimination"
    platform: str = ""
    # Step 3
    team_size: str = "team"
    max_teams: int = 16
    reserve_teams: int = 0
    # Step 4 — registration + tournament schedule
    registration_open: str = ""
    registration_close: str = ""
    tournament_start: str = ""
    tournament_end: str = ""
    round_duration_hours: int = 24
    allow_duplicates: bool = False
    auto_verification: bool = True
    # Step 5
    enable_checkin: bool = True
    noshow_policy: str = "flag"
    checkin_reminders: list[str] = field(default_factory=lambda: ["24h", "1h"])
    # Step 6
    match_rules: str = ""
    scoring_rules: str = ""
    tiebreak_rules: str = ""
    dispute_policy: str = ""


def _parse_dt(val: str) -> datetime | None:
    """Parse a date string typed by staff into a UTC-aware datetime.

    Accepts formats like:
      2026-07-01 12:00 UTC
      2026-07-01 12:00
      2026-07-01T14:00
      2026-07-01
    """
    if not val:
        return None
    val = val.strip().replace(" UTC", "").replace("UTC", "").strip()
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(val, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _key(guild_id: int, user_id: int) -> str:
    return f"tw:{guild_id}:{user_id}"


def _get(bot: discord.Client, guild_id: int, user_id: int) -> TournamentWizardState:
    if not hasattr(bot, "_tournament_wizard_states"):
        bot._tournament_wizard_states = {}
    return bot._tournament_wizard_states.setdefault(_key(guild_id, user_id), TournamentWizardState())


def _clear(bot: discord.Client, guild_id: int, user_id: int) -> None:
    if hasattr(bot, "_tournament_wizard_states"):
        bot._tournament_wizard_states.pop(_key(guild_id, user_id), None)


# ── Progress helper ───────────────────────────────────────────────────────────

def _bar(step: int, total: int = 6) -> str:
    return f"`{'█' * step}{'░' * (total - step)}`  Step {step}/{total}"


_FORMAT_LABELS = {
    "single_elimination": "Single Elimination",
    "double_elimination": "Double Elimination",
    "round_robin":        "Round Robin",
    "swiss":              "Swiss",
    "battle_royale":      "Battle Royale",
    "league":             "League",
    "free_for_all":       "Free For All",
}

_TEAM_SIZE_LABELS = {
    "solo": "Solo (1v1)", "duo": "Duo (2v2)", "trio": "Trio (3v3)",
    "squad": "Squad (4v4)", "team": "Team (5+)", "hybrid": "Hybrid",
}

_NOSHOW_LABELS = {"remove": "Remove Team", "flag": "Flag Team", "ignore": "Ignore"}


# ── Step 1 — Tournament Details Modal ─────────────────────────────────────────

class TournamentWizardStep1Modal(discord.ui.Modal, title="Create Tournament (1/6)"):
    t_name = discord.ui.TextInput(label="Tournament Name", placeholder="e.g. Season 1 Grand Finals", required=True, max_length=100)
    game   = discord.ui.TextInput(label="Game",            placeholder="e.g. Apex Legends",          required=True, max_length=80)
    desc   = discord.ui.TextInput(label="Description",     placeholder="Short description (optional)", required=False, style=discord.TextStyle.paragraph, max_length=500)
    region = discord.ui.TextInput(label="Region",          placeholder="e.g. NA, EU, SEA, Global",   required=False, max_length=50)
    prize  = discord.ui.TextInput(label="Prize Pool",      placeholder="e.g. $500 Cash Prize",       required=False, max_length=200)

    def __init__(self, org_id: str, guild_db_id: str) -> None:
        super().__init__()
        self.org_id = org_id
        self.guild_db_id = guild_db_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.org_id = self.org_id
        state.guild_db_id = self.guild_db_id
        state.name = self.t_name.value.strip()
        state.game = self.game.value.strip()
        state.description = self.desc.value.strip()
        state.region = self.region.value.strip()
        state.prize_pool = self.prize.value.strip()
        await interaction.response.send_message(embed=_step2_embed(state), view=Step2View(), ephemeral=True)


# ── Step 2 — Format Select ────────────────────────────────────────────────────

def _step2_embed(state: TournamentWizardState) -> discord.Embed:
    e = discord.Embed(title="🏆 Create Tournament — Format", description="Choose the bracket/competition format.", color=discord.Color.blurple())
    e.add_field(name="🏷️ Name", value=state.name, inline=True)
    e.add_field(name="🎮 Game", value=state.game, inline=True)
    if state.region:
        e.add_field(name="🌍 Region", value=state.region, inline=True)
    e.set_footer(text=_bar(2))
    return e


class Step2View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select tournament format…",
        options=[
            discord.SelectOption(label="Single Elimination", value="single_elimination", emoji="⚔️",  description="Lose once, you're out"),
            discord.SelectOption(label="Double Elimination", value="double_elimination", emoji="🔁",  description="One loss sends you to losers bracket"),
            discord.SelectOption(label="Round Robin",        value="round_robin",        emoji="🔄",  description="Everyone plays everyone"),
            discord.SelectOption(label="Swiss",              value="swiss",              emoji="🇨🇭",  description="Paired by record each round"),
            discord.SelectOption(label="Battle Royale",      value="battle_royale",      emoji="🎯",  description="Last player/team standing"),
            discord.SelectOption(label="League",             value="league",             emoji="🏟️",  description="Season-based point accumulation"),
            discord.SelectOption(label="Free For All",       value="free_for_all",       emoji="💥",  description="Every team for themselves"),
        ],
    )
    async def select_format(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.format = select.values[0]
        await interaction.response.edit_message(embed=_step3_embed(state), view=Step3View())


# ── Step 3 — Team Configuration ───────────────────────────────────────────────

def _step3_embed(state: TournamentWizardState) -> discord.Embed:
    e = discord.Embed(title="🏆 Create Tournament — Teams", description="Configure team size and capacity.", color=discord.Color.blurple())
    e.add_field(name="🏷️ Name",   value=state.name, inline=True)
    e.add_field(name="📋 Format", value=_FORMAT_LABELS.get(state.format, state.format), inline=True)
    e.set_footer(text=_bar(3))
    return e


class Step3View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select team/player size…",
        options=[
            discord.SelectOption(label="Solo (1v1)",  value="solo",   emoji="🧑"),
            discord.SelectOption(label="Duo (2v2)",   value="duo",    emoji="👥"),
            discord.SelectOption(label="Trio (3v3)",  value="trio",   emoji="👨‍👩‍👦"),
            discord.SelectOption(label="Squad (4v4)", value="squad",  emoji="👨‍👩‍👧‍👦"),
            discord.SelectOption(label="Team (5+)",   value="team",   emoji="🏅"),
            discord.SelectOption(label="Hybrid",      value="hybrid", emoji="🔀"),
        ],
    )
    async def select_size(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.team_size = select.values[0]
        await interaction.response.send_modal(_TeamCapacityModal())

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step2_embed(state), view=Step2View())


class _TeamCapacityModal(discord.ui.Modal, title="Team Capacity (3/6)"):
    max_teams     = discord.ui.TextInput(label="Max Teams",     placeholder="e.g. 16", required=True,  max_length=4)
    reserve_teams = discord.ui.TextInput(label="Reserve Teams", placeholder="e.g. 4 (leave 0 for none)", required=False, max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        try:
            state.max_teams = int(self.max_teams.value.strip())
        except ValueError:
            state.max_teams = 16
        try:
            state.reserve_teams = int(self.reserve_teams.value.strip()) if self.reserve_teams.value.strip() else 0
        except ValueError:
            state.reserve_teams = 0
        await interaction.response.send_message(embed=_step4_embed(state), view=Step4View(), ephemeral=True)


# ── Step 4 — Registration Settings ───────────────────────────────────────────

def _step4_embed(state: TournamentWizardState) -> discord.Embed:
    e = discord.Embed(
        title="🏆 Create Tournament — Dates & Schedule",
        description="Set registration dates and tournament schedule. Both buttons are optional — click **⏭ Skip** to use defaults.",
        color=discord.Color.blurple(),
    )
    e.add_field(name="🏷️ Name",      value=state.name, inline=True)
    e.add_field(name="👥 Team Size", value=_TEAM_SIZE_LABELS.get(state.team_size, state.team_size), inline=True)
    e.add_field(name="🔢 Max Teams", value=str(state.max_teams), inline=True)
    if state.registration_open:
        e.add_field(name="📅 Reg Opens",  value=state.registration_open,  inline=True)
    if state.registration_close:
        e.add_field(name="📅 Reg Closes", value=state.registration_close, inline=True)
    if state.tournament_start:
        e.add_field(name="🎮 Matches Start",   value=state.tournament_start, inline=True)
    if state.tournament_end:
        e.add_field(name="🏁 Tournament Ends", value=state.tournament_end,   inline=True)
    if state.round_duration_hours != 24:
        e.add_field(name="⏱ Round Duration",  value=f"{state.round_duration_hours}h", inline=True)
    e.set_footer(text=_bar(4))
    return e


class Step4View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="📅 Set Registration Dates", style=discord.ButtonStyle.primary)
    async def set_reg_dates(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_RegistrationDatesModal())

    @discord.ui.button(label="🗓 Set Tournament Schedule", style=discord.ButtonStyle.primary)
    async def set_schedule(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_TournamentScheduleModal())

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step5_embed(state), view=Step5View())

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step3_embed(state), view=Step3View())


class _RegistrationDatesModal(discord.ui.Modal, title="Registration Dates (4/6)"):
    reg_open  = discord.ui.TextInput(label="Registration Opens",  placeholder="e.g. 2026-07-01 12:00 UTC", required=False, max_length=30)
    reg_close = discord.ui.TextInput(label="Registration Closes", placeholder="e.g. 2026-07-10 23:59 UTC", required=False, max_length=30)
    allow_dup = discord.ui.TextInput(label="Allow Duplicates (yes/no)", placeholder="no",  required=False, max_length=3)
    auto_ver  = discord.ui.TextInput(label="Auto Verification (yes/no)", placeholder="yes", required=False, max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.registration_open  = self.reg_open.value.strip()
        state.registration_close = self.reg_close.value.strip()
        state.allow_duplicates   = self.allow_dup.value.strip().lower() in ("yes", "y", "true")
        state.auto_verification  = self.auto_ver.value.strip().lower() not in ("no", "n", "false")
        await interaction.response.edit_message(embed=_step4_embed(state), view=Step4View())


class _TournamentScheduleModal(discord.ui.Modal, title="Tournament Schedule (4/6)"):
    t_start    = discord.ui.TextInput(label="Tournament / Matches Start", placeholder="e.g. 2026-07-15 14:00 UTC", required=False, max_length=30)
    t_end      = discord.ui.TextInput(label="Tournament End",             placeholder="e.g. 2026-07-20 23:59 UTC", required=False, max_length=30)
    round_dur  = discord.ui.TextInput(label="Round Duration (hours)",     placeholder="e.g. 24  (hours per round)", required=False, max_length=4)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.tournament_start = self.t_start.value.strip()
        state.tournament_end   = self.t_end.value.strip()
        try:
            state.round_duration_hours = int(self.round_dur.value.strip()) if self.round_dur.value.strip() else 24
        except ValueError:
            state.round_duration_hours = 24
        await interaction.response.edit_message(embed=_step4_embed(state), view=Step4View())


# ── Step 5 — Check-In Settings ───────────────────────────────────────────────

def _step5_embed(state: TournamentWizardState) -> discord.Embed:
    e = discord.Embed(title="🏆 Create Tournament — Check-In", description="Configure the check-in system.", color=discord.Color.blurple())
    e.add_field(name="🏷️ Name",          value=state.name, inline=True)
    e.add_field(name="📋 Format",         value=_FORMAT_LABELS.get(state.format, state.format), inline=True)
    e.add_field(name="⬇️ Duplicates",    value="Allowed" if state.allow_duplicates else "Blocked", inline=True)
    e.set_footer(text=_bar(5))
    return e


class Step5View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Enable check-in?",
        options=[
            discord.SelectOption(label="✅ Enable Check-In",  value="yes", description="Players must check in before the tournament"),
            discord.SelectOption(label="⏭ Skip Check-In",    value="no",  description="No check-in required"),
        ],
    )
    async def checkin_toggle(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.enable_checkin = select.values[0] == "yes"
        if state.enable_checkin:
            await interaction.response.edit_message(embed=_step5_embed(state), view=_Step5NoShowView())
        else:
            await interaction.response.edit_message(embed=_step6_embed(state), view=Step6View())

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step4_embed(state), view=Step4View())


class _Step5NoShowView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="No-show policy…",
        options=[
            discord.SelectOption(label="Remove Team",  value="remove", emoji="❌", description="Remove no-shows from the tournament"),
            discord.SelectOption(label="Flag Team",    value="flag",   emoji="🚩", description="Flag no-shows for staff review"),
            discord.SelectOption(label="Ignore",       value="ignore", emoji="🔕", description="No action taken on no-shows"),
        ],
    )
    async def noshow(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.noshow_policy = select.values[0]
        await interaction.response.edit_message(embed=_step6_embed(state), view=Step6View())


# ── Step 6 — Rules & Publish ──────────────────────────────────────────────────

def _step6_embed(state: TournamentWizardState) -> discord.Embed:
    e = discord.Embed(
        title="🏆 Create Tournament — Rules & Publish",
        description="Optionally set match rules, or publish now.",
        color=discord.Color.gold(),
    )
    e.add_field(name="🏷️ Name",         value=state.name, inline=True)
    e.add_field(name="🎮 Game",          value=state.game,  inline=True)
    e.add_field(name="📋 Format",        value=_FORMAT_LABELS.get(state.format, state.format), inline=True)
    e.add_field(name="👥 Team Size",     value=_TEAM_SIZE_LABELS.get(state.team_size, state.team_size), inline=True)
    e.add_field(name="🔢 Max Teams",     value=str(state.max_teams), inline=True)
    if state.prize_pool:
        e.add_field(name="🏆 Prize Pool", value=state.prize_pool, inline=True)
    if state.region:
        e.add_field(name="🌍 Region",    value=state.region, inline=True)
    e.add_field(name="✅ Check-In",      value="Enabled" if state.enable_checkin else "Disabled", inline=True)
    if state.enable_checkin:
        e.add_field(name="⛔ No-Show",   value=_NOSHOW_LABELS.get(state.noshow_policy, state.noshow_policy), inline=True)
    e.set_footer(text=_bar(6))
    return e


class Step6View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Add Rules", style=discord.ButtonStyle.secondary)
    async def add_rules(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_RulesModal())

    @discord.ui.button(label="🚀 Publish Tournament", style=discord.ButtonStyle.success, emoji="🚀")
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state_copy = TournamentWizardState(**state.__dict__)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚙️ Creating tournament…",
                description="Please wait while we set everything up.",
                color=discord.Color.blurple(),
            ),
            view=self,
        )
        await _create_tournament(interaction, state_copy, publish=True)

    @discord.ui.button(label="💾 Save Draft", style=discord.ButtonStyle.secondary, emoji="💾")
    async def save_draft(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state_copy = TournamentWizardState(**state.__dict__)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="⚙️ Saving draft…", color=discord.Color.blurple()),
            view=self,
        )
        await _create_tournament(interaction, state_copy, publish=False)

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step5_embed(state), view=Step5View())


class _RulesModal(discord.ui.Modal, title="Rules & Scoring (6/6)"):
    match_rules    = discord.ui.TextInput(label="Match Rules",       placeholder="Rules for each match", required=False, style=discord.TextStyle.paragraph, max_length=500)
    scoring_rules  = discord.ui.TextInput(label="Scoring Rules",     placeholder="How scores are tallied", required=False, style=discord.TextStyle.paragraph, max_length=300)
    tiebreak_rules = discord.ui.TextInput(label="Tiebreaker Rules",  placeholder="How ties are broken", required=False, style=discord.TextStyle.paragraph, max_length=300)
    dispute_policy = discord.ui.TextInput(label="Dispute Policy",    placeholder="How disputes are handled", required=False, style=discord.TextStyle.paragraph, max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.match_rules    = self.match_rules.value.strip()
        state.scoring_rules  = self.scoring_rules.value.strip()
        state.tiebreak_rules = self.tiebreak_rules.value.strip()
        state.dispute_policy = self.dispute_policy.value.strip()
        await interaction.response.edit_message(embed=_step6_embed(state), view=Step6View())


# ── Create tournament in DB + Discord ─────────────────────────────────────────

async def _create_tournament(
    interaction: discord.Interaction,
    state: TournamentWizardState,
    publish: bool,
) -> None:
    import re
    from app.database.session import AsyncSessionLocal
    from app.database.models.guild import Guild
    from app.database.models.tournament import Tournament, TournamentStatus
    from app.database.repositories.user import UserRepository
    from app.services.tournament.creation import TournamentCreationService
    from app.bot.views.tournament_manage_view import TournamentManageView, _make_manage_message
    from app.bot.views.control_panel_view import ControlPanelView
    from sqlalchemy import select
    import re as _re

    def _channel_name(text: str) -> str:
        slug = text.lower().strip()
        slug = _re.sub(r"[^\w\s-]", "", slug)
        slug = _re.sub(r"[\s_]+", "-", slug)
        return slug.strip("-")[:90] or "channel"

    try:
        # Resolve format
        fmt_map = {
            "single_elimination": TournamentFormat.SINGLE_ELIMINATION,
            "double_elimination": TournamentFormat.DOUBLE_ELIMINATION,
            "round_robin":        TournamentFormat.ROUND_ROBIN,
            "swiss":              TournamentFormat.SWISS,
            "battle_royale":      TournamentFormat.BATTLE_ROYALE,
            "league":             TournamentFormat.SEASON_LEAGUE,
            "free_for_all":       TournamentFormat.FREE_FOR_ALL,
        }
        fmt = fmt_map.get(state.format, TournamentFormat.SINGLE_ELIMINATION)

        t_id = ""
        t_name = ""

        async with AsyncSessionLocal() as session:
            async with session.begin():
                guild_q = select(Guild).where(Guild.id == state.guild_db_id)
                guild_record = (await session.execute(guild_q)).scalar_one_or_none()
                if not guild_record:
                    await interaction.edit_original_response(
                        embed=discord.Embed(title="❌ Error", description="Guild record not found.", color=discord.Color.red()),
                        view=None,
                    )
                    return
                guild_settings = dict(guild_record.settings or {})

                user_repo = UserRepository(session)
                user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                kwargs: dict = {"max_teams": state.max_teams}
                if state.description:
                    kwargs["description"] = state.description
                if state.region:
                    kwargs["region"] = state.region
                if state.prize_pool:
                    kwargs["prize_pool"] = state.prize_pool

                svc = TournamentCreationService(session)
                tournament = await svc.create(
                    organization_id=state.org_id,
                    guild_id=state.guild_db_id,
                    created_by=user.id,
                    name=state.name,
                    game=state.game,
                    format=fmt,
                    **kwargs,
                )
                t_id = tournament.id
                t_name = tournament.name

        # Discord channels
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
                    topic=f"Management channel for {t_name}",
                    reason=f"Tournament OS: {t_name}",
                )

            t_category = await d_guild.create_category(
                name=f"🏆 {t_name}"[:100],
                overwrites=hidden_ow,
                reason=f"Tournament OS: {t_name}",
            )

            channels_to_create = [
                ("📢-announcements", "Tournament announcements"),
                ("📋-rules",         "Tournament rules"),
                ("📅-schedule",      "Match schedule"),
                ("📊-standings",     "Live standings"),
                ("🏆-results",       "Match results"),
                ("🎯-brackets",      "Bracket and fixture list"),
            ]
            if fmt in (TournamentFormat.BATTLE_ROYALE, TournamentFormat.FREE_FOR_ALL):
                channels_to_create.append(("🎮-lobby-info", "Lobby codes and session info"))

            for ch_name, topic in channels_to_create:
                await d_guild.create_text_channel(ch_name, category=t_category, topic=topic, reason=f"Tournament OS: {t_name}")

        # ── Persist to proper model columns ───────────────────────────────────────
        # channel_config  → ONLY Discord channel / category IDs
        # proper columns  → behavior flags, text rules, dates
        channel_config: dict = {}
        if manage_ch:
            channel_config["manage_channel_id"] = str(manage_ch.id)
        if t_category:
            channel_config["tournament_category_id"] = str(t_category.id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                t_row = await session.get(Tournament, t_id)
                if t_row:
                    # Discord IDs
                    t_row.channel_config = channel_config
                    # Behavior flags — direct model columns
                    t_row.allow_duplicates = state.allow_duplicates
                    # auto_removal_policy JSONB — checkin + noshow behavior
                    t_row.auto_removal_policy = {
                        "enable_checkin":    state.enable_checkin,
                        "noshow_policy":     state.noshow_policy,
                        "auto_verification": state.auto_verification,
                    }
                    # Rules text — direct model columns
                    if state.match_rules:
                        t_row.rules = state.match_rules
                    if state.dispute_policy:
                        t_row.dispute_policy = state.dispute_policy
                    # Scoring / tiebreaker — JSONB columns (store as {"text": ...})
                    if state.scoring_rules:
                        t_row.scoring_rules = {"text": state.scoring_rules}
                    if state.tiebreak_rules:
                        t_row.tiebreaker_rules = {"text": state.tiebreak_rules}
                    # Scheduling dates
                    if state.registration_open:
                        t_row.registration_open_at = _parse_dt(state.registration_open)
                    if state.registration_close:
                        t_row.registration_close_at = _parse_dt(state.registration_close)
                    if state.tournament_start:
                        t_row.match_start_at = _parse_dt(state.tournament_start)
                    if state.tournament_end:
                        t_row.match_end_at = _parse_dt(state.tournament_end)
                    if state.round_duration_hours:
                        t_row.round_duration_hours = state.round_duration_hours
                    # Status stays DRAFT — staff uses Control Panel to publish

        # Post management embed with Control Panel
        if manage_ch:
            cp_view = ControlPanelView(tournament_id=t_id, org_id=state.org_id)
            interaction.client.add_view(cp_view)

            status_str = "draft"
            cp_embed = _make_control_panel_embed(t_name, t_id, status_str, state.format)
            await manage_ch.send(embed=cp_embed, view=cp_view)

            # Also post old manage view for backward compat
            manage_view = TournamentManageView(t_id, state.org_id)
            interaction.client.add_view(manage_view)
            old_embed = _make_manage_message(t_name, t_id, status_str, state.format)
            await manage_ch.send(embed=old_embed, view=manage_view)

        _clear(interaction.client, interaction.guild_id, interaction.user.id)

        icon = "🚀" if publish else "💾"
        done = discord.Embed(
            title=f"{icon} Tournament {'Created' if publish else 'Saved as Draft'}!",
            color=discord.Color.green() if publish else discord.Color.greyple(),
        )
        done.add_field(name="🏷️ Name",     value=t_name, inline=True)
        done.add_field(name="🎮 Game",      value=state.game, inline=True)
        done.add_field(name="📋 Format",    value=_FORMAT_LABELS.get(state.format, state.format), inline=True)
        done.add_field(name="🔢 Max Teams", value=str(state.max_teams), inline=True)
        if state.prize_pool:
            done.add_field(name="🏆 Prize", value=state.prize_pool, inline=True)
        done.add_field(name="🆔 ID",        value=f"`{t_id[:8]}`", inline=True)
        if manage_ch:
            done.add_field(name="⚙️ Management", value=manage_ch.mention, inline=False)
        done.set_footer(text=f"Full ID: {t_id}")

        await interaction.edit_original_response(embed=done, view=None)

    except Exception as exc:
        logger.exception("Tournament wizard create failed: %s", exc)
        err = discord.Embed(title="❌ Creation Failed", description=f"```{str(exc)[:500]}```", color=discord.Color.red())
        try:
            await interaction.edit_original_response(embed=err, view=None)
        except Exception:
            pass


def _make_control_panel_embed(t_name: str, t_id: str, status: str, fmt: str) -> discord.Embed:
    status_colors = {
        "live": discord.Color.red(), "registration_open": discord.Color.green(),
        "completed": discord.Color.gold(), "cancelled": discord.Color.dark_red(),
    }
    e = discord.Embed(
        title=f"⚙️ {t_name} — Control Panel",
        description="Use the buttons below to manage this tournament.",
        color=status_colors.get(status, discord.Color.blurple()),
    )
    status_emoji = {
        "draft": "📝", "registration_open": "📋", "checkin_open": "✅",
        "live": "🔴", "completed": "🏆", "cancelled": "❌",
    }
    e.add_field(name="Status", value=f"{status_emoji.get(status, '⚙️')} {status.replace('_', ' ').title()}", inline=True)
    e.add_field(name="Format", value=_FORMAT_LABELS.get(fmt, fmt.replace("_", " ").title()), inline=True)
    e.add_field(name="ID", value=f"`{t_id[:8]}`", inline=True)
    e.set_footer(text="All tournament operations are available through the buttons below.")
    return e
