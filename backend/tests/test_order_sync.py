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

from app.core.config import get_settings
from app.core.prisma import prisma
from app.repositories.menu_repository import MenuRepository
from app.services.order_service import OrderService
from app.schemas.order import OrderItemAdd
from app.schemas.conversation import ChatRequest, ChatResponse, OrderDiscrepancy, OrderSyncStatus
from app.services.order_sync import clean_dish_name, compute_llm_expected_order, validate_order_sync
from app.services.openai.prompts import build_structured_context_dict
from app.api.conversations.router import chat
from fastapi import Request, BackgroundTasks


class DummyRequest:
    async def is_disconnected(self):
        return False


class TestOrderSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await prisma.connect()
        self.order_svc = OrderService()
        self.menu_repo = MenuRepository()

    async def asyncTearDown(self):
        await prisma.disconnect()

    def test_scenario_d_configurable_pause_threshold(self):
        """Scenario D & E: Verify 2-second silence threshold is configurable via constants."""
        self.assertEqual(get_settings().llm_pause_threshold_ms, 2000)

        # Also verify frontend constant file exists and defines LLM_PAUSE_THRESHOLD_MS = 2000
        frontend_const_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "frontend", "src", "config", "constants.ts"
        )
        self.assertTrue(os.path.exists(frontend_const_path))
        with open(frontend_const_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("LLM_PAUSE_THRESHOLD_MS = 2000", content)
        self.assertIn("VOICE_ACTIVITY_THRESHOLD", content)

    def test_scenario_a_sync_unit_normal(self):
        """Scenario A Unit: llm_order matches actual_cart exactly."""
        base_cart = {"id": 1, "status": "active", "items": []}
        raw_actions = [{"action": "add", "menu_item_name": "Veg Biryani", "quantity": 2}]
        llm_order = compute_llm_expected_order(base_cart, raw_actions)
        
        actual_cart = {
            "id": 1,
            "status": "active",
            "items": [{"menu_item_name": "Veg Biryani", "quantity": 2, "unit_price": 250}],
        }
        sync_status = validate_order_sync(llm_order, actual_cart)
        self.assertTrue(sync_status.is_synced)
        self.assertEqual(len(sync_status.discrepancies), 0)

    def test_scenario_b_sync_unit_quantity_mismatch(self):
        """Scenario B Unit: Cart update only adds 1 burger instead of 2."""
        llm_order = {
            "id": 1,
            "status": "active",
            "items": [{"menu_item_name": "Veg Burger", "quantity": 2}],
        }
        actual_cart = {
            "id": 1,
            "status": "active",
            "items": [{"menu_item_name": "Veg Burger", "quantity": 1}],
        }
        sync_status = validate_order_sync(llm_order, actual_cart)
        self.assertFalse(sync_status.is_synced)
        self.assertEqual(len(sync_status.discrepancies), 1)
        d = sync_status.discrepancies[0]
        self.assertEqual(d.field, "quantity")
        self.assertEqual(d.item, "Veg Burger")
        self.assertEqual(d.llm_value, 2)
        self.assertEqual(d.cart_value, 1)

    def test_scenario_c_sync_unit_missing_item(self):
        """Scenario C Unit: LLM expected an item that does not exist in the actual cart."""
        llm_order = {
            "id": 1,
            "status": "active",
            "items": [{"menu_item_name": "Margherita Pizza", "quantity": 1}],
        }
        actual_cart = {
            "id": 1,
            "status": "active",
            "items": [],
        }
        sync_status = validate_order_sync(llm_order, actual_cart)
        self.assertFalse(sync_status.is_synced)
        self.assertEqual(len(sync_status.discrepancies), 1)
        d = sync_status.discrepancies[0]
        self.assertEqual(d.field, "item_missing")
        self.assertEqual(d.item, "Margherita Pizza")
        self.assertEqual(d.llm_value, 1)
        self.assertEqual(d.cart_value, 0)

    def test_structured_context_contains_sync_data(self):
        """Verify build_structured_context_dict incorporates llm_order, actual_cart, and sync_status."""
        llm_order = {"id": 10, "status": "active", "items": [{"menu_item_name": "Pizza", "quantity": 1}]}
        actual_cart = {"id": 10, "status": "active", "items": []}
        sync_status = validate_order_sync(llm_order, actual_cart)

        ctx = build_structured_context_dict(
            user_intent="order_add",
            current_request="I want a pizza",
            conversation_history=[],
            order=actual_cart,
            customer_name="Test User",
            customer_preferences={},
            recent_memories=[],
            events=[],
            llm_order=llm_order,
            actual_cart=actual_cart,
            sync_status=sync_status.model_dump(),
        )

        self.assertIn("llm_order", ctx)
        self.assertIn("actual_cart", ctx)
        self.assertIn("sync_status", ctx)
        self.assertIn("instruction", ctx)
        self.assertFalse(ctx["sync_status"]["is_synced"])
        self.assertIn("Reconcile", ctx["instruction"])

    async def test_scenario_a_integration_normal_order(self):
        """Scenario A Integration: User says 'Add 2 Veg Biryani' -> Cart has 2, synced=True."""
        customer_id = 1
        existing = await prisma.order.find_first(where={"customer_id": customer_id, "status": "active"})
        if existing:
            await prisma.order.update(where={"id": existing.id}, data={"status": "cancelled"})

        order = await self.order_svc.get_or_create_active_order(customer_id)

        chat_req = ChatRequest(
            customer_id=customer_id,
            message="Please add 2 Veg Biryani",
            conversation_history=[],
            active_order_id=order.id,
        )

        response: ChatResponse = await chat(chat_req, DummyRequest(), BackgroundTasks())
        
        self.assertIsNotNone(response.sync_status)
        self.assertTrue(response.sync_status.is_synced)
        self.assertEqual(len(response.sync_status.discrepancies), 0)
        self.assertIsNotNone(response.updated_order)
        biryani_items = [it for it in response.updated_order["items"] if "biryani" in it["menu_item_name"].lower()]
        self.assertTrue(len(biryani_items) > 0)
        self.assertEqual(biryani_items[0]["quantity"], 2)

    async def test_scenario_c_integration_item_missing_prevent_false_success(self):
        """Scenario C Integration: User asks for an item not on the menu (e.g. Salmon Sushi).
        Cart does NOT contain it. sync_status.is_synced is False, and AI does not claim false success.
        """
        customer_id = 1
        existing = await prisma.order.find_first(where={"customer_id": customer_id, "status": "active"})
        if existing:
            await prisma.order.update(where={"id": existing.id}, data={"status": "cancelled"})

        order = await self.order_svc.get_or_create_active_order(customer_id)

        chat_req = ChatRequest(
            customer_id=customer_id,
            message="Can you please add 1 Salmon Sushi to my order?",
            conversation_history=[],
            active_order_id=order.id,
        )

        response: ChatResponse = await chat(chat_req, DummyRequest(), BackgroundTasks())
        
        # Verify cart does NOT have sushi
        self.assertIsNotNone(response.updated_order)
        sushi_items = [it for it in response.updated_order["items"] if "sushi" in it["menu_item_name"].lower()]
        self.assertEqual(len(sushi_items), 0, "Sushi must NOT be added to authoritative cart")

        # Verify discrepancy was detected
        self.assertIsNotNone(response.sync_status)
        self.assertFalse(response.sync_status.is_synced)
        missing_discrepancies = [d for d in response.sync_status.discrepancies if d.field == "item_missing"]
        self.assertTrue(len(missing_discrepancies) > 0)

        # Verify event was recorded
        discrepancy_events = [e for e in response.events if e.type == "order_sync_discrepancy"]
        self.assertTrue(len(discrepancy_events) > 0)

        # Verify AI message does NOT falsely claim success
        self.assertNotIn("added the salmon sushi", response.message.lower())
        self.assertNotIn("added salmon sushi", response.message.lower())

    async def test_scenario_f_terminal_event_precedence(self):
        """Scenario F: Confirming order generates is_retryable=false, terminating the conversation."""
        customer_id = 1
        existing = await prisma.order.find_first(where={"customer_id": customer_id, "status": "active"})
        if existing:
            await prisma.order.update(where={"id": existing.id}, data={"status": "cancelled"})

        order = await self.order_svc.get_or_create_active_order(customer_id)
        veg_biryani = await self.menu_repo.find_by_name("Veg Biryani")
        await self.order_svc.add_item(order.id, OrderItemAdd(menu_item_id=veg_biryani.id, quantity=1))

        chat_req = ChatRequest(
            customer_id=customer_id,
            message="Confirm my order now please",
            conversation_history=[],
            active_order_id=order.id,
        )

        response: ChatResponse = await chat(chat_req, DummyRequest(), BackgroundTasks())
        terminal_events = [e for e in response.events if e.is_retryable is False]
        self.assertTrue(len(terminal_events) > 0, "Must contain terminal event with is_retryable=False")
        self.assertEqual(response.updated_order["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
