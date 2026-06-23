"""
AI Tournament Assistant — powered by Groq (llama-3.3-70b-versatile).
Context is always scoped to organization_id + guild_id + tournament_id.
If the AI cannot resolve an issue, it escalates to a human support ticket.
"""
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ai.context.builder import ContextBuilder
from app.ai.tools.db_tools import AIDBTools
from app.database.models.ai_session import AISession
from app.database.models.dispute import DisputeCaseType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful Tournament Support AI for a gaming tournament platform.
You have access to live tournament data through function calls.
Always be concise, accurate, and friendly.
When you don't know something, say so — never guess about tournament-specific data.
If a user's issue cannot be resolved through information alone (e.g., score disputes, cheating reports,
verification problems), escalate to a human staff member by calling the escalate_to_human function.
Never reveal data from other tournaments or organizations."""


class TournamentAIAgent:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_or_create_session(
        self,
        organization_id: str,
        guild_id: str,
        tournament_id: str | None,
        user_id: str,
        thread_id: str | None = None,
    ) -> AISession:
        from sqlalchemy import select
        q = (
            select(AISession)
            .where(AISession.organization_id == organization_id)
            .where(AISession.user_id == user_id)
            .where(AISession.tournament_id == tournament_id)
            .where(AISession.escalated_to.is_(None))
            .order_by(AISession.created_at.desc())
        )
        result = await self.session.execute(q)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        sess = AISession(
            organization_id=organization_id,
            guild_id=guild_id,
            tournament_id=tournament_id,
            user_id=user_id,
            thread_id=thread_id,
            messages=[],
        )
        self.session.add(sess)
        await self.session.flush()
        await self.session.refresh(sess)
        return sess

    async def chat(
        self,
        organization_id: str,
        guild_id: str,
        tournament_id: str | None,
        user_id: str,
        discord_user_id: str,
        message: str,
        thread_id: str | None = None,
    ) -> dict:
        """Process one chat turn. Returns {reply, escalated, dispute_id}."""
        if not settings.groq_api_key:
            return {
                "reply": "AI assistant is not configured (GROQ_API_KEY missing). Please contact staff.",
                "escalated": False,
                "dispute_id": None,
            }

        ai_session = await self._get_or_create_session(
            organization_id, guild_id, tournament_id, user_id, thread_id
        )

        # If already escalated, stop responding and point to the ticket
        if ai_session.escalated_to:
            return {
                "reply": (
                    "This session has already been escalated to a human staff member. "
                    f"Your ticket ID is `{ai_session.escalated_to[:8]}`. They will assist you shortly."
                ),
                "escalated": True,
                "dispute_id": ai_session.escalated_to,
            }

        ctx_builder = ContextBuilder(self.session)
        ctx = await ctx_builder.build(organization_id, guild_id, tournament_id, discord_user_id)

        db_tools = AIDBTools(self.session, organization_id, tournament_id)

        messages = list(ai_session.messages)
        messages.append({"role": "user", "content": message})

        groq_messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT + f"\n\nCurrent context:\n{json.dumps(ctx, default=str)}",
            }
        ]
        # Keep last 20 turns to stay within context window
        groq_messages.extend(messages[-20:])

        reply_content = ""
        escalated = False
        dispute_id = None

        try:
            import asyncio
            from groq import AsyncGroq

            # Hard timeout at the HTTP client level (seconds) — prevents indefinite hangs
            _GROQ_TIMEOUT = 25.0
            client = AsyncGroq(api_key=settings.groq_api_key, timeout=_GROQ_TIMEOUT)

            tools = self._build_tools()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.groq_model,
                    messages=groq_messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=1024,
                ),
                timeout=_GROQ_TIMEOUT + 5,
            )

            for choice in response.choices:
                msg = choice.message

                if msg.tool_calls:
                    # Append the assistant's tool-call message before tool results
                    groq_messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ]})

                    for tc in msg.tool_calls:
                        fn_name = tc.function.name
                        fn_args = json.loads(tc.function.arguments or "{}")
                        tool_result = await self._call_tool(
                            db_tools, fn_name, fn_args, discord_user_id
                        )

                        # Always append tool result — keeps conversation history valid
                        # for any subsequent Groq calls (required by the API spec)
                        groq_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(tool_result, default=str),
                        })

                        if fn_name == "escalate_to_human":
                            escalated = True
                            from app.services.dispute.case_manager import DisputeCaseManager
                            dm = DisputeCaseManager(self.session)
                            dispute = await dm.open_dispute(
                                organization_id=organization_id,
                                tournament_id=tournament_id or "",
                                opened_by=user_id,
                                case_type=DisputeCaseType.GENERAL_SUPPORT,
                                description=message,
                                thread_id=thread_id,
                                ai_context={"messages": messages, "context": ctx},
                            )
                            dispute_id = dispute.id
                            ai_session.escalated_to = dispute_id
                            reply_content = (
                                f"I've escalated your issue to a human staff member. "
                                f"Your ticket ID is `{dispute_id[:8]}`. "
                                "Staff will review it shortly — I won't reply further in this thread."
                            )

                    if not escalated:
                        # Second pass: get natural-language answer with tool results in context
                        follow_up = await asyncio.wait_for(
                            client.chat.completions.create(
                                model=settings.groq_model,
                                messages=groq_messages,
                                max_tokens=512,
                            ),
                            timeout=_GROQ_TIMEOUT + 5,
                        )
                        if follow_up.choices:
                            reply_content = follow_up.choices[0].message.content or ""
                else:
                    reply_content = msg.content or ""

        except TimeoutError:
            logger.warning("Groq API timed out after %ss", _GROQ_TIMEOUT)
            reply_content = (
                "⏱️ The AI assistant took too long to respond. "
                "Please try again in a moment, or contact staff directly."
            )
        except Exception as e:
            logger.error("Groq API error: %s", e, exc_info=True)
            reply_content = (
                "I'm having trouble connecting to the AI service right now. "
                "Please try again in a moment or contact staff directly."
            )

        # Persist the conversation
        messages.append({"role": "assistant", "content": reply_content})
        ai_session.messages = messages
        await self.session.flush()

        return {
            "reply": reply_content,
            "escalated": escalated,
            "dispute_id": dispute_id,
        }

    def _build_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_my_registration",
                    "description": "Get the calling user's registration status for the current tournament.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_my_matches",
                    "description": "Get the calling user's upcoming and past matches in the current tournament.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_standings",
                    "description": "Get the current standings/leaderboard for the tournament.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Max teams to return (default 10)",
                                "default": 10,
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_live_matches",
                    "description": "Get all matches currently in LIVE status for the tournament.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_tournament_info",
                    "description": "Get general tournament info: name, game, format, dates, rules, prize pool.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "escalate_to_human",
                    "description": (
                        "Escalate the conversation to a human staff member. "
                        "Use when the issue requires manual review (score disputes, cheating, bans, etc.)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Why escalation is needed",
                            }
                        },
                        "required": ["reason"],
                    },
                },
            },
        ]

    async def _call_tool(
        self, db_tools: AIDBTools, fn_name: str, args: dict, discord_user_id: str
    ) -> object:
        try:
            if fn_name == "get_my_registration":
                return await db_tools.get_my_registration(discord_user_id)
            elif fn_name == "get_my_matches":
                return await db_tools.get_my_matches(discord_user_id)
            elif fn_name == "get_standings":
                return await db_tools.get_standings(limit=args.get("limit", 10))
            elif fn_name == "get_live_matches":
                return await db_tools.get_live_matches()
            elif fn_name == "get_tournament_info":
                return await db_tools.get_tournament_info()
            elif fn_name == "escalate_to_human":
                # Handled in the caller; return acknowledgement for the tool-result slot
                return {"escalating": True, "reason": args.get("reason", "")}
            else:
                return {"error": f"Unknown tool: {fn_name}"}
        except Exception as e:
            logger.error("Tool %s error: %s", fn_name, e, exc_info=True)
            return {"error": str(e)}
