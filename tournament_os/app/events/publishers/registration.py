from app.events.bus import event_bus


async def registration_submitted(
    registration_id: str, tournament_id: str, organization_id: str,
    submitted_by: str, has_duplicates: bool = False
) -> None:
    await event_bus.publish("RegistrationSubmitted", {
        "registration_id": registration_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "submitted_by": submitted_by,
        "has_duplicates": has_duplicates,
    })


async def registration_approved(
    registration_id: str, tournament_id: str, organization_id: str,
    submitted_by: str, reviewed_by: str
) -> None:
    await event_bus.publish("RegistrationApproved", {
        "registration_id": registration_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "submitted_by": submitted_by,
        "reviewed_by": reviewed_by,
    })


async def registration_rejected(
    registration_id: str, tournament_id: str, organization_id: str,
    submitted_by: str, reviewed_by: str, reason: str
) -> None:
    await event_bus.publish("RegistrationRejected", {
        "registration_id": registration_id,
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "submitted_by": submitted_by,
        "reviewed_by": reviewed_by,
        "reason": reason,
    })
