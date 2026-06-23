"""
Dynamic registration modal — built from the tournament's form fields.
Discord modals support up to 5 text inputs, so we paginate for longer forms.

After a successful submission the bot automatically posts a registration card
in the #verification-queue channel so staff can action it without any commands.
"""
import asyncio
import logging

import discord

logger = logging.getLogger(__name__)

MAX_MODAL_FIELDS = 5


class RegistrationModal(discord.ui.Modal, title="Tournament Registration"):
    """
    A single-page registration modal (up to 5 fields).
    For longer forms, multiple modals are shown in sequence.
    """

    def __init__(self, tournament_id: str, organization_id: str, fields: list[dict], page: int = 0):
        super().__init__(title=f"Registration (Page {page + 1})" if page > 0 else "Tournament Registration")
        self.tournament_id = tournament_id
        self.organization_id = organization_id
        self.page = page
        self.field_keys: list[str] = []

        for f in fields[:MAX_MODAL_FIELDS]:
            style = discord.TextStyle.paragraph if f.get("long_text") else discord.TextStyle.short
            self.field_keys.append(f["field_key"])
            self.add_item(
                discord.ui.TextInput(
                    label=f["label"][:45],
                    placeholder=f.get("placeholder", ""),
                    required=f.get("is_required", False),
                    style=style,
                    max_length=1000,
                    custom_id=f["field_key"],
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        form_data = {item.custom_id: item.value for item in self.children if hasattr(item, "value")}
        form_data["username"] = interaction.user.name

        from app.database.session import AsyncSessionLocal
        from app.database.models.guild import Guild
        from app.database.repositories.tournament import TournamentRepository
        from app.services.registration.form_builder import FormBuilderService
        from app.services.registration.approvals import RegistrationApprovalService
        from app.bot.helpers.formatters import registration_embed, error_embed
        from sqlalchemy import select

        reg_id: str | None = None
        tournament_name: str = ""
        guild_settings: dict = {}

        async with AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    t_repo = TournamentRepository(session)
                    tournament = await t_repo.get_by_id(self.tournament_id, self.organization_id)
                    if not tournament:
                        await interaction.followup.send(embed=error_embed("Tournament not found."), ephemeral=True)
                        return

                    tournament_name = tournament.name

                    # Get guild settings for card posting (inside session while it's open)
                    if interaction.guild_id:
                        g_q = select(Guild).where(
                            Guild.discord_guild_id == str(interaction.guild_id),
                            Guild.deleted_at.is_(None),
                        )
                        g_row = (await session.execute(g_q)).scalar_one_or_none()
                        if g_row:
                            guild_settings = dict(g_row.settings or {})

                    fb = FormBuilderService(session)
                    form = await fb.get_active_form(self.organization_id, self.tournament_id)

                    unique_fields: list[str] = []
                    if form:
                        errors = fb.validate_submission(form, form_data)
                        if errors:
                            await interaction.followup.send(
                                embed=error_embed("Please fix the following:\n" + "\n".join(f"• {e}" for e in errors)),
                                ephemeral=True,
                            )
                            return
                        unique_fields = fb.get_unique_field_keys(form)

                    svc = RegistrationApprovalService(session)
                    reg = await svc.submit(
                        tournament=tournament,
                        discord_user_id=str(interaction.user.id),
                        form_data=form_data,
                        unique_field_keys=unique_fields,
                    )
                    reg_id = reg.id

                    await interaction.followup.send(embed=registration_embed(reg), ephemeral=True)

                except ValueError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                    return
                except Exception as e:
                    logger.error("Registration modal error: %s", e, exc_info=True)
                    await interaction.followup.send(embed=error_embed("An unexpected error occurred."), ephemeral=True)
                    return

        # ── Post registration card to #verification-queue (async, non-blocking) ──
        if reg_id and interaction.guild and guild_settings:
            from app.bot.views.registration_card_view import post_registration_card
            d_guild = interaction.guild

            asyncio.create_task(
                post_registration_card(
                    bot=interaction.client,
                    guild=d_guild,
                    reg_id=reg_id,
                    applicant=d_guild.get_member(interaction.user.id),
                    applicant_discord_id=str(interaction.user.id),
                    applicant_name=interaction.user.display_name,
                    tournament_name=tournament_name,
                    form_data=form_data,
                    guild_settings=guild_settings,
                )
            )
