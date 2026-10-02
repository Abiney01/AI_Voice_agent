import asyncio
import json
import unittest
from dotenv import load_dotenv

load_dotenv()

from app.schemas.conversation import ConversationEvent, OrderAction, ChatResponse
from app.services.openai.prompts import build_structured_context_dict, build_conversation_messages
from app.services.openai.conversation_service import ConversationService


class TestContextFlow(unittest.TestCase):
    def test_structured_context_schema_consistency(self):
        """Verify the structured context schema matches required structure."""
        events = [
            ConversationEvent(
                type="item_added",
                status="success",
                is_retryable=True,
                details={"item_name": "Veg Biryani", "quantity": 1}
            ).model_dump()
        ]
        sample_order = {
            "id": 19,
            "status": "active",
            "total_amount": 220.0,
            "items": [
                {
                    "menu_item_name": "Veg Biryani",
                    "quantity": 1,
                    "unit_price": 220.0,
                    "subtotal": 220.0,
                    "customization_notes": None,
                }
            ],
        }
        ctx = build_structured_context_dict(
            user_intent="order_add",
            current_request="I want to order Veg Biryani",
            conversation_history=[{"role": "user", "content": "hello"}],
            order=sample_order,
            customer_name="Rahul",
            customer_preferences={"spice_level": "hot"},
            recent_memories=["Prefers spicy food"],
            events=events,
        )

        # Check top-level keys
        self.assertIn("conversation", ctx)
        self.assertIn("state", ctx)
        self.assertIn("events", ctx)

        # Check conversation fields
        self.assertEqual(ctx["conversation"]["user_intent"], "order_add")
        self.assertEqual(ctx["conversation"]["current_request"], "I want to order Veg Biryani")
        self.assertIsInstance(ctx["conversation"]["previous_messages"], list)

        # Check state fields
        self.assertEqual(ctx["state"]["order_status"], "active")
        self.assertIn("required_information", ctx["state"])
        self.assertIn("collected_information", ctx["state"])
        self.assertTrue(ctx["state"]["required_information"]["has_items"])
        self.assertFalse(ctx["state"]["required_information"]["order_confirmed"])
        self.assertFalse(ctx["state"]["required_information"]["is_terminal"])

        # Check collected_information
        self.assertEqual(ctx["state"]["collected_information"]["customer_name"], "Rahul")
        self.assertEqual(ctx["state"]["collected_information"]["total_amount"], 220.0)
        self.assertEqual(len(ctx["state"]["collected_information"]["items"]), 1)

        # Check events
        self.assertEqual(len(ctx["events"]), 1)
        self.assertEqual(ctx["events"][0]["type"], "item_added")
        self.assertTrue(ctx["events"][0]["is_retryable"])

    def test_terminal_event_structure(self):
        """Verify that confirm event sets is_retryable=False and marks state terminal."""
        events = [
            ConversationEvent(
                type="order_confirmed",
                status="confirmed",
                is_retryable=False,
                details={"order_id": 19, "total_amount": 290.0}
            ).model_dump()
        ]
        sample_order = {
            "id": 19,
            "status": "confirmed",
            "total_amount": 290.0,
            "items": [
                {"menu_item_name": "Veg Biryani", "quantity": 1, "unit_price": 220.0, "subtotal": 220.0},
                {"menu_item_name": "Sweet Lassi", "quantity": 1, "unit_price": 70.0, "subtotal": 70.0},
            ],
        }
        ctx = build_structured_context_dict(
            user_intent="order_confirm",
            current_request="place my order",
            conversation_history=[],
            order=sample_order,
            customer_name="Rahul",
            customer_preferences={"spice_level": "hot"},
            recent_memories=[],
            events=events,
        )

        self.assertEqual(ctx["state"]["order_status"], "confirmed")
        self.assertTrue(ctx["state"]["required_information"]["order_confirmed"])
        self.assertTrue(ctx["state"]["required_information"]["is_terminal"])
        self.assertFalse(ctx["events"][0]["is_retryable"])

    def test_prompt_messages_contain_structured_json(self):
        """Verify build_conversation_messages includes valid structured context JSON."""
        events = [
            ConversationEvent(
                type="order_confirmed",
                status="confirmed",
                is_retryable=False,
                details={"order_id": 19}
            ).model_dump()
        ]
        ctx = build_structured_context_dict(
            user_intent="order_confirm",
            current_request="place my order",
            conversation_history=[],
            order={"id": 19, "status": "confirmed", "total_amount": 290.0, "items": []},
            customer_name="Rahul",
            customer_preferences={},
            recent_memories=[],
            events=events,
        )

        messages = build_conversation_messages(
            customer_name="Rahul",
            preferences={},
            menu_summary="Veg Biryani - 220, Sweet Lassi - 70",
            current_order={"id": 19, "status": "confirmed", "total_amount": 290.0, "items": []},
            recent_memories=[],
            conversation_history=[],
            user_message="place my order",
            structured_context=ctx,
        )

        # Message 0: system identity
        # Message 1: menu
        # Message 2: structured context JSON
        context_msg = messages[2]
        self.assertEqual(context_msg["role"], "system")
        self.assertIn("--- CURRENT STRUCTURED CONTEXT (JSON) ---", context_msg["content"])

        # Extract and parse the embedded JSON
        content = context_msg["content"]
        start_idx = content.find("{")
        end_idx = content.rfind("}") + 1
        parsed = json.loads(content[start_idx:end_idx])

        self.assertEqual(parsed["conversation"]["user_intent"], "order_confirm")
        self.assertEqual(parsed["state"]["order_status"], "confirmed")
        self.assertFalse(parsed["events"][0]["is_retryable"])


if __name__ == "__main__":
    unittest.main()
