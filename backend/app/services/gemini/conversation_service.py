import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from app.services.gemini.client import get_gemini_client
from app.services.gemini.prompts import (
    MEMORY_SUMMARIZE_PROMPT,
    ORDER_EXTRACTION_PROMPT,
    PREFERENCE_EXTRACTION_PROMPT,
    build_conversation_prompt,
)

logger = logging.getLogger(__name__)


class ConversationService:
    """Handles all Gemini-powered conversation tasks."""

    def _get_model(self):
        return get_gemini_client()

    async def _generate(self, prompt: str, generation_config: Optional[Dict] = None) -> str:
        """
        Run generate_content in a thread-pool executor so it never blocks the
        asyncio event loop. The google-generativeai SDK is synchronous; without
        this wrapper every LLM call would freeze all concurrent requests.
        """
        model = self._get_model()
        loop = asyncio.get_running_loop()

        def _call():
            if generation_config:
                return model.generate_content(prompt, generation_config=generation_config)
            return model.generate_content(prompt)

        response = await loop.run_in_executor(None, _call)
        return response.text.strip()

    async def chat(
        self,
        customer_name: Optional[str],
        preferences: Optional[Dict[str, Any]],
        menu_summary: str,
        current_order: Optional[Dict[str, Any]],
        recent_memories: List[str],
        conversation_history: List[Dict[str, str]],
        user_message: str,
    ) -> str:
        """Generate an AI concierge response."""
        prompt = build_conversation_prompt(
            customer_name=customer_name,
            preferences=preferences,
            menu_summary=menu_summary,
            current_order=current_order,
            recent_memories=recent_memories,
            conversation_history=conversation_history,
            user_message=user_message,
        )
        try:
            return await self._generate(prompt)
        except Exception as e:
            logger.error(f"Gemini chat error: {e}")
            return (
                "I'm sorry, I'm having trouble processing your request right now. "
                "Could you please try again?"
            )

    async def extract_order_actions(
        self, message: str, menu_summary: str
    ) -> List[Dict[str, Any]]:
        """Extract structured order actions from a customer message."""
        # Escape curly braces in user message to prevent Python format-string injection
        safe_message = message.replace("{", "{{").replace("}", "}}")
        prompt = ORDER_EXTRACTION_PROMPT.format(
            menu_summary=menu_summary, message=safe_message
        )
        try:
            text = await self._generate(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            actions = json.loads(text)
            if not isinstance(actions, list):
                actions = [actions]
            return actions
        except json.JSONDecodeError:
            logger.warning(f"Could not parse order extraction JSON: {text!r:.200}")
            return [{"action": "none"}]
        except Exception as e:
            logger.error(f"Order extraction error: {e}")
            return [{"action": "none"}]

    async def summarize_conversation(self, conversation: str) -> str:
        """Summarize a conversation into a memory fact."""
        prompt = MEMORY_SUMMARIZE_PROMPT.format(conversation=conversation)
        try:
            return await self._generate(prompt)
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return ""

    async def extract_preferences(self, summary: str) -> Dict[str, Any]:
        """Extract structured preferences from a conversation summary."""
        prompt = PREFERENCE_EXTRACTION_PROMPT.format(summary=summary)
        try:
            text = await self._generate(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            return json.loads(text)
        except Exception as e:
            logger.error(f"Preference extraction error: {e}")
            return {}
