import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.services.restrictions.allergy_validator import (
    extract_restrictions_from_text,
    check_dish_conflict,
    scan_and_remove_cart_conflicts,
    ALLERGEN_SYNONYMS,
)
from app.services.order_service import OrderService
from app.schemas.order import OrderItemAdd


class TestAllergyExtraction(unittest.TestCase):
    def test_extract_allergy_peanuts(self):
        text = "I'm allergic to peanuts."
        allergies, dislikes = extract_restrictions_from_text(text)
        self.assertIn("peanut", allergies)
        self.assertEqual(dislikes, [])

    def test_extract_dislike_mushrooms(self):
        text = "I don't like mushrooms."
        allergies, dislikes = extract_restrictions_from_text(text)
        self.assertEqual(allergies, [])
        self.assertIn("mushroom", dislikes)

    def test_extract_retroactive_prawns(self):
        text = "Actually, I'm allergic to prawns."
        allergies, dislikes = extract_restrictions_from_text(text)
        self.assertIn("prawn", allergies)
        self.assertEqual(dislikes, [])

    def test_extract_multiple_restrictions(self):
        text = "I have a dairy allergy and I don't eat onions"
        allergies, dislikes = extract_restrictions_from_text(text)
        self.assertIn("dairy", allergies)
        self.assertIn("onion", dislikes)

    def test_extract_no_gluten(self):
        text = "No gluten, I'm allergic"
        allergies, dislikes = extract_restrictions_from_text(text)
        self.assertIn("gluten", allergies)


class TestDishConflictChecking(unittest.TestCase):
    def setUp(self):
        self.peanut_noodles = MagicMock(
            name="Peanut Noodles",
            description="Egg noodles tossed in peanut sauce with veggies",
            allergens="Peanuts, Gluten, Soy",
        )
        self.peanut_noodles.name = "Peanut Noodles"

        self.mushroom_rice = MagicMock(
            name="Mushroom Fried Rice",
            description="Wok-tossed rice with fresh mushrooms and scallions",
            allergens="Soy",
        )
        self.mushroom_rice.name = "Mushroom Fried Rice"

        self.prawns_dish = MagicMock(
            name="Garlic Butter Prawns",
            description="Succulent prawns sautéed in garlic herb butter",
            allergens="Shellfish, Dairy",
        )
        self.prawns_dish.name = "Garlic Butter Prawns"

        self.jeera_rice = MagicMock(
            name="Jeera Rice",
            description="Basmati rice tempered with cumin seeds",
            allergens="",
        )
        self.jeera_rice.name = "Jeera Rice"

    def test_allergy_conflict_detected(self):
        conflict_type, ing = check_dish_conflict(
            menu_item=self.peanut_noodles,
            allergies=["peanut"],
            dislikes=[],
        )
        self.assertEqual(conflict_type, "allergy")
        self.assertEqual(ing, "peanut")

    def test_dislike_conflict_detected(self):
        conflict_type, ing = check_dish_conflict(
            menu_item=self.mushroom_rice,
            allergies=[],
            dislikes=["mushroom"],
        )
        self.assertEqual(conflict_type, "dislike")
        self.assertEqual(ing, "mushroom")

    def test_prawns_synonym_allergy(self):
        conflict_type, ing = check_dish_conflict(
            menu_item=self.prawns_dish,
            allergies=["shellfish"],
            dislikes=[],
        )
        self.assertEqual(conflict_type, "allergy")
        self.assertEqual(ing, "shellfish")

    def test_safe_dish_no_conflict(self):
        conflict_type, ing = check_dish_conflict(
            menu_item=self.jeera_rice,
            allergies=["peanut", "shellfish"],
            dislikes=["mushroom"],
        )
        self.assertIsNone(conflict_type)
        self.assertIsNone(ing)

    def test_uncertain_ingredient_for_empty_allergens_on_critical_allergy(self):
        mystery_curry = MagicMock(
            name="Mystery Curry",
            description="",
            allergens="",
        )
        mystery_curry.name = "Mystery Curry"
        conflict_type, ing = check_dish_conflict(
            menu_item=mystery_curry,
            allergies=["gluten"],
            dislikes=[],
        )
        self.assertEqual(conflict_type, "uncertain_ingredient")


class TestCartScanAndRemoval(unittest.IsolatedAsyncioTestCase):
    async def test_retroactive_removal_of_conflicting_item(self):
        # Create mock order items
        prawn_menu_item = MagicMock()
        prawn_menu_item.name = "Garlic Butter Prawns"
        prawn_menu_item.description = "Succulent prawns sautéed in garlic butter"
        prawn_menu_item.allergens = "Shellfish, Dairy"

        rice_menu_item = MagicMock()
        rice_menu_item.name = "Steamed Basmati Rice"
        rice_menu_item.description = "Aromatic steamed rice"
        rice_menu_item.allergens = ""

        item1 = MagicMock(id=101, menu_item_id=1, menu_item=prawn_menu_item)
        item2 = MagicMock(id=102, menu_item_id=2, menu_item=rice_menu_item)

        mock_order = MagicMock(id=999, items=[item1, item2])
        mock_order_svc = AsyncMock()

        # Customer subsequently mentions allergy to prawns
        removed = await scan_and_remove_cart_conflicts(
            order=mock_order,
            allergies=["prawn"],
            dislikes=[],
            order_svc=mock_order_svc,
        )

        # Verify only the prawn dish was removed
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["item_name"], "Garlic Butter Prawns")
        self.assertEqual(removed[0]["type"], "allergy")
        mock_order_svc.remove_item.assert_called_once_with(999, 101)


class TestOrderServiceBackendAllergyEnforcement(unittest.IsolatedAsyncioTestCase):
    async def test_add_item_raises_http_exception_on_allergy(self):
        order_svc = OrderService()

        # Mock order
        mock_order = MagicMock(id=1, customer_id=42, status="active")
        order_svc.get_order = AsyncMock(return_value=mock_order)

        # Mock menu item containing peanuts
        mock_menu_item = MagicMock(
            id=5,
            name="Peanut Noodles",
            description="Noodles with peanut sauce",
            allergens="Peanuts, Gluten",
            is_available=True,
        )
        mock_menu_item.name = "Peanut Noodles"
        order_svc.menu_repo.get_by_id = AsyncMock(return_value=mock_menu_item)

        # Mock customer with peanut allergy
        mock_prefs = MagicMock(allergies=["peanut"], disliked_dishes=[])
        mock_customer = MagicMock(id=42, preferences=mock_prefs)
        order_svc.customer_repo.get_by_id = AsyncMock(return_value=mock_customer)

        # Attempting to add peanut noodles must raise HTTPException(400)
        with self.assertRaises(HTTPException) as ctx:
            await order_svc.add_item(1, OrderItemAdd(menu_item_id=5, quantity=1))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("allergy", ctx.exception.detail.lower())

    async def test_add_item_raises_with_string_stored_allergies(self):
        """Verifies RC-1 fix: DB stores allergies as string 'peanut, shellfish'."""
        order_svc = OrderService()
        mock_order = MagicMock(id=1, customer_id=42, status="active")
        order_svc.get_order = AsyncMock(return_value=mock_order)

        mock_menu_item = MagicMock(
            id=5,
            name="Peanut Noodles",
            description="Noodles with peanut sauce",
            allergens="Peanuts, Gluten",
            is_available=True,
        )
        mock_menu_item.name = "Peanut Noodles"
        order_svc.menu_repo.get_by_id = AsyncMock(return_value=mock_menu_item)

        # Stored as comma-separated string
        mock_prefs = MagicMock(allergies="peanut, shellfish", disliked_dishes=None)
        mock_customer = MagicMock(id=42, preferences=mock_prefs)
        order_svc.customer_repo.get_by_id = AsyncMock(return_value=mock_customer)

        with self.assertRaises(HTTPException) as ctx:
            await order_svc.add_item(1, OrderItemAdd(menu_item_id=5, quantity=1))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("allergy", ctx.exception.detail.lower())

    async def test_add_item_raises_with_legacy_repr_stored_allergies(self):
        """Verifies RC-1 & RC-2 legacy fix: DB stores allergies as \"['peanut']\"."""
        order_svc = OrderService()
        mock_order = MagicMock(id=1, customer_id=42, status="active")
        order_svc.get_order = AsyncMock(return_value=mock_order)

        mock_menu_item = MagicMock(
            id=5,
            name="Peanut Noodles",
            description="Noodles with peanut sauce",
            allergens="Peanuts, Gluten",
            is_available=True,
        )
        mock_menu_item.name = "Peanut Noodles"
        order_svc.menu_repo.get_by_id = AsyncMock(return_value=mock_menu_item)

        # Stored as Python list repr string
        mock_prefs = MagicMock(allergies="['peanut']", disliked_dishes=None)
        mock_customer = MagicMock(id=42, preferences=mock_prefs)
        order_svc.customer_repo.get_by_id = AsyncMock(return_value=mock_customer)

        with self.assertRaises(HTTPException) as ctx:
            await order_svc.add_item(1, OrderItemAdd(menu_item_id=5, quantity=1))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("allergy", ctx.exception.detail.lower())


class TestDietaryRestrictionSessionContinuity(unittest.TestCase):
    def test_allergy_block_does_not_terminate_session(self):
        """Verifies that an allergy rejection event keeps the ordering session active."""
        from app.services.openai.prompts import build_structured_context_dict
        from app.schemas.conversation import ConversationEvent

        event = ConversationEvent(
            type="item_blocked_allergy",
            status="blocked_allergy",
            is_retryable=True,
            details={"item_name": "Peanut Noodles", "conflict_type": "allergy", "ingredient": "peanut"}
        ).model_dump()

        active_order = {
            "id": 1,
            "status": "active",
            "total_amount": 0.0,
            "items": [],
        }

        ctx = build_structured_context_dict(
            user_intent="order_request",
            current_request="add peanut noodles",
            conversation_history=[],
            order=active_order,
            customer_name="Test User",
            customer_preferences={"allergies": "peanut"},
            recent_memories=[],
            events=[event],
        )

        # Crucial: is_terminal must be False so the session stays active
        self.assertFalse(ctx["state"]["required_information"]["is_terminal"])
        self.assertFalse(ctx["state"]["required_information"]["order_confirmed"])
        self.assertEqual(ctx["state"]["order_status"], "active")
        self.assertTrue(ctx["events"][0]["is_retryable"])


if __name__ == "__main__":
    unittest.main()

