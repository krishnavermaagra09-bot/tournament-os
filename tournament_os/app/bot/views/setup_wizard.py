"""
7-step setup wizard for Tournament OS.

Flow:
  /setup tournament  →  Step1Modal (workspace name)
  Step1 submit       →  Step2View  (create staff roles? Yes/No)
  Step2 button       →  Step3View  (create server structure? Yes/No)
  Step3 button       →  Step4View  (team channel mode — select)
  Step4 select       →  Step5View  (match room mode — select)
  Step5 select       →  Step6View  (archive policy — select)
  Step6 select       →  Step7View  (confirmation + [Confirm Setup])
  Step7 confirm      →  _execute_setup()  →  done embed
"""
import logging
import re
from dataclasses import dataclass

import discord

logger = logging.getLogger(__name__)

TOTAL_STEPS = 7


# ── Wizard state ──────────────────────────────────────────────────────────────

@dataclass
class WizardState:
    workspace_name: str = ""
    create_roles: bool = True
    create_categories: bool = True
    team_channel_mode: str = "text"
    match_room_mode: str = "auto"
    archive_policy: str = "archive"


def _key(guild_id: int, user_id: int) -> str:
    return f"sw:{guild_id}:{user_id}"


def _get(bot: discord.Client, guild_id: int, user_id: int) -> WizardState:
    if not hasattr(bot, "_wizard_states"):
        bot._wizard_states = {}
    return bot._wizard_states.setdefault(_key(guild_id, user_id), WizardState())


def _clear(bot: discord.Client, guild_id: int, user_id: int) -> None:
    if hasattr(bot, "_wizard_states"):
        bot._wizard_states.pop(_key(guild_id, user_id), None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bar(step: int) -> str:
    return f"`{'█' * step}{'░' * (TOTAL_STEPS - step)}`  Step {step}/{TOTAL_STEPS}"


def _embed(title: str, desc: str, step: int, fields: list[tuple] | None = None) -> discord.Embed:
    e = discord.Embed(title=f"⚙️ Setup Wizard — {title}", description=desc, color=discord.Color.blurple())
    e.set_footer(text=_bar(step))
    for name, value, inline in (fields or []):
        e.add_field(name=name, value=value, inline=inline)
    return e


_TEAM_LABELS = {"none": "No team channels", "text": "Private text channels", "text_voice": "Text + voice channels"}
_MATCH_LABELS = {"auto": "Auto-create match rooms", "manual": "Manual match rooms"}
_ARCH_LABELS = {
    "keep": "Keep everything",
    "archive": "Archive everything",
    "delete_match": "Delete match rooms",
    "delete_team": "Delete team rooms",
    "full": "Full cleanup",
}


# ── Step 1 — Modal (workspace name) ──────────────────────────────────────────

class SetupStep1Modal(discord.ui.Modal, title="Tournament OS Setup (1/7)"):
    workspace_name = discord.ui.TextInput(
        label="Tournament Workspace Name",
        placeholder="e.g. Apex Legends PH",
        required=True,
        min_length=2,
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.workspace_name = self.workspace_name.value.strip()
        embed = _embed(
            "Staff Roles",
            (
                "Should the bot **automatically create staff roles**?\n\n"
                "Creates:\n"
                "🔴 **Tournament Admin** · 🟠 **Tournament Manager**\n"
                "🔵 **Referee** · 🟢 **Verifier** · 🟩 **Moderator**\n"
                "🟣 **Support** · 🟡 **Analyst**\n\n"
                "Each role maps to a permission level in the database."
            ),
            step=2,
            fields=[("🏷️ Workspace", state.workspace_name, True)],
        )
        await interaction.response.send_message(embed=embed, view=SetupStep2View(), ephemeral=True)


# ── Step 2 — Create roles? ────────────────────────────────────────────────────

class SetupStep2View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="✅ Yes, Create Roles", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        _get(interaction.client, interaction.guild_id, interaction.user.id).create_roles = True
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step3_embed(state), view=SetupStep3View())

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        _get(interaction.client, interaction.guild_id, interaction.user.id).create_roles = False
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step3_embed(state), view=SetupStep3View())


# ── Step 3 — Create server structure? ────────────────────────────────────────

def _step3_embed(state: WizardState) -> discord.Embed:
    return _embed(
        "Server Structure",
        (
            "Should the bot **automatically build your server layout**?\n\n"
            "📢 **TOURNAMENT INFO** — announcements, rules, schedule, standings\n"
            "🎮 **PLAYER HUB** — register, check-in, support, faq\n"
            "🏆 **MATCHES** — match feed, live matches, score submission\n"
            "👨‍💼 **STAFF CENTER** — hidden from players\n"
            "🤖 **SYSTEM LOGS** — admin only"
        ),
        step=3,
        fields=[
            ("🏷️ Workspace", state.workspace_name, True),
            ("👥 Roles", "✅ Will create" if state.create_roles else "⏭ Skipped", True),
        ],
    )


class SetupStep3View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="✅ Yes, Build Structure", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.create_categories = True
        await interaction.response.edit_message(embed=_step4_embed(state), view=SetupStep4View())

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.create_categories = False
        await interaction.response.edit_message(embed=_step4_embed(state), view=SetupStep4View())


# ── Step 4 — Team channel mode ────────────────────────────────────────────────

def _step4_embed(state: WizardState) -> discord.Embed:
    return _embed(
        "Team Channel Mode",
        "How should **team channels** be created when a player is approved?",
        step=4,
        fields=[
            ("🏷️ Workspace", state.workspace_name, True),
            ("👥 Roles", "✅ Creating" if state.create_roles else "⏭ Skipped", True),
            ("🏗️ Structure", "✅ Creating" if state.create_categories else "⏭ Skipped", True),
        ],
    )


class SetupStep4View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select team channel mode…",
        options=[
            discord.SelectOption(label="No Team Channels",              value="none",       emoji="🚫", description="Teams don't get private channels"),
            discord.SelectOption(label="Private Text Channels",         value="text",       emoji="💬", description="Each team gets a private text channel"),
            discord.SelectOption(label="Private Text + Voice Channels", value="text_voice", emoji="🎙️", description="Text and voice channels per team"),
        ],
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.team_channel_mode = select.values[0]
        await interaction.response.edit_message(embed=_step5_embed(state), view=SetupStep5View())


# ── Step 5 — Match room mode ──────────────────────────────────────────────────

def _step5_embed(state: WizardState) -> discord.Embed:
    return _embed(
        "Match Room Mode",
        "How should **match rooms** be handled when the bracket runs?",
        step=5,
        fields=[
            ("🏷️ Workspace", state.workspace_name, True),
            ("👥 Team Channels", _TEAM_LABELS.get(state.team_channel_mode, state.team_channel_mode), True),
        ],
    )


class SetupStep5View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select match room mode…",
        options=[
            discord.SelectOption(label="Create Match Rooms Automatically", value="auto",   emoji="🤖", description="Bot creates a private room per match"),
            discord.SelectOption(label="Manual Match Rooms",               value="manual", emoji="🛠️", description="Staff create match rooms manually"),
        ],
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.match_room_mode = select.values[0]
        await interaction.response.edit_message(embed=_step6_embed(state), view=SetupStep6View())


# ── Step 6 — Archive policy ───────────────────────────────────────────────────

def _step6_embed(state: WizardState) -> discord.Embed:
    return _embed(
        "Archive Policy",
        "What should happen to channels **when a tournament ends**?",
        step=6,
        fields=[
            ("🏷️ Workspace", state.workspace_name, True),
            ("🎮 Match Rooms", _MATCH_LABELS.get(state.match_room_mode, state.match_room_mode), True),
        ],
    )


class SetupStep6View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select archive policy…",
        options=[
            discord.SelectOption(label="Keep Everything",    value="keep",         emoji="📁", description="All channels remain after the tournament"),
            discord.SelectOption(label="Archive Everything", value="archive",      emoji="🗃️", description="Move all tournament channels to an archive"),
            discord.SelectOption(label="Delete Match Rooms", value="delete_match", emoji="🗑️", description="Auto-delete match rooms only"),
            discord.SelectOption(label="Delete Team Rooms",  value="delete_team",  emoji="🗑️", description="Auto-delete team channels only"),
            discord.SelectOption(label="Full Cleanup",       value="full",         emoji="🧹", description="Delete all created channels when done"),
        ],
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        state.archive_policy = select.values[0]
        await interaction.response.edit_message(embed=_step7_embed(state), view=SetupStep7View())


# ── Step 7 — Confirmation ─────────────────────────────────────────────────────

def _step7_embed(state: WizardState) -> discord.Embed:
    e = discord.Embed(
        title="⚙️ Setup Wizard — Confirm",
        description="Review your configuration and click **Confirm Setup** to apply.",
        color=discord.Color.gold(),
    )
    e.add_field(name="🏷️ Workspace Name",  value=state.workspace_name,                                          inline=False)
    e.add_field(name="👥 Staff Roles",     value="✅ Will be created" if state.create_roles else "⏭ Skipped",    inline=True)
    e.add_field(name="🏗️ Server Structure",value="✅ Will be created" if state.create_categories else "⏭ Skipped", inline=True)
    e.add_field(name="💬 Team Channels",   value=_TEAM_LABELS.get(state.team_channel_mode, state.team_channel_mode), inline=True)
    e.add_field(name="🎮 Match Rooms",     value=_MATCH_LABELS.get(state.match_room_mode, state.match_room_mode),    inline=True)
    e.add_field(name="🗃️ Archive Policy",  value=_ARCH_LABELS.get(state.archive_policy, state.archive_policy),       inline=True)
    e.set_footer(text=_bar(TOTAL_STEPS))
    return e


class SetupStep7View(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="🚀 Confirm Setup", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚙️ Building your Tournament OS workspace…",
                description="Creating roles and channels. This usually takes 30–60 seconds.",
                color=discord.Color.blurple(),
            ),
            view=self,
        )
        await _execute_setup(interaction, state)

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = _get(interaction.client, interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=_step6_embed(state), view=SetupStep6View())


# ── Execute ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:100] or "org"


async def _execute_setup(interaction: discord.Interaction, state: WizardState) -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.guild import Guild
    from app.database.models.organization import Organization
    from app.database.repositories.user import UserRepository
    from app.database.models.staff import StaffMember, StaffRole
    from app.bot.helpers.server_builder import ServerBuilder
    from app.bot.views.tournament_create_view import TournamentCreateView
    from app.bot.views.player_hub_view import PlayerHubView
    from app.bot.views.support_ticket_view import SupportTicketView
    from sqlalchemy import select

    d_guild = interaction.guild
    if not d_guild:
        await interaction.followup.send("Must be run inside a server.", ephemeral=True)
        return

    try:
        # ── 1. DB records ─────────────────────────────────────────────────
        org_id = ""
        guild_db_id = ""

        async with AsyncSessionLocal() as session:
            async with session.begin():
                existing_q = select(Guild).where(
                    Guild.discord_guild_id == str(interaction.guild_id),
                    Guild.deleted_at.is_(None),
                )
                existing = (await session.execute(existing_q)).scalar_one_or_none()

                if existing:
                    org_id = existing.organization_id
                    guild_db_id = existing.id
                else:
                    base_slug = _slugify(state.workspace_name)
                    slug = base_slug
                    counter = 1
                    while True:
                        sq = await session.execute(select(Organization).where(Organization.slug == slug))
                        if not sq.scalar_one_or_none():
                            break
                        slug = f"{base_slug}-{counter}"
                        counter += 1

                    org = Organization(name=state.workspace_name, slug=slug, settings={})
                    session.add(org)
                    await session.flush()
                    await session.refresh(org)
                    org_id = org.id

                    g = Guild(
                        organization_id=org.id,
                        discord_guild_id=str(interaction.guild_id),
                        name=d_guild.name,
                        settings={},
                    )
                    session.add(g)
                    await session.flush()
                    await session.refresh(g)
                    guild_db_id = g.id

                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)
                    session.add(StaffMember(
                        organization_id=org.id,
                        user_id=user.id,
                        role=StaffRole.OWNER,
                        tournament_id=None,
                        permissions={},
                        assigned_by=user.id,
                    ))

        # ── 2. Discord roles ──────────────────────────────────────────────
        builder = ServerBuilder(d_guild)
        role_ids: dict[str, int] = {}

        if state.create_roles:
            role_ids = await builder.create_roles()
            admin_role_id = role_ids.get("tournament_admin")
            if admin_role_id and isinstance(interaction.user, discord.Member):
                role_obj = d_guild.get_role(admin_role_id)
                if role_obj:
                    try:
                        await interaction.user.add_roles(role_obj, reason="Tournament OS: setup")
                    except discord.Forbidden:
                        pass

        # ── 3. Discord server structure ───────────────────────────────────
        build_result = None
        if state.create_categories:
            build_result = await builder.build_server_structure(role_ids)

        # ── 4. Save guild settings ────────────────────────────────────────
        settings: dict = {
            "workspace_name": state.workspace_name,
            "team_channel_mode": state.team_channel_mode,
            "match_room_mode": state.match_room_mode,
            "archive_policy": state.archive_policy,
            "staff_role_ids": {k: str(v) for k, v in role_ids.items()},
        }
        if build_result:
            settings["category_ids"] = {k: str(v) for k, v in build_result.categories.items()}
            settings["channel_ids"] = {k: str(v) for k, v in build_result.channels.items()}
            # backward-compat keys
            sc = build_result.categories.get("staff_center")
            if sc:
                settings["setup_category_id"] = str(sc)
            ph = build_result.categories.get("player_hub")
            if ph:
                settings["registration_category_id"] = str(ph)
            ct = build_result.channels.get("create_tournament")
            if ct:
                settings["create_tournament_channel_id"] = str(ct)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                g_row = await session.get(Guild, guild_db_id)
                if g_row:
                    g_row.settings = settings

        # ── 5. Post Create Tournament button ──────────────────────────────
        create_ch = None
        if build_result and build_result.channels.get("create_tournament"):
            ch_id = build_result.channels["create_tournament"]
            create_ch = d_guild.get_channel(ch_id)

        if isinstance(create_ch, discord.TextChannel):
            cv = TournamentCreateView(org_id=org_id, guild_db_id=guild_db_id)
            interaction.client.add_view(cv)
            hdr = discord.Embed(
                title="🏆 Tournament OS — Ready!",
                description=(
                    f"Welcome to **{state.workspace_name}**!\n\n"
                    "Click the button below to create your first tournament.\n"
                    "A private management channel will be created automatically."
                ),
                color=discord.Color.gold(),
            )
            await create_ch.send(embed=hdr, view=cv)

        # ── 6. Post Player Hub welcome embeds ─────────────────────────────
        if build_result:
            reg_ch_id = build_result.channels.get("register")
            if reg_ch_id:
                reg_ch = d_guild.get_channel(reg_ch_id)
                if isinstance(reg_ch, discord.TextChannel):
                    phv = PlayerHubView()
                    interaction.client.add_view(phv)
                    reg_embed = discord.Embed(
                        title="📝 Tournament Registration",
                        description=(
                            "**Welcome to the Player Hub!**\n\n"
                            "When a tournament opens for registration a **[📝 Register]** button will appear here.\n"
                            "No commands needed — just click and fill in the form."
                        ),
                        color=discord.Color.blurple(),
                    )
                    await reg_ch.send(embed=reg_embed, view=phv)

            checkin_ch_id = build_result.channels.get("check_in")
            if checkin_ch_id:
                ch = d_guild.get_channel(checkin_ch_id)
                if isinstance(ch, discord.TextChannel):
                    ce = discord.Embed(
                        title="✅ Check-In",
                        description="When check-in opens a **[✅ Check In]** button will appear here.\nMake sure to check in before the deadline!",
                        color=discord.Color.green(),
                    )
                    await ch.send(embed=ce)

            faq_ch_id = build_result.channels.get("faq")
            if faq_ch_id:
                ch = d_guild.get_channel(faq_ch_id)
                if isinstance(ch, discord.TextChannel):
                    fe = discord.Embed(
                        title="❓ Frequently Asked Questions",
                        description=(
                            "**How do I register?**\n→ Go to 📝-register and click **Register**.\n\n"
                            "**How do I check in?**\n→ Go to ✅-check-in when check-in opens.\n\n"
                            "**How do I submit a score?**\n→ Use the **Submit Score** button in your match room.\n\n"
                            "**I have a problem**\n→ Go to 🎫-support and open a ticket."
                        ),
                        color=discord.Color.blue(),
                    )
                    await ch.send(embed=fe)

            support_ch_id = build_result.channels.get("support")
            if support_ch_id:
                ch = d_guild.get_channel(support_ch_id)
                if isinstance(ch, discord.TextChannel):
                    stv = SupportTicketView()
                    interaction.client.add_view(stv)
                    se = discord.Embed(
                        title="🎫 Support",
                        description=(
                            "Need help? Click the button that matches your issue.\n"
                            "A private ticket thread will be created for you."
                        ),
                        color=discord.Color.purple(),
                    )
                    await ch.send(embed=se, view=stv)

        # ── 7. Done ────────────────────────────────────────────────────────
        _clear(interaction.client, interaction.guild_id, interaction.user.id)

        done = discord.Embed(title="✅ Tournament OS — Setup Complete!", color=discord.Color.green())
        done.add_field(name="🏷️ Workspace", value=state.workspace_name, inline=True)
        done.add_field(name="👥 Roles", value=f"{len(role_ids)} created" if role_ids else "Skipped", inline=True)
        done.add_field(
            name="🏗️ Channels",
            value=f"{len(build_result.channels)} created" if build_result else "Skipped",
            inline=True,
        )
        if isinstance(create_ch, discord.TextChannel):
            done.add_field(name="🚀 Next Step", value=f"Go to {create_ch.mention} and click **Create Tournament**!", inline=False)
        if build_result and build_result.errors:
            done.add_field(name="⚠️ Warnings", value="\n".join(build_result.errors[:3]), inline=False)
        done.set_footer(text=f"Org ID: {org_id[:8]}")

        await interaction.edit_original_response(embed=done, view=None)

    except Exception as exc:
        logger.exception("Setup wizard execution failed: %s", exc)
        err = discord.Embed(
            title="❌ Setup Failed",
            description=f"```{str(exc)[:500]}```",
            color=discord.Color.red(),
        )
        try:
            await interaction.edit_original_response(embed=err, view=None)
        except Exception:
            pass
