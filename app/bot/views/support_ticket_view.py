"""
Persistent Support Ticket view — posted in 🎫-support channel during server setup.

Buttons: Registration Issue · Verification Issue · Match Issue · Dispute · General Support

Each button creates a thread visible to the user and staff.
The channel itself is already public (anyone can see and click the buttons).
Threads use public_thread so non-Community servers are supported; staff are
added as members so they receive notifications.
custom_ids are static (no encoded IDs) — guild/staff context resolved at click time.
"""
import logging

import discord

logger = logging.getLogger(__name__)

_CATEGORIES = {
    "support:registration": ("📝 Registration Issue",  discord.ButtonStyle.primary),
    "support:verification": ("🔍 Verification Issue",  discord.ButtonStyle.primary),
    "support:match":        ("🎮 Match Issue",          discord.ButtonStyle.primary),
    "support:dispute":      ("⚖️ Dispute",              discord.ButtonStyle.danger),
    "support:general":      ("💬 General Support",      discord.ButtonStyle.secondary),
}


class SupportTicketView(discord.ui.View):
    """Persistent view — survives bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for custom_id, (label, style) in _CATEGORIES.items():
            btn = discord.ui.Button(label=label, style=style, custom_id=custom_id)
            btn.callback = self._handle
            self.add_item(btn)

    async def _handle(self, interaction: discord.Interaction) -> None:
        custom_id: str = interaction.data.get("custom_id", "")
        category_info = _CATEGORIES.get(custom_id)
        if not category_info:
            await interaction.response.send_message("Unknown button.", ephemeral=True)
            return

        label, _ = category_info
        category_name = custom_id.split(":")[-1].replace("_", " ").title()

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Tickets can only be created in text channels.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Try public thread first (works on all servers including non-Community).
            # Public threads are visible in the channel list but the initial message
            # is still only seen by the user who opened it (ephemeral confirmation).
            try:
                thread = await channel.create_thread(
                    name=f"🎫 {interaction.user.display_name} — {category_name}",
                    type=discord.ChannelType.public_thread,
                    reason=f"Support ticket: {category_name}",
                )
            except discord.HTTPException:
                # Fallback: private thread (requires Community mode)
                thread = await channel.create_thread(
                    name=f"🎫 {interaction.user.display_name} — {category_name}",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason=f"Support ticket: {category_name}",
                )

            # Add the user to the thread
            await thread.add_user(interaction.user)

            # Add staff roles to the thread
            guild = interaction.guild
            if guild:
                from app.database.session import AsyncSessionLocal
                from app.database.models.guild import Guild
                from sqlalchemy import select

                async with AsyncSessionLocal() as session:
                    g_q = select(Guild).where(
                        Guild.discord_guild_id == str(guild.id),
                        Guild.deleted_at.is_(None),
                    )
                    g = (await session.execute(g_q)).scalar_one_or_none()
                    if g:
                        role_ids: dict = (g.settings or {}).get("staff_role_ids", {})
                        for key in ("tournament_admin", "tournament_manager", "moderator", "support"):
                            rid = role_ids.get(key)
                            if rid:
                                role = guild.get_role(int(rid))
                                if role:
                                    for member in role.members[:10]:
                                        try:
                                            await thread.add_user(member)
                                        except Exception:
                                            pass

            embed = discord.Embed(
                title=f"🎫 Support Ticket — {label}",
                description=(
                    f"Hi {interaction.user.mention}! A staff member will be with you shortly.\n\n"
                    "**Please describe your issue in as much detail as possible**, including:\n"
                    "• What happened\n"
                    "• When it happened\n"
                    "• Any relevant IDs or screenshots"
                ),
                color=discord.Color.purple(),
            )
            embed.set_footer(text="Staff will respond as soon as possible.")

            close_view = _TicketCloseView()
            await thread.send(embed=embed, view=close_view)

            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ Ticket Created",
                    description=f"Your support ticket has been opened in {thread.mention}.\nStaff will respond shortly.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create threads. Please ask an admin to check bot permissions.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.error("Support ticket creation failed: %s", exc, exc_info=True)
            await interaction.followup.send("An error occurred creating your ticket.", ephemeral=True)


class _TicketCloseView(discord.ui.View):
    """Non-persistent close button inside a ticket thread."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message("This button only works inside a thread.", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒 Ticket Closed",
                description=f"Closed by {interaction.user.mention}. This thread will be archived.",
                color=discord.Color.greyple(),
            )
        )
        try:
            await thread.edit(archived=True, locked=True, reason="Ticket closed")
        except discord.Forbidden:
            pass
