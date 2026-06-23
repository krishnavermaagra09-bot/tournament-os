from app.events.bus import event_bus


async def tournament_created(tournament_id: str, organization_id: str, created_by: str) -> None:
    await event_bus.publish("TournamentCreated", {
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "created_by": created_by,
    })


async def tournament_updated(tournament_id: str, organization_id: str, changes: dict) -> None:
    await event_bus.publish("TournamentUpdated", {
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "changes": changes,
    })


async def tournament_status_changed(
    tournament_id: str, organization_id: str,
    old_status: str, new_status: str
) -> None:
    await event_bus.publish("TournamentStatusChanged", {
        "tournament_id": tournament_id,
        "organization_id": organization_id,
        "old_status": old_status,
        "new_status": new_status,
    })
