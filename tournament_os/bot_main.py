"""
Discord Bot entrypoint.

IPv4 fix: Railway containers have no IPv6 routing. We install a custom asyncio
event loop policy that forces AF_INET on every internal getaddrinfo call so that
discord.py (aiohttp), asyncpg, and httpx all resolve to IPv4 without needing to
patch socket.getaddrinfo (which asyncio bypasses when calling its own resolver).
"""
import asyncio
import logging
import socket
import sys


# ── Force IPv4 at the asyncio event-loop level ────────────────────────────────
# Must be done BEFORE any network library (aiohttp, asyncpg) is imported so that
# every coroutine that calls `await loop.getaddrinfo(...)` gets IPv4 results.
class _IPv4SelectorEventLoop(asyncio.SelectorEventLoop):
    """SelectorEventLoop that resolves DNS to IPv4 addresses only."""
    async def getaddrinfo(self, host, port, *, family=0, type=0, proto=0, flags=0):
        return await super().getaddrinfo(
            host, port,
            family=socket.AF_INET,
            type=type,
            proto=proto,
            flags=flags,
        )

class _IPv4EventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> _IPv4SelectorEventLoop:
        return _IPv4SelectorEventLoop()

asyncio.set_event_loop_policy(_IPv4EventLoopPolicy())
# ─────────────────────────────────────────────────────────────────────────────

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Global View Error Handler ─────────────────────────────────────────────────
# discord.py's default View.on_error only prints to stderr and never responds
# to the interaction, causing Discord to show "interaction failed" to the user.
# This patch logs the real error AND sends a user-facing error message.
async def _view_on_error(
    self: discord.ui.View,
    interaction: discord.Interaction,
    error: Exception,
    item: discord.ui.Item,
) -> None:
    logger.error(
        "View error in %s (item=%s): %s",
        type(self).__name__,
        getattr(item, "custom_id", repr(item)),
        error,
        exc_info=True,
    )
    msg = "❌ Something went wrong. Please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

discord.ui.View.on_error = _view_on_error


# ── Global Modal Error Handler ────────────────────────────────────────────────
# Same fix for Modals — default on_error only prints to stderr.
async def _modal_on_error(
    self: discord.ui.Modal,
    interaction: discord.Interaction,
    error: Exception,
) -> None:
    logger.error(
        "Modal error in %s: %s",
        type(self).__name__,
        error,
        exc_info=True,
    )
    msg = "❌ Something went wrong. Please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

discord.ui.Modal.on_error = _modal_on_error
# ─────────────────────────────────────────────────────────────────────────────


class TournamentBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        super().__init__(
            command_prefix="!",
            intents=intents,
            description="Tournament Operating System Bot",
            connector=connector,
        )
        self._pg_listener = None

    async def setup_hook(self) -> None:
        logger.info("Loading cogs...")

        cog_modules = [
            "app.bot.cogs.admin",
            "app.bot.cogs.registration",
            "app.bot.cogs.match_cog",
            "app.bot.cogs.ai_assistant_cog",
            "app.bot.cogs.dispute_cog",
            "app.bot.cogs.override_cog",
            "app.bot.cogs.search_cog",
            "app.bot.cogs.flags_cog",
            "app.bot.cogs.audit_cog",
        ]
        for cog in cog_modules:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as e:
                logger.error("Failed to load cog %s: %s", cog, e, exc_info=True)

        import app.events.subscribers.notification_handler  # noqa: F401
        import app.events.subscribers.analytics_handler  # noqa: F401

        # Wire webhook delivery into the event bus
        from app.services.webhook.webhook_service import register_webhook_subscriber
        register_webhook_subscriber()

        await self._restore_persistent_views()

        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands globally", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands globally: %s", e)

        @self.tree.error
        async def on_tree_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            logger.error(
                "App command error in '%s': %s",
                interaction.command.name if interaction.command else "?",
                error,
                exc_info=True,
            )
            msg = "❌ An unexpected error occurred. Please try again."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        asyncio.create_task(self._start_pg_listener())

        from app.services.scheduler import run_scheduler
        asyncio.create_task(run_scheduler())

        from app.services.autonomous_engine import run_autonomous_engine
        asyncio.create_task(run_autonomous_engine())

        from app.services.job_queue.worker import run_job_queue_worker
        asyncio.create_task(run_job_queue_worker())

    async def _restore_persistent_views(self) -> None:
        try:
            from app.database.session import AsyncSessionLocal
            from app.database.models.tournament import Tournament, TournamentStatus
            from app.database.models.guild import Guild
            from app.database.models.registration import Registration, RegistrationStatus
            from app.bot.views.checkin_button import CheckInView
            from app.bot.views.tournament_create_view import TournamentCreateView
            from app.bot.views.tournament_manage_view import TournamentManageView
            from app.bot.views.registration_button_view import RegistrationButtonView
            from app.bot.views.player_hub_view import PlayerHubView
            from app.bot.views.support_ticket_view import SupportTicketView
            from app.bot.views.registration_card_view import RegistrationCardView
            from app.bot.views.control_panel_view import ControlPanelView
            from sqlalchemy import select

            self.add_view(PlayerHubView())
            logger.info("Restored PlayerHubView (static)")
            self.add_view(SupportTicketView())
            logger.info("Restored SupportTicketView (static)")

            from app.bot.views.match_channel_view import MatchScoreButtonView
            self.add_view(MatchScoreButtonView())
            logger.info("Restored MatchScoreButtonView (static)")

            async with AsyncSessionLocal() as session:
                checkin_q = (
                    select(Tournament)
                    .where(Tournament.status == TournamentStatus.CHECKIN_OPEN)
                    .where(Tournament.deleted_at.is_(None))
                )
                result = await session.execute(checkin_q)
                for t in result.scalars().all():
                    self.add_view(CheckInView(tournament_id=t.id, organization_id=t.organization_id))

                guilds_q = select(Guild).where(Guild.deleted_at.is_(None))
                guilds_result = await session.execute(guilds_q)
                create_count = 0
                for g in guilds_result.scalars().all():
                    s: dict = g.settings or {}
                    if s.get("create_tournament_channel_id") or s.get("channel_ids", {}).get("create_tournament"):
                        self.add_view(TournamentCreateView(org_id=g.organization_id, guild_db_id=g.id))
                        create_count += 1
                logger.info("Restored %d TournamentCreateView(s)", create_count)

                all_t_q = select(Tournament).where(Tournament.deleted_at.is_(None))
                all_t_result = await session.execute(all_t_q)
                manage_count = cp_count = reg_count = 0
                _ended = {TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED, TournamentStatus.CANCELLED}

                for t in all_t_result.scalars().all():
                    tc: dict = t.channel_config or {}
                    if tc.get("manage_channel_id"):
                        self.add_view(TournamentManageView(tournament_id=t.id, org_id=t.organization_id))
                        manage_count += 1
                        if t.status not in _ended:
                            self.add_view(ControlPanelView(tournament_id=t.id, org_id=t.organization_id))
                            cp_count += 1
                    if tc.get("registration_channel_id") and t.status == TournamentStatus.REGISTRATION_OPEN:
                        self.add_view(RegistrationButtonView(tournament_id=t.id, org_id=t.organization_id))
                        reg_count += 1

                logger.info("Restored manage=%d cp=%d reg=%d views", manage_count, cp_count, reg_count)

                cards_q = (
                    select(Registration)
                    .where(Registration.status.in_([
                        RegistrationStatus.PENDING, RegistrationStatus.FLAGGED,
                        RegistrationStatus.WAITLISTED, RegistrationStatus.CHANGES_REQUESTED,
                    ]))
                    .where(Registration.deleted_at.is_(None))
                )
                cards_result = await session.execute(cards_q)
                card_count = 0
                for reg in cards_result.scalars().all():
                    self.add_view(RegistrationCardView(registration_id=reg.id))
                    card_count += 1
                logger.info("Restored %d RegistrationCardView(s)", card_count)

        except Exception as e:
            logger.warning("Could not restore persistent views: %s", e, exc_info=True)

    async def _start_pg_listener(self) -> None:
        async def handle_event(event: dict) -> None:
            from app.events.bus import event_bus
            await event_bus.publish(event.get("type", ""), event)

        from app.services.notify_listener import PGNotifyListener
        listener = PGNotifyListener(settings.database_url, handle_event)
        self._pg_listener = listener
        try:
            await listener.start()
        except Exception as e:
            logger.error("PGNotifyListener failed: %s", e)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Catch-all for component interactions that no registered view handles.

        IMPORTANT: Only intercept interactions whose custom_id has NO ':' separator.
        Every real registered button custom_id uses ':' (e.g. 'player_hub:register',
        'manage_t:<id>:<org>', 'cp_status:<id>'). Setup-wizard step buttons use
        random UUID hex strings with no ':' — those are the only truly unregistered
        interactions we need to handle here.

        DO NOT sleep-and-check for registered views. discord.py dispatches registered
        view handlers as asyncio tasks that run AFTER on_interaction, so is_done()
        will be False even for handled interactions → causes 40060 double-ack errors.
        """
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        # If the custom_id contains ':', it belongs to a registered persistent view.
        # Let discord.py route it — don't touch it here.
        if ":" in custom_id:
            return
        # Only UUID-style custom_ids (setup wizard steps, etc.) reach here.
        logger.warning("Unhandled component interaction: custom_id=%s user=%s", custom_id, interaction.user)
        try:
            await interaction.response.send_message(
                "⚠️ This button is no longer active — the bot may have restarted. "
                "Please start over by running `/setup tournament` or using the latest controls.",
                ephemeral=True,
            )
        except Exception:
            pass

    async def on_ready(self) -> None:
        logger.info("Bot ready: %s (ID: %s)", self.user, self.user.id)

        # Register this bot instance with the Discord notification delivery service
        # so event subscribers can send real DMs and channel messages.
        from app.services.notification.discord_delivery import set_bot
        set_bot(self)

        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="tournaments | /setup tournament",
        ))
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                n = await self.tree.sync(guild=guild)
                logger.info("Guild-synced %d commands to '%s'", len(n), guild.name)
            except Exception as e:
                logger.warning("Could not guild-sync to '%s': %s", guild.name, e)

    async def on_message(self, message: discord.Message) -> None:
        """AI chatbot: any message in a channel named *ai-assistant* gets an AI reply."""
        if message.author.bot:
            return
        if not message.guild:
            return

        ch = message.channel
        ch_name = getattr(ch, "name", "") or ""
        if "ai-assistant" not in ch_name:
            await self.process_commands(message)
            return

        # Don't reply to very short messages or commands
        content = message.content.strip()
        if not content or content.startswith("/") or len(content) < 2:
            await self.process_commands(message)
            return

        async with message.channel.typing():
            try:
                from app.database.session import AsyncSessionLocal
                from app.database.models.guild import Guild
                from app.database.repositories.user import UserRepository
                from app.ai.assistant.agent import TournamentAIAgent
                from sqlalchemy import select
                import asyncio

                async with AsyncSessionLocal() as session:
                    g_q = select(Guild).where(Guild.discord_guild_id == str(message.guild.id))
                    guild_row = (await session.execute(g_q)).scalar_one_or_none()
                    if not guild_row:
                        await message.reply(
                            "❌ This server hasn't been set up yet. Ask an admin to run `/setup tournament`.",
                            mention_author=False,
                        )
                        return

                    user_repo = UserRepository(session)
                    user, _ = await user_repo.get_or_create(
                        str(message.author.id), message.author.name
                    )

                    agent = TournamentAIAgent(session)
                    thread_id = str(message.channel.id)

                    response = await asyncio.wait_for(
                        agent.chat(
                            organization_id=guild_row.organization_id,
                            guild_id=guild_row.id,
                            tournament_id=None,
                            user_id=user.id,
                            discord_user_id=str(message.author.id),
                            message=content,
                            thread_id=thread_id,
                        ),
                        timeout=45,
                    )

                reply_text = response.get("reply", "I'm not sure how to answer that.")[:4000]

                embed = discord.Embed(
                    description=reply_text,
                    color=discord.Color.blurple(),
                )
                embed.set_author(
                    name="🤖 Tournament Assistant",
                    icon_url=self.user.display_avatar.url if self.user else None,
                )
                if response.get("escalated"):
                    embed.color = discord.Color.orange()
                    embed.set_footer(text="⚠️ Your question has been flagged for staff review.")

                await message.reply(embed=embed, mention_author=False)

            except asyncio.TimeoutError:
                await message.reply(
                    "⏱️ I'm thinking too hard — please try again in a moment.",
                    mention_author=False,
                )
            except Exception as exc:
                logger.error("on_message AI reply error: %s", exc, exc_info=True)
                await message.reply(
                    "❌ Something went wrong. Please try again.",
                    mention_author=False,
                )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        logger.info("Joined guild: %s (ID: %s)", guild.name, guild.id)
        try:
            self.tree.copy_global_to(guild=guild)
            n = await self.tree.sync(guild=guild)
            logger.info("Guild-synced %d commands to new guild '%s'", len(n), guild.name)
        except Exception as e:
            logger.warning("Could not guild-sync to '%s': %s", guild.name, e)

    async def close(self) -> None:
        logger.info("Shutting down bot...")
        if self._pg_listener:
            await self._pg_listener.stop()
        await super().close()


async def main() -> None:
    if not settings.discord_token:
        logger.critical("DISCORD_TOKEN is not set. Exiting.")
        sys.exit(1)

    if not settings.database_url:
        logger.critical("DATABASE_URL is not set. Exiting.")
        sys.exit(1)

    logger.info("Running database migrations...")
    proc = await asyncio.create_subprocess_exec(
        "alembic", "upgrade", "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Alembic output:\n%s", stderr.decode().strip())
    else:
        logger.info("Migrations OK:\n%s", stdout.decode().strip())

    delay = 10
    max_delay = 300
    attempt = 0

    while True:
        attempt += 1
        try:
            bot = TournamentBot()
            async with bot:
                await bot.start(settings.discord_token)
            break
        except discord.errors.HTTPException as exc:
            if exc.status == 429:
                retry_after = getattr(exc, "retry_after", None) or delay
                logger.warning("Rate-limited (attempt %d). Retry in %.1fs…", attempt, retry_after)
                await asyncio.sleep(retry_after)
                delay = min(delay * 2, max_delay)
            else:
                logger.error("Discord HTTP error: %s", exc, exc_info=True)
                raise
        except (OSError, ConnectionError) as exc:
            logger.warning("Network error (attempt %d): %s. Retry in %ds…", attempt, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


if __name__ == "__main__":
    asyncio.run(main())
