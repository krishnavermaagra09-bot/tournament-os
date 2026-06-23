"""
AI assistant REST API endpoint — for non-Discord integrations or dashboard use.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.ai.assistant.agent import TournamentAIAgent

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatRequest(BaseModel):
    organization_id: str
    guild_id: str
    user_id: str
    discord_user_id: str
    message: str
    tournament_id: str | None = None
    thread_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    escalated: bool = False
    dispute_id: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        agent = TournamentAIAgent(session)
        try:
            result = await agent.chat(
                organization_id=body.organization_id,
                guild_id=body.guild_id,
                tournament_id=body.tournament_id,
                user_id=body.user_id,
                discord_user_id=body.discord_user_id,
                message=body.message,
                thread_id=body.thread_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return ChatResponse(**result)
