"""
Persistent "Register Now" button posted in registration channels.

custom_id format: "reg_btn:<tournament_id>:<org_id>"
Max length: 7+1+36+1+36 = 81 chars (under Discord's 100-char limit).
"""
import logging

import discord

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "reg_btn"


def _make_custom_id(tournament_id: str, org_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{tournament_id}:{org_id}"


def _parse_custom_id(custom_id: str) -> tuple[str, str] | None:
    parts = custom_id.split(":", 2)
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    return parts[1], parts[2]


class RegistrationButtonView(discord.ui.View):
    """Persistent view — survives bot restarts via bot.add_view()."""

    def __init__(self, tournament_id: str, org_id: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.org_id = org_id

        btn = discord.ui.Button(
            label="Register Now",
            style=discord.ButtonStyle.primary,
            emoji="📝",
            custom_id=_make_custom_id(tournament_id, org_id),
        )
        btn.callback = self._handle_register
        self.add_item(btn)

    async def _handle_register(self, interaction: discord.Interaction) -> None:
        raw = interaction.data.get("custom_id", "")
        parsed = _parse_custom_id(raw)
        if not parsed:
            await interaction.response.send_message("Invalid button. Contact an admin.", ephemeral=True)
            return
        tournament_id, org_id = parsed

        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import TournamentStatus
        from app.database.repositories.tournament import TournamentRepository
        from app.services.registration.form_builder import FormBuilderService
        from app.bot.views.registration_modal import RegistrationModal
        from app.bot.helpers.formatters import error_embed

        async with AsyncSessionLocal() as session:
            t_repo = TournamentRepository(session)
            tournament = await t_repo.get_by_id(tournament_id, org_id)
            if not tournament:
                await interaction.response.send_message(
                    embed=error_embed("Tournament not found."), ephemeral=True
                )
                return
            if tournament.status != TournamentStatus.REGISTRATION_OPEN:
                await interaction.response.send_message(
                    embed=error_embed(
                        f"Registration is not open right now (status: **{tournament.status.value.replace('_', ' ').title()}**)."
                    ),
                    ephemeral=True,
                )
                return

            fb = FormBuilderService(session)
            form = await fb.get_active_form(org_id, tournament.id)
            fields: list[dict] = []
            if form and form.fields:
                fields = [
                    {
                        "field_key": f.field_key,
                        "label": f.label,
                        "is_required": f.is_required,
                        "long_text": f.field_type.value == "long_text",
                        "placeholder": "",
                    }
                    for f in form.fields
                ]
            else:
                fields = [
                    {
                        "field_key": "in_game_name",
                        "label": "In-Game Name",
                        "is_required": True,
                        "long_text": False,
                        "placeholder": "Your IGN",
                    }
                ]
            t_id = tournament.id

        modal = RegistrationModal(
            tournament_id=t_id,
            organization_id=org_id,
            fields=fields[:5],
        )
        await interaction.response.send_modal(modal)
