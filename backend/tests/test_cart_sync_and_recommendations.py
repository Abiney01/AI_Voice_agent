import asyncio
import os
import sys
import unittest
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from app.schemas.conversation import (
    ConversationEvent,
    OrderAction,
    OrderSyncStatus,
    OrderDiscrepancy,
)
from app.services.openai.prompts import (
    build_structured_context_dict,
    build_conversation_messages,
    SYSTEM_PROMPT,
    ORDER_EXTRACTION_PROMPT,
)
from app.services.order_sync import (
    clean_dish_name,
    compute_llm_expected_order,
    validate_order_sync,
)
from app.api.conversations.router import _has_order_intent, _ORDER_INTENT_RE


class TestCartSyncAndRecommendations(unittest.TestCase):
    def test_order_intent_detection(self):
        """Test natural ordering phrases are reliably detected by intent detection."""
        # 1. Direct "I want" phrasing
        self.assertTrue(_has_order_intent("I want two butter naans and one paneer butter masala."))
        # 2. "Actually, make it three" modification phrasing
        self.assertTrue(_has_order_intent("Actually, make it three butter naans."))
        # 3. "Remove paneer butter masala" removal phrasing
        self.assertTrue(_has_order_intent("Remove paneer butter masala."))
        # 4. "Make that three" context reference
        self.assertTrue(_has_order_intent("Make that three."))
        # 5. "Add another biryani"
        self.assertTrue(_has_order_intent("Add another chicken biryani please."))
        # 6. "Drop the fries"
        self.assertTrue(_has_order_intent("Drop the fries."))
        # 7. Casual questions without ordering intent
        self.assertFalse(_has_order_intent("What time do you close tonight?"))
        self.assertFalse(_has_order_intent("Where are you located?"))

    def test_compute_expected_order_modify_prevents_duplicate(self):
        """Test that modifying an existing item updates its quantity without creating duplicate entries."""
        base_cart = {
            "id": 101,
            "status": "active",
            "items": [
                {"menu_item_name": "Butter Naan", "quantity": 2, "unit_price": 60.0},
                {"menu_item_name": "Paneer Butter Masala", "quantity": 1, "unit_price": 240.0},
            ],
        }

        # Customer: "Actually, make it three butter naans."
        actions = [
            {"action": "modify", "menu_item_name": "Butter Naan", "quantity": 3, "customization_notes": None}
        ]
        expected = compute_llm_expected_order(base_cart, actions)

        # Must have exactly 2 unique items
        self.assertEqual(len(expected["items"]), 2)
        naan = next((it for it in expected["items"] if "butter naan" in it["menu_item_name"].lower()), None)
        self.assertIsNotNone(naan)
        self.assertEqual(naan["quantity"], 3)

        paneer = next((it for it in expected["items"] if "paneer" in it["menu_item_name"].lower()), None)
        self.assertIsNotNone(paneer)
        self.assertEqual(paneer["quantity"], 1)

    def test_compute_expected_order_remove_item(self):
        """Test that removing an item removes it completely from expected order."""
        base_cart = {
            "id": 101,
            "status": "active",
            "items": [
                {"menu_item_name": "Butter Naan", "quantity": 3, "unit_price": 60.0},
                {"menu_item_name": "Paneer Butter Masala", "quantity": 1, "unit_price": 240.0},
            ],
        }

        # Customer: "Remove paneer butter masala."
        actions = [
            {"action": "remove", "menu_item_name": "Paneer Butter Masala", "quantity": 1}
        ]
        expected = compute_llm_expected_order(base_cart, actions)

        # Paneer butter masala should be removed
        self.assertEqual(len(expected["items"]), 1)
        self.assertEqual(expected["items"][0]["menu_item_name"], "Butter Naan")
        self.assertEqual(expected["items"][0]["quantity"], 3)

    def test_validate_order_sync_detects_false_success_when_item_missing(self):
        """Test that validate_order_sync flags discrepancy when expected item was not added to cart."""
        llm_order = {
            "id": 101,
            "status": "active",
            "items": [
                {"menu_item_name": "Butter Naan", "quantity": 2},
                {"menu_item_name": "Paneer Butter Masala", "quantity": 1},
            ],
        }
        # Actual database cart only has Butter Naan (Paneer Butter Masala was missing/failed)
        actual_cart = {
            "id": 101,
            "status": "active",
            "items": [
                {"menu_item_name": "Butter Naan", "quantity": 2},
            ],
        }
        sync = validate_order_sync(llm_order, actual_cart)
        self.assertFalse(sync.is_synced)
        self.assertEqual(len(sync.discrepancies), 1)
        self.assertEqual(sync.discrepancies[0].field, "item_missing")
        self.assertEqual(sync.discrepancies[0].item, "Paneer Butter Masala")

    def test_validate_order_sync_detects_quantity_divergence(self):
        """Test that validate_order_sync flags discrepancy when quantity in actual cart differs from expected."""
        llm_order = {
            "id": 101,
            "status": "active",
            "items": [{"menu_item_name": "Butter Naan", "quantity": 3}],
        }
        actual_cart = {
            "id": 101,
            "status": "active",
            "items": [{"menu_item_name": "Butter Naan", "quantity": 2}],
        }
        sync = validate_order_sync(llm_order, actual_cart)
        self.assertFalse(sync.is_synced)
        self.assertEqual(len(sync.discrepancies), 1)
        self.assertEqual(sync.discrepancies[0].field, "quantity")
        self.assertEqual(sync.discrepancies[0].llm_value, 3)
        self.assertEqual(sync.discrepancies[0].cart_value, 2)

    def test_system_prompt_rules_for_recommendations_and_pairings(self):
        """Verify SYSTEM_PROMPT contains the required recommendation, pairing, and cart rules."""
        # Check Menu Recommendation rules
        self.assertIn("NEVER display, recite, or dump the entire menu", SYSTEM_PROMPT)
        self.assertIn("RETURNING CUSTOMERS", SYSTEM_PROMPT)
        self.assertIn("NEW CUSTOMERS", SYSTEM_PROMPT)
        self.assertIn("POPULAR RECOMMENDATIONS", SYSTEM_PROMPT)

        # Check Food Pairing rules
        self.assertIn("INTELLIGENT FOOD PAIRING", SYSTEM_PROMPT)
        self.assertIn("Paneer Butter Masala → Butter Naan or Garlic Naan", SYSTEM_PROMPT)
        self.assertIn("Butter Chicken → Butter Naan or Jeera Rice", SYSTEM_PROMPT)
        self.assertIn("Biryani → Raita", SYSTEM_PROMPT)
        self.assertIn("Fried Rice → Gobi Manchurian", SYSTEM_PROMPT)
        self.assertIn("NEVER automatically add recommendations or pairings to the cart", SYSTEM_PROMPT)

        # Check Context Awareness & References
        self.assertIn("Make that three", SYSTEM_PROMPT)
        self.assertIn("ASK FOR CLARIFICATION", SYSTEM_PROMPT)

        # Check Cart as Single Source of Truth
        self.assertIn("The database `actual_cart` is the SINGLE AUTHORITATIVE TRUTH", SYSTEM_PROMPT)

    def test_order_extraction_prompt_rules_for_context_and_modify(self):
        """Verify ORDER_EXTRACTION_PROMPT guides model to extract modify for 'make that three'."""
        self.assertIn("Recent conversation history", ORDER_EXTRACTION_PROMPT)
        self.assertIn("Make that three", ORDER_EXTRACTION_PROMPT)
        self.assertIn("modify", ORDER_EXTRACTION_PROMPT)
        self.assertIn("clarify", ORDER_EXTRACTION_PROMPT)
        self.assertIn("customization_notes", ORDER_EXTRACTION_PROMPT)


if __name__ == "__main__":
    unittest.main()

