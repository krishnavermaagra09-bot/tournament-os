"""
Registration Card — auto-posted in #verification-queue when a player submits.

Each card has action buttons:
  [✅ Approve]   — approve immediately
  [❌ Reject]    — opens RejectReasonModal, then rejects
  [⏸ Hold]      — place on hold
  [🚩 Flag]      — flag for secondary review
  [↩ Send Back]  — request changes (opens SendBackModal)

custom_id format:  "rc_{action}:{registration_id}"
  e.g.  "rc_approve:550e8400-e29b-41d4-a716-446655440000"
Max: 10+36 = 46 chars  ✓
"""
import logging

import discord

logger = logging.getLogger(__name__)

_PREFIX = "rc"


def _cid(action: str, reg_id: str) -> str:
    return f"{_PREFIX}_{action}:{reg_id}"


def build_card_embed(
    reg_id: str,
    applicant_name: str,
    discord_mention: str,
    tournament_name: str,
    form_data: dict,
    status: str = "pending",
    actioned_by: str | None = None,
) -> discord.Embed:
    status_color = {
        "pending": discord.Color.yellow(),
        "manually_approved": discord.Color.green(),
        "auto_approved": discord.Color.green(),
        "rejected": discord.Color.red(),
        "flagged": discord.Color.orange(),
        "hold": discord.Color.greyple(),
        "changes_requested": discord.Color.blue(),
    }.get(status, discord.Color.yellow())

    status_emoji = {
        "pending": "⏳", "manually_approved": "✅", "auto_approved": "✅",
        "rejected": "❌", "flagged": "🚩", "hold": "⏸", "changes_requested": "↩",
    }.get(status, "❓")

    embed = discord.Embed(
        title=f"📋 Registration — {tournament_name}",
        color=status_color,
    )
    embed.add_field(name="👤 Applicant", value=f"{discord_mention}\n({applicant_name})", inline=True)
    embed.add_field(name="🔖 Status", value=f"{status_emoji} {status.replace('_', ' ').title()}", inline=True)
    embed.add_field(name="🆔 Reg ID", value=f"`{reg_id[:8]}`", inline=True)

    # Form answers
    skip_keys = {"username", "discord_user_id"}
    answer_lines: list[str] = []
    for key, value in form_data.items():
        if key in skip_keys or not value:
            continue
        label = key.replace("_", " ").title()
        answer_lines.append(f"**{label}:** {str(value)[:100]}")
    if answer_lines:
        embed.add_field(name="📝 Answers", value="\n".join(answer_lines[:10]), inline=False)

    if actioned_by:
        embed.set_footer(text=f"Actioned by {actioned_by}")

    return embed


class RegistrationCardView(discord.ui.View):
    """
    Persistent view — one per registration card in #verification-queue.
    registration_id is encoded in each button's custom_id.
    """

    def __init__(self, registration_id: str) -> None:
        super().__init__(timeout=None)
        self.registration_id = registration_id

        for action, label, style, emoji in [
            ("approve",  "Approve",   discord.ButtonStyle.success,   "✅"),
            ("reject",   "Reject",    discord.ButtonStyle.danger,    "❌"),
            ("hold",     "Hold",      discord.ButtonStyle.secondary,  "⏸"),
            ("flag",     "Flag",      discord.ButtonStyle.secondary,  "🚩"),
            ("sendback", "Send Back", discord.ButtonStyle.secondary,  "↩"),
        ]:
            btn = discord.ui.Button(
                label=label,
                style=style,
                emoji=emoji,
                custom_id=_cid(action, registration_id),
            )
            btn.callback = self._dispatch
            self.add_item(btn)

    async def _dispatch(self, interaction: discord.Interaction) -> None:
        custom_id: str = interaction.data.get("custom_id", "")
        if not custom_id.startswith(_PREFIX + "_"):
            return
        rest = custom_id[len(_PREFIX) + 1:]
        action, reg_id = rest.split(":", 1)

        if action == "reject":
            await interaction.response.send_modal(_RejectModal(reg_id, interaction.message))
        elif action == "sendback":
            await interaction.response.send_modal(_SendBackModal(reg_id, interaction.message))
        else:
            await interaction.response.defer(ephemeral=True)
            await _apply_action(interaction, reg_id, action, reason=None)

    async def _disable_all(self, message: discord.Message) -> None:
        for item in self.children:
            item.disabled = True
        try:
            await message.edit(view=self)
        except Exception:
            pass


# ── Modals ────────────────────────────────────────────────────────────────────

class _RejectModal(discord.ui.Modal, title="Reject Registration"):
    reason = discord.ui.TextInput(
        label="Rejection Reason",
        placeholder="Why is this registration being rejected?",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=5,
        max_length=500,
    )

    def __init__(self, reg_id: str, message: discord.Message) -> None:
        super().__init__()
        self.reg_id = reg_id
        self.message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _apply_action(interaction, self.reg_id, "reject", reason=self.reason.value, message=self.message)


class _SendBackModal(discord.ui.Modal, title="Request Changes"):
    notes = discord.ui.TextInput(
        label="What changes are needed?",
        placeholder="Describe what the applicant needs to fix or resubmit.",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=5,
        max_length=500,
    )

    def __init__(self, reg_id: str, message: discord.Message) -> None:
        super().__init__()
        self.reg_id = reg_id
        self.message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _apply_action(interaction, self.reg_id, "sendback", reason=self.notes.value, message=self.message)


# ── Action handler ────────────────────────────────────────────────────────────

async def _apply_action(
    interaction: discord.Interaction,
    reg_id: str,
    action: str,
    reason: str | None,
    message: discord.Message | None = None,
) -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.guild import Guild
    from app.database.models.registration import Registration
    from app.database.models.tournament import Tournament
    from app.database.repositories.user import UserRepository
    from app.services.registration.approvals import RegistrationApprovalService
    from app.bot.helpers.permissions import has_permission
    from app.database.models.staff import StaffRole
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Permission check
            if not await has_permission(session, interaction.user, str(interaction.guild_id), StaffRole.VERIFIER):
                await interaction.followup.send("❌ You need **Verifier** or higher to action registrations.", ephemeral=True)
                return

            # Look up registration
            reg_q = select(Registration).where(
                Registration.id == reg_id,
                Registration.deleted_at.is_(None),
            )
            reg = (await session.execute(reg_q)).scalar_one_or_none()
            if not reg:
                await interaction.followup.send("Registration not found.", ephemeral=True)
                return

            t_q = select(Tournament).where(Tournament.id == reg.tournament_id)
            tournament = (await session.execute(t_q)).scalar_one_or_none()
            if not tournament:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return

            user_repo = UserRepository(session)
            reviewer, _ = await user_repo.get_or_create(str(interaction.user.id), interaction.user.name)

            svc = RegistrationApprovalService(session)

            new_status = "pending"
            if action == "approve":
                await svc.approve(reg_id, tournament, reviewer.id)
                new_status = "manually_approved"
            elif action == "reject":
                if not reason:
                    await interaction.followup.send("A reason is required for rejection.", ephemeral=True)
                    return
                await svc.reject(reg_id, tournament, reviewer.id, reason)
                new_status = "rejected"
            elif action == "flag":
                await svc.flag(reg_id, tournament, reviewer.id)
                new_status = "flagged"
            elif action == "hold":
                from app.database.models.registration import RegistrationStatus as _RS
                reg.status = _RS.HOLD
                new_status = "hold"
            elif action == "sendback":
                from app.database.models.registration import RegistrationStatus as _RS
                if reason:
                    reg.rejection_reason = reason
                reg.status = _RS.CHANGES_REQUESTED
                new_status = "changes_requested"

    # Update the card embed
    if message:
        try:
            embed = message.embeds[0] if message.embeds else None
            if embed:
                new_embed = embed.copy()
                status_emoji = {
                    "manually_approved": "✅", "rejected": "❌",
                    "flagged": "🚩", "hold": "⏸", "changes_requested": "↩",
                }.get(new_status, "❓")
                status_color = {
                    "manually_approved": discord.Color.green(), "rejected": discord.Color.red(),
                    "flagged": discord.Color.orange(), "hold": discord.Color.greyple(),
                    "changes_requested": discord.Color.blue(),
                }.get(new_status, discord.Color.yellow())
                new_embed.color = status_color

                # Update status field
                new_fields = []
                for f in new_embed.fields:
                    if f.name == "🔖 Status":
                        new_fields.append(discord.EmbedField(
                            name="🔖 Status",
                            value=f"{status_emoji} {new_status.replace('_', ' ').title()}",
                            inline=True,
                        ))
                    else:
                        new_fields.append(f)

                rebuilt = discord.Embed(
                    title=new_embed.title,
                    color=new_embed.color,
                    description=new_embed.description,
                )
                rebuilt.set_footer(text=f"Actioned by {interaction.user.display_name}")
                for f in new_fields:
                    rebuilt.add_field(name=f.name, value=f.value, inline=f.inline)

                disabled_view = discord.ui.View()
                for item in RegistrationCardView(reg_id).children:
                    item.disabled = True
                    disabled_view.add_item(item)

                await message.edit(embed=rebuilt, view=disabled_view)
        except Exception as exc:
            logger.warning("Could not update registration card: %s", exc)

    action_labels = {
        "approve": "✅ Approved", "reject": "❌ Rejected",
        "flag": "🚩 Flagged", "hold": "⏸ Put on Hold", "sendback": "↩ Sent Back",
    }
    await interaction.followup.send(
        f"{action_labels.get(action, 'Done')} — registration `{reg_id[:8]}`",
        ephemeral=True,
    )


# ── Helper: post card to verification-queue ───────────────────────────────────

async def post_registration_card(
    bot: discord.Client,
    guild: discord.Guild,
    reg_id: str,
    applicant: discord.Member | None,
    applicant_discord_id: str,
    applicant_name: str,
    tournament_name: str,
    form_data: dict,
    guild_settings: dict,
) -> None:
    """Called from RegistrationModal after a successful submission."""
    channel_ids: dict = guild_settings.get("channel_ids", {})
    vq_id = channel_ids.get("verification_queue")
    if not vq_id:
        # Fallback: try old key
        vq_id = guild_settings.get("verification_queue_channel_id")
    if not vq_id:
        logger.warning("No verification_queue channel configured — skipping card post")
        return

    ch = guild.get_channel(int(vq_id))
    if not isinstance(ch, discord.TextChannel):
        logger.warning("verification_queue channel %s not found in guild %s", vq_id, guild.id)
        return

    mention = f"<@{applicant_discord_id}>"
    embed = build_card_embed(
        reg_id=reg_id,
        applicant_name=applicant_name,
        discord_mention=mention,
        tournament_name=tournament_name,
        form_data=form_data,
    )

    view = RegistrationCardView(registration_id=reg_id)
    bot.add_view(view)

    try:
        await ch.send(embed=embed, view=view)
        logger.info("Posted registration card for %s in #verification-queue", reg_id[:8])
    except discord.Forbidden:
        logger.error("No permission to post in verification-queue channel")
    except Exception as exc:
        logger.error("Failed to post registration card: %s", exc, exc_info=True)
