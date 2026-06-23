"""
Settings Panel — feature flags + webhook management via buttons and modals.
Triggered from the Control Panel "⚙️ Settings" button.

Sections:
  Feature Flags  — toggle each known flag with one click
  Webhooks       — add / list / remove via modals
"""
import logging
import discord

logger = logging.getLogger(__name__)

_KNOWN_FLAGS: dict[str, str] = {
    "score_auto_approval": "Auto-approve scores when both teams agree",
    "checkin_required":    "Require check-in before going LIVE",
    "allow_score_edit":    "Allow captains to edit scores before confirmation",
    "ai_moderation":       "AI-assisted dispute moderation",
    "solo_auto_team":      "Auto-create solo team on registration submit",
    "snapshot_on_round":   "Auto-snapshot after every round completes",
}


# ── Webhook Modals ────────────────────────────────────────────────────────────

class _AddWebhookModal(discord.ui.Modal, title="🔗 Add Webhook"):
    url    = discord.ui.TextInput(label="Webhook URL (https://...)", placeholder="https://example.com/webhook")
    events = discord.ui.TextInput(label="Events (comma-separated, or * for all)", default="*", required=False)
    secret = discord.ui.TextInput(label="HMAC Secret (optional)", required=False, placeholder="leave blank for unsigned")

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.bot.helpers.formatters import success_embed, error_embed

        url_val = self.url.value.strip()
        if not url_val.startswith("http"):
            await interaction.followup.send(embed=error_embed("URL must start with http:// or https://"), ephemeral=True)
            return

        event_list = [e.strip() for e in self.events.value.split(",") if e.strip()] or ["*"]
        secret_val = self.secret.value.strip()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                t = await session.get(Tournament, self._tournament_id)
                if not t:
                    await interaction.followup.send(embed=error_embed("Tournament not found."), ephemeral=True)
                    return
                config = dict(t.channel_config or {})
                existing: list[dict] = list(config.get("webhooks", []))
                if any(wh.get("url") == url_val for wh in existing):
                    await interaction.followup.send(embed=error_embed("This URL is already registered."), ephemeral=True)
                    return
                entry: dict = {"url": url_val, "events": event_list}
                if secret_val:
                    entry["secret"] = secret_val
                existing.append(entry)
                config["webhooks"] = existing
                t.channel_config = config

        await interaction.followup.send(
            embed=success_embed(
                f"Webhook registered.\nURL: `{url_val[:60]}`\nEvents: `{', '.join(event_list)}`",
                title="✅ Webhook Added",
            ),
            ephemeral=True,
        )
        logger.info("webhook.add: tournament=%s url=%s", self._tournament_id[:8], url_val[:60])


class _RemoveWebhookModal(discord.ui.Modal, title="❌ Remove Webhook"):
    url = discord.ui.TextInput(label="Webhook URL to remove")

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__()
        self._tournament_id = tournament_id
        self._org_id = org_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.bot.helpers.formatters import success_embed, error_embed

        url_val = self.url.value.strip()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                t = await session.get(Tournament, self._tournament_id)
                if not t:
                    await interaction.followup.send(embed=error_embed("Tournament not found."), ephemeral=True)
                    return
                config = dict(t.channel_config or {})
                before = config.get("webhooks", [])
                after  = [wh for wh in before if wh.get("url") != url_val]
                if len(after) == len(before):
                    await interaction.followup.send(embed=error_embed("Webhook URL not found."), ephemeral=True)
                    return
                config["webhooks"] = after
                t.channel_config = config

        await interaction.followup.send(
            embed=success_embed(f"Webhook `{url_val[:60]}` removed.", title="Webhook Removed"),
            ephemeral=True,
        )


# ── Flag Toggle Logic ─────────────────────────────────────────────────────────

async def _toggle_flag(session, tournament_id: str, flag: str, new_value: bool) -> None:
    from app.database.models.tournament import Tournament
    t = await session.get(Tournament, tournament_id)
    if t:
        flags = dict(t.feature_flags or {})
        flags[flag] = new_value
        t.feature_flags = flags


# ── Main View ─────────────────────────────────────────────────────────────────

class SettingsPanelView(discord.ui.View):
    """Ephemeral settings sub-panel — flags + webhook management."""

    def __init__(self, tournament_id: str, org_id: str, tournament_name: str, current_flags: dict):
        super().__init__(timeout=120)
        self.tournament_id   = tournament_id
        self.org_id          = org_id
        self.tournament_name = tournament_name
        self.flags           = dict(current_flags)

        # Add one toggle button per known flag (row 0-1, up to 6 buttons)
        for i, (flag_key, flag_desc) in enumerate(_KNOWN_FLAGS.items()):
            val = self.flags.get(flag_key)
            icon = "✅" if val is True else ("❌" if val is False else "⬜")
            btn = discord.ui.Button(
                label=f"{icon} {flag_key.replace('_',' ').title()[:24]}",
                style=discord.ButtonStyle.secondary,
                row=i // 3,  # 3 per row → rows 0 and 1
                custom_id=f"sflag_{flag_key}_{tournament_id[:8]}",
            )
            btn.callback = self._make_flag_callback(flag_key, val)
            self.add_item(btn)

    def _make_flag_callback(self, flag_key: str, current: bool | None):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            from app.database.session import AsyncSessionLocal
            from app.bot.helpers.formatters import success_embed

            new_val = not current if isinstance(current, bool) else True
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await _toggle_flag(session, self.tournament_id, flag_key, new_val)

            icon = "✅" if new_val else "❌"
            await interaction.followup.send(
                embed=success_embed(
                    f"Flag `{flag_key}` → **{icon} {'enabled' if new_val else 'disabled'}**",
                    title="⚙️ Flag Updated",
                ),
                ephemeral=True,
            )
            logger.info("flag.toggle: flag=%s value=%s tournament=%s by=%s", flag_key, new_val, self.tournament_id[:8], interaction.user.id)
        return callback

    @discord.ui.button(label="🔗 Add Webhook", style=discord.ButtonStyle.primary, row=2)
    async def add_webhook(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_AddWebhookModal(self.tournament_id, self.org_id))

    @discord.ui.button(label="📋 List Webhooks", style=discord.ButtonStyle.secondary, row=2)
    async def list_webhooks(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament

        async with AsyncSessionLocal() as session:
            t = await session.get(Tournament, self.tournament_id)
            webhooks: list[dict] = (t.channel_config or {}).get("webhooks", []) if t else []

        embed = discord.Embed(title=f"🔗 Webhooks — {self.tournament_name}", color=discord.Color.blurple())
        if not webhooks:
            embed.description = "No webhooks registered. Use **🔗 Add Webhook** to add one."
        else:
            for wh in webhooks:
                has_secret = "🔐 Signed" if wh.get("secret") else "🔓 Unsigned"
                events = ", ".join(wh.get("events", ["*"]))
                embed.add_field(
                    name=f"`{wh['url'][:55]}`",
                    value=f"Events: `{events}` | {has_secret}",
                    inline=False,
                )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="❌ Remove Webhook", style=discord.ButtonStyle.danger, row=2)
    async def remove_webhook(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_RemoveWebhookModal(self.tournament_id, self.org_id))
