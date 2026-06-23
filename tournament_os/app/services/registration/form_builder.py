"""
Dynamic registration form builder service.
Supports unlimited custom fields with conditional logic.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.registration import (
    RegistrationForm, FormField, FormFieldType
)
from app.database.repositories.registration import RegistrationRepository

logger = logging.getLogger(__name__)


class FormBuilderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_form(
        self, organization_id: str, tournament_id: str
    ) -> RegistrationForm | None:
        from sqlalchemy import select
        q = (
            select(RegistrationForm)
            .where(RegistrationForm.organization_id == organization_id)
            .where(RegistrationForm.tournament_id == tournament_id)
            .where(RegistrationForm.is_active.is_(True))
            .order_by(RegistrationForm.version.desc())
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()

    async def create_form(
        self, organization_id: str, tournament_id: str, fields: list[dict]
    ) -> RegistrationForm:
        # Deactivate existing active form
        existing = await self.get_active_form(organization_id, tournament_id)
        if existing:
            existing.is_active = False
            version = existing.version + 1
        else:
            version = 1

        form = RegistrationForm(
            organization_id=organization_id,
            tournament_id=tournament_id,
            version=version,
            is_active=True,
        )
        self.session.add(form)
        await self.session.flush()
        await self.session.refresh(form)

        for i, field_def in enumerate(fields):
            field = FormField(
                organization_id=organization_id,
                form_id=form.id,
                tournament_id=tournament_id,
                field_key=field_def["field_key"],
                label=field_def["label"],
                field_type=FormFieldType(field_def["field_type"]),
                is_required=field_def.get("is_required", False),
                is_unique=field_def.get("is_unique", False),
                display_order=field_def.get("display_order", i),
                options=field_def.get("options", []),
                conditional_logic=field_def.get("conditional_logic", {}),
                validation_rules=field_def.get("validation_rules", {}),
            )
            self.session.add(field)

        await self.session.flush()
        return form

    def validate_submission(self, form: RegistrationForm, data: dict) -> list[str]:
        """Returns list of validation error messages. Empty = valid."""
        errors: list[str] = []
        for field in form.fields:
            value = data.get(field.field_key)

            # Conditional logic — skip hidden fields
            if field.conditional_logic:
                condition_field = field.conditional_logic.get("show_if_field")
                condition_value = field.conditional_logic.get("show_if_value")
                if condition_field and data.get(condition_field) != condition_value:
                    continue

            if field.is_required and (value is None or value == "" or value == []):
                errors.append(f"Field '{field.label}' is required.")
                continue

            if value is None:
                continue

            # Type-specific validation
            if field.field_type == FormFieldType.NUMBER:
                try:
                    float(str(value))
                except ValueError:
                    errors.append(f"Field '{field.label}' must be a number.")

            if field.field_type == FormFieldType.DROPDOWN:
                allowed = [opt if isinstance(opt, str) else opt.get("value") for opt in field.options]
                if str(value) not in allowed:
                    errors.append(f"Field '{field.label}' must be one of: {', '.join(allowed)}")

            rules = field.validation_rules
            if rules.get("max_length") and isinstance(value, str) and len(value) > rules["max_length"]:
                errors.append(f"Field '{field.label}' exceeds maximum length of {rules['max_length']}.")

        return errors

    def get_unique_field_keys(self, form: RegistrationForm) -> list[str]:
        return [f.field_key for f in form.fields if f.is_unique]
