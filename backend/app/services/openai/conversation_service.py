import json
import logging
from typing import Any, Dict, List, Optional

from app.services.openai.client import get_openai_client
from app.services.openai.prompts import (
    MEMORY_SUMMARIZE_PROMPT,
    ORDER_EXTRACTION_PROMPT,
    PREFERENCE_EXTRACTION_PROMPT,
    build_conversation_messages,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ConversationService:
    """Handles all OpenAI-powered conversation tasks using gpt-4o-mini."""

    def _get_client(self):
        return get_openai_client()

    async def _generate(self, prompt: str, json_mode: bool = False) -> str:
        """
        Call OpenAI with a single user message (used for extraction / summarization tasks).
        These tasks don't need multi-turn history — one self-contained prompt is enough.
        """
        client = self._get_client()
        messages = [{"role": "user", "content": prompt}]

        kwargs: Dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        completion = None
        for attempt in range(3):
            try:
                completion = await client.chat.completions.create(
                    messages=messages,
                    model=settings.openai_model,
                    temperature=0.1,  # deterministic for structured outputs
                    timeout=15.0,     # prevent indefinite hangs on API hiccups
                    **kwargs,
                )
                break
            except Exception as e:
                if ("429" in str(e) or "rate limit" in str(e).lower()) and attempt < 2:
                    logger.warning("[OPENAI] 429 rate limit hit in _generate, backing off 1.5s (attempt %d/3)", attempt + 1)
                    await asyncio.sleep(1.5)
                else:
                    raise

        # content can be None in openai SDK v2 (e.g. content_filter refusal)
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty/null response content")

        response = content.strip()
        # Clean up any stray 'Diaa:' prefix
        if response.startswith("Diaa:"):
            response = response[len("Diaa:"):].strip()
        return response

    async def _generate_chat(self, messages: List[Dict[str, str]]) -> str:
        """
        Call OpenAI with a proper multi-turn messages array.
        Used for the main conversation — preserves system/user/assistant roles
        so gpt-4o-mini handles context correctly.
        """
        client = self._get_client()

        completion = None
        for attempt in range(3):
            try:
                completion = await client.chat.completions.create(
                    messages=messages,
                    model=settings.openai_model,
                    temperature=0.7,  # slightly higher for natural, varied responses
                    timeout=15.0,     # prevent indefinite hangs on API hiccups
                )
                break
            except Exception as e:
                if ("429" in str(e) or "rate limit" in str(e).lower()) and attempt < 2:
                    logger.warning("[OPENAI] 429 rate limit hit in _generate_chat, backing off 1.5s (attempt %d/3)", attempt + 1)
                    await asyncio.sleep(1.5)
                else:
                    raise

        content = completion.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty/null response content")

        response = content.strip()
        if response.startswith("Diaa:"):
            response = response[len("Diaa:"):].strip()
        return response

    async def chat(
        self,
        customer_name: Optional[str],
        preferences: Optional[Dict[str, Any]],
        menu_summary: str,
        current_order: Optional[Dict[str, Any]],
        recent_memories: List[str],
        conversation_history: List[Dict[str, str]],
        user_message: str,
        recent_action_summary: Optional[str] = None,
        structured_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate an AI concierge response using native OpenAI multi-turn format."""
        messages = build_conversation_messages(
            customer_name=customer_name,
            preferences=preferences,
            menu_summary=menu_summary,
            current_order=current_order,
            recent_memories=recent_memories,
            conversation_history=conversation_history,
            user_message=user_message,
            recent_action_summary=recent_action_summary,
            structured_context=structured_context,
        )
        try:
            return await self._generate_chat(messages)
        except Exception as e:
            logger.error(f"OpenAI chat error: {e}", exc_info=True)
            return (
                "I'm sorry, I'm having trouble processing your request right now. "
                "Could you please try again?"
            )

    async def extract_order_actions(
        self,
        message: str,
        current_order_summary: str = "Empty (nothing ordered yet)",
        last_assistant_message: str = "",
        available_menu_items: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract structured order actions from a customer message.

        available_menu_items: comma-separated or newline-separated dish names from the menu.
        current_order_summary: compact text description of what's already in the cart.
        last_assistant_message: what the AI spoke in previous turn.
        """
        # Escape any stray braces in the user message before injecting into the template.
        safe_message = message.replace("{", "{{").replace("}", "}}")
        safe_order = current_order_summary.replace("{", "{{").replace("}", "}}")
        safe_last_assistant = last_assistant_message.replace("{", "{{").replace("}", "}}")
        safe_menu_items = available_menu_items.replace("{", "{{").replace("}", "}}")

        prompt = ORDER_EXTRACTION_PROMPT.format(
            available_menu_items=safe_menu_items,
            message=safe_message,
            current_order=safe_order,
            last_assistant_message=safe_last_assistant,
        )
        text = ""

        try:
            # Use plain text mode (no json_object) so the model can return a JSON array.
            text = await self._generate(prompt, json_mode=False)
            # Strip markdown fences if the model wraps the JSON in ```json ... ```
            stripped = text.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(stripped)
            # Happy path: model returned a JSON array directly.
            if isinstance(data, list):
                return data
            # Fallback: model wrapped the array in an object, e.g. {"actions": [...]}
            # Find the first list value in the object.
            for v in data.values():
                if isinstance(v, list):
                    logger.debug("[EXTRACT] Unwrapped object-wrapped action array")
                    return v
            # If the object itself looks like a single action, wrap it in a list.
            if "action" in data:
                return [data]
            logger.warning("[EXTRACT] Unexpected JSON shape, defaulting to none: %r", stripped[:200])
            return [{"action": "none"}]
        except json.JSONDecodeError:
            logger.warning("[EXTRACT] Could not parse extraction JSON: %r", text[:200])
            return [{"action": "none"}]
        except Exception as e:
            logger.error("[EXTRACT] Order extraction error: %s", e, exc_info=True)
            return [{"action": "none"}]


    async def summarize_conversation(self, conversation: str) -> str:
        """Summarize a conversation into a memory fact."""
        prompt = MEMORY_SUMMARIZE_PROMPT.format(conversation=conversation)
        try:
            return await self._generate(prompt)
        except Exception as e:
            logger.error(f"Summarization error: {e}", exc_info=True)
            return ""

    async def extract_preferences(self, summary: str) -> Dict[str, Any]:
        """Extract structured preferences from a conversation summary."""
        prompt = PREFERENCE_EXTRACTION_PROMPT.format(summary=summary)
        try:
            text = await self._generate(prompt, json_mode=True)
            return json.loads(text)
        except Exception as e:
            logger.error(f"Preference extraction error: {e}", exc_info=True)
            return {}
