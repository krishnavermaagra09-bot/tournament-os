"""
AI assistant cog — /ask, /setup tournament, /setup_server (legacy).
"""
import re
import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:100] or "org"


class AIAssistantCog(commands.Cog, name="ai_assistant"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /ask ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="ask", description="Ask the AI tournament assistant a question")
    @app_commands.describe(
        question="Your question about the tournament",
        tournament_id="Tournament ID (optional — for tournament-specific questions)",
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        question: str,
        tournament_id: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.repositories.user import UserRepository
        from app.ai.assistant.agent import TournamentAIAgent
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            async with session.begin():
                guild_q = select(Guild).where(Guild.discord_guild_id == str(interaction.guild_id))
                result = await session.execute(guild_q)
                guild = result.scalar_one_or_none()
                if not guild:
                    await interaction.followup.send(embed=error_embed("Server not registered."), ephemeral=True)
                    return

                user_repo = UserRepository(session)
                user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                agent = TournamentAIAgent(session)
                thread_id = str(interaction.channel_id) if interaction.channel else None
                try:
                    import asyncio
                    response = await asyncio.wait_for(
                        agent.chat(
                            organization_id=guild.organization_id,
                            guild_id=guild.id,
                            tournament_id=tournament_id,
                            user_id=user.id,
                            discord_user_id=str(interaction.user.id),
                            message=question,
                            thread_id=thread_id,
                        ),
                        timeout=60,
                    )

                    embed = discord.Embed(
                        title="🤖 AI Assistant",
                        description=response["reply"][:4096],
                        color=discord.Color.blurple(),
                    )
                    if response.get("escalated"):
                        embed.set_footer(text=f"Escalated to staff | Ticket: {(response.get('dispute_id') or '')[:8]}")
                        embed.color = discord.Color.orange()

                    await interaction.followup.send(embed=embed, ephemeral=True)

                except asyncio.TimeoutError:
                    logger.warning("AI /ask timed out for user %s", interaction.user.id)
                    await interaction.followup.send(
                        embed=error_embed("⏱️ The AI assistant took too long to respond (>60s). Please try again."),
                        ephemeral=True,
                    )
                except Exception as e:
                    logger.error("AI ask error: %s", e, exc_info=True)
                    await interaction.followup.send(
                        embed=error_embed("AI assistant encountered an error. Please try again."),
                        ephemeral=True,
                    )

    # ── /setup group ──────────────────────────────────────────────────────────

    setup_group = app_commands.Group(
        name="setup",
        description="Tournament OS setup commands",
    )

    @setup_group.command(
        name="tournament",
        description="Launch the interactive setup wizard (creates roles, channels, and server structure)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_tournament(self, interaction: discord.Interaction) -> None:
        """7-step interactive setup wizard — replaces the legacy /setup_server command."""
        if not interaction.guild:
            await interaction.response.send_message("Must be used inside a server.", ephemeral=True)
            return

        # Check if already set up
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.organization import Organization
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            g_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            existing = (await session.execute(g_q)).scalar_one_or_none()
            if existing:
                org_q = select(Organization).where(Organization.id == existing.organization_id)
                org = (await session.execute(org_q)).scalar_one_or_none()
                name_display = org.name if org else existing.organization_id
                settings = dict(existing.settings or {})
                create_t_id = settings.get("channel_ids", {}).get("create_tournament") or settings.get("create_tournament_channel_id")
                ch_mention = f" (<#{create_t_id}>)" if create_t_id else ""
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="⚠️ Already Set Up",
                        description=(
                            f"This server is already configured as **{name_display}**.\n\n"
                            f"To create a tournament, go to the **Create Tournament** channel{ch_mention} and click the button.\n\n"
                            f"Org ID: `{existing.organization_id[:8]}`"
                        ),
                        color=discord.Color.yellow(),
                    ),
                    ephemeral=True,
                )
                return

        from app.bot.views.setup_wizard import SetupStep1Modal
        await interaction.response.send_modal(SetupStep1Modal())

    @setup_tournament.error
    async def setup_tournament_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to run this command.", ephemeral=True
            )
        else:
            logger.error("setup tournament error: %s", error, exc_info=True)
            await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)

    @setup_group.command(
        name="repair",
        description="Rebuild any missing channels/categories without wiping existing data",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_repair(self, interaction: discord.Interaction) -> None:
        """Re-runs the channel/category builder for an already-configured guild.

        Safe to run multiple times — only creates what is missing (any already-present
        channels are left alone; new ones are created alongside them).
        """
        if not interaction.guild:
            await interaction.response.send_message("Must be used inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.organization import Organization
        from app.bot.helpers.server_builder import ServerBuilder
        from app.bot.views.tournament_create_view import TournamentCreateView
        from app.bot.views.player_hub_view import PlayerHubView
        from app.bot.views.support_ticket_view import SupportTicketView
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            g_q = select(Guild).where(
                Guild.discord_guild_id == str(interaction.guild_id),
                Guild.deleted_at.is_(None),
            )
            guild_row = (await session.execute(g_q)).scalar_one_or_none()

        if not guild_row:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Not Set Up",
                    description="This server hasn't been configured yet. Run `/setup tournament` first.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        org_id = guild_row.organization_id
        guild_db_id = guild_row.id
        existing_settings: dict = dict(guild_row.settings or {})
        role_ids_raw: dict = existing_settings.get("staff_role_ids", {})
        role_ids = {k: int(v) for k, v in role_ids_raw.items() if str(v).isdigit()}

        await interaction.followup.send(
            embed=discord.Embed(
                description="🔨 Rebuilding missing channels… this may take up to 30 seconds.",
                color=discord.Color.blurple(),
            ),
            ephemeral=True,
        )

        builder = ServerBuilder(interaction.guild)
        build_result = await builder.build_server_structure(role_ids)

        # Merge new channel/category IDs into saved settings
        merged_settings = dict(existing_settings)
        new_channel_ids = {k: str(v) for k, v in build_result.channels.items()}
        new_cat_ids = {k: str(v) for k, v in build_result.categories.items()}

        merged_settings.setdefault("channel_ids", {}).update(new_channel_ids)
        merged_settings.setdefault("category_ids", {}).update(new_cat_ids)

        # Keep legacy compat keys up to date
        ct = build_result.channels.get("create_tournament")
        if ct:
            merged_settings["create_tournament_channel_id"] = str(ct)
        sc = build_result.categories.get("staff_center")
        if sc:
            merged_settings["setup_category_id"] = str(sc)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                g_row = await session.get(Guild, guild_db_id)
                if g_row:
                    g_row.settings = merged_settings

        # Re-register views for newly created channels
        if ct:
            cv = TournamentCreateView(org_id=org_id, guild_db_id=guild_db_id)
            interaction.client.add_view(cv)
            create_ch = interaction.guild.get_channel(ct)
            if isinstance(create_ch, discord.TextChannel):
                try:
                    hdr = discord.Embed(
                        title="🏆 Tournament OS — Ready!",
                        description="Click the button below to create a tournament.",
                        color=discord.Color.gold(),
                    )
                    await create_ch.send(embed=hdr, view=cv)
                except Exception:
                    pass

        reg_ch_id = build_result.channels.get("register")
        if reg_ch_id:
            reg_ch = interaction.guild.get_channel(reg_ch_id)
            if isinstance(reg_ch, discord.TextChannel):
                try:
                    phv = PlayerHubView()
                    interaction.client.add_view(phv)
                    reg_embed = discord.Embed(
                        title="📝 Tournament Registration",
                        description="When a tournament opens for registration a **[📝 Register]** button will appear here.",
                        color=discord.Color.blurple(),
                    )
                    await reg_ch.send(embed=reg_embed, view=phv)
                except Exception:
                    pass

        support_ch_id = build_result.channels.get("support")
        if support_ch_id:
            support_ch = interaction.guild.get_channel(support_ch_id)
            if isinstance(support_ch, discord.TextChannel):
                try:
                    stv = SupportTicketView()
                    interaction.client.add_view(stv)
                    se = discord.Embed(
                        title="🎫 Support",
                        description="Need help? Click the button below to open a support ticket.",
                        color=discord.Color.purple(),
                    )
                    await support_ch.send(embed=se, view=stv)
                except Exception:
                    pass

        done = discord.Embed(
            title="✅ Repair Complete",
            color=discord.Color.green(),
        )
        done.add_field(name="📁 Categories", value=str(len(build_result.categories)), inline=True)
        done.add_field(name="📢 Channels", value=str(len(build_result.channels)), inline=True)
        if build_result.errors:
            done.add_field(
                name="⚠️ Warnings",
                value="\n".join(build_result.errors[:5]),
                inline=False,
            )
        else:
            done.add_field(name="✨ Status", value="All channels created successfully!", inline=False)

        await interaction.edit_original_response(embed=done)

    @setup_repair.error
    async def setup_repair_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You need **Manage Server** permission to run this command."
        else:
            logger.error("setup repair error: %s", error, exc_info=True)
            msg = "An unexpected error occurred."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    # ── /tournament group ──────────────────────────────────────────────────────

    tournament_group = app_commands.Group(
        name="tournament",
        description="Tournament management commands",
    )

    @tournament_group.command(
        name="quicktest",
        description="Create a test tournament that runs its full lifecycle in ~10 minutes (free, no real players needed)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tournament_quicktest(self, interaction: discord.Interaction) -> None:
        """
        Creates a sandboxed test tournament with dates set just minutes from now.
        The scheduler will auto-advance it through every stage so you can verify
        the full bot flow without spending money or involving real players.

        Stages (all automatic):
          2 min  → Registration Opens  (announcements posted, register button active)
          5 min  → Registration Closes
          6 min  → Check-In Opens      (check-in button posted to ✅-check-in)
          8 min  → Check-In Closes     (no-show handler runs)
          9 min  → Tournament Goes LIVE (bracket generated, match channels created)
          30 min → Tournament Completes
        """
        if not interaction.guild:
            await interaction.response.send_message("Must be used inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from datetime import datetime, timezone, timedelta
        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.models.tournament import TournamentFormat
        from app.database.repositories.user import UserRepository
        from app.services.tournament.creation import TournamentCreationService
        from app.bot.helpers.formatters import error_embed
        from sqlalchemy import select

        now = datetime.now(tz=timezone.utc)

        try:
            async with AsyncSessionLocal() as session:
                g_q = select(Guild).where(
                    Guild.discord_guild_id == str(interaction.guild_id),
                    Guild.deleted_at.is_(None),
                )
                guild_row = (await session.execute(g_q)).scalar_one_or_none()
                if not guild_row:
                    await interaction.followup.send(
                        embed=error_embed("Server not set up. Run `/setup tournament` first."),
                        ephemeral=True,
                    )
                    return

                user_repo = UserRepository(session)
                user, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

                async with session.begin():
                    svc = TournamentCreationService(session)
                    t = await svc.create(
                        organization_id=guild_row.organization_id,
                        guild_id=guild_row.id,
                        created_by=user.id,
                        name=f"🧪 Test Tournament {now.strftime('%H:%M')}",
                        game="Test Game",
                        format=TournamentFormat.SINGLE_ELIMINATION,
                        max_teams=8,
                        registration_open_at=now + timedelta(minutes=2),
                        registration_close_at=now + timedelta(minutes=5),
                        checkin_open_at=now + timedelta(minutes=6),
                        checkin_close_at=now + timedelta(minutes=8),
                        match_start_at=now + timedelta(minutes=9),
                        match_end_at=now + timedelta(minutes=30),
                    )
                    t_id = t.id
                    t_name = t.name

            # Create the management channel
            guild_settings: dict = dict(guild_row.settings or {})
            setup_cat_id = guild_settings.get("setup_category_id") or guild_settings.get("category_ids", {}).get("staff_center")
            d_guild = interaction.guild
            manage_ch = None
            t_category = None

            if setup_cat_id:
                setup_cat = d_guild.get_channel(int(setup_cat_id))
                if isinstance(setup_cat, discord.CategoryChannel):
                    manage_ch = await d_guild.create_text_channel(
                        name="⚙️-test-tournament",
                        category=setup_cat,
                        reason="Tournament OS: test tournament",
                    )

            # Create tournament category (hidden initially)
            everyone = d_guild.default_role
            hidden_ow = {everyone: discord.PermissionOverwrite(view_channel=False)}
            t_category = await d_guild.create_category(
                name=f"🏆 {t_name}"[:100],
                overwrites=hidden_ow,
                reason="Tournament OS: test tournament",
            )
            for ch_name in ["📢-announcements", "📋-rules", "🏆-bracket", "🎯-scores"]:
                await d_guild.create_text_channel(ch_name, category=t_category)

            channel_config: dict = {}
            if manage_ch:
                channel_config["manage_channel_id"] = str(manage_ch.id)
            if t_category:
                channel_config["tournament_category_id"] = str(t_category.id)

            from app.database.models.tournament import Tournament
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    t_row = await session.get(Tournament, t_id)
                    if t_row:
                        t_row.channel_config = channel_config
                        t_row.autonomous_mode = True

            # Post management views
            if manage_ch:
                from app.bot.views.control_panel_view import ControlPanelView
                from app.bot.views.tournament_manage_view import TournamentManageView, _make_manage_message
                from app.bot.views.tournament_wizard import _make_control_panel_embed
                cp_view = ControlPanelView(tournament_id=t_id, org_id=guild_row.organization_id)
                interaction.client.add_view(cp_view)
                cp_embed = _make_control_panel_embed(t_name, t_id, "scheduled", "single_elimination")
                await manage_ch.send(embed=cp_embed, view=cp_view)

                manage_view = TournamentManageView(t_id, guild_row.organization_id)
                interaction.client.add_view(manage_view)
                embed = _make_manage_message(t_name, t_id, "scheduled", "single_elimination")
                await manage_ch.send(embed=embed, view=manage_view)

            timeline = discord.Embed(
                title="🧪 Test Tournament Created!",
                description=(
                    f"**{t_name}** is scheduled and the bot will run it automatically.\n\n"
                    "**What will happen (auto, no action needed):**\n"
                    f"⏱️ `+2 min` — 📋 Registration opens (announcement + register button active)\n"
                    f"⏱️ `+5 min` — 🔒 Registration closes\n"
                    f"⏱️ `+6 min` — ✅ Check-in opens (button posted to ✅-check-in)\n"
                    f"⏱️ `+8 min` — 🔒 Check-in closes (no-shows removed)\n"
                    f"⏱️ `+9 min` — 🔴 Tournament goes LIVE (bracket generated, match rooms created)\n"
                    f"⏱️ `+30 min` — 🏆 Tournament completes\n\n"
                    f"📌 Management channel: {manage_ch.mention if manage_ch else 'None'}\n"
                    f"🆔 Tournament ID: `{t_id[:8]}`\n\n"
                    "**To test player registration:** Have a user go to `📝-register` and click Register during the registration window."
                ),
                color=discord.Color.teal(),
            )
            await interaction.followup.send(embed=timeline, ephemeral=False)

        except Exception as exc:
            logger.exception("quicktest error: %s", exc)
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)

    @tournament_quicktest.error
    async def tournament_quicktest_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to run this command.", ephemeral=True
            )
        else:
            logger.error("quicktest error: %s", error, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("An unexpected error occurred.", ephemeral=True)
                else:
                    await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
            except Exception:
                pass

    # ── /setup_server removed — use /setup tournament ─────────────────────────

    async def _setup_server_removed(self) -> None:
        """Legacy /setup_server has been removed. Use /setup tournament instead."""


async def setup(bot: commands.Bot) -> None:
    cog = AIAssistantCog(bot)
    await bot.add_cog(cog)
