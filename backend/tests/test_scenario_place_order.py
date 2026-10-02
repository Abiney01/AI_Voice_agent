import asyncio
import sys
import unittest
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from app.core.prisma import prisma
from app.repositories.customer_repository import CustomerRepository
from app.repositories.menu_repository import MenuRepository
from app.services.order_service import OrderService
from app.schemas.order import OrderItemAdd
from app.schemas.conversation import ChatRequest, ChatResponse
from app.api.conversations.router import chat
from fastapi import Request, BackgroundTasks


class DummyRequest:
    async def is_disconnected(self):
        return False


class TestScenarioPlaceOrder(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await prisma.connect()
        self.order_svc = OrderService()
        self.menu_repo = MenuRepository()

    async def asyncTearDown(self):
        await prisma.disconnect()

    async def test_place_my_order_scenario(self):
        # 1. Use customer 1 (Rahul)
        customer_id = 1

        # Clean up any existing active order or create a fresh one
        existing = await prisma.order.find_first(where={"customer_id": customer_id, "status": "active"})
        if existing:
            await prisma.order.update(where={"id": existing.id}, data={"status": "cancelled"})

        # Create fresh active order for Rahul
        order = await self.order_svc.get_or_create_active_order(customer_id)

        # Add Veg Biryani and Sweet Lassi
        veg_biryani = await self.menu_repo.find_by_name("Veg Biryani")
        sweet_lassi = await self.menu_repo.find_by_name("Sweet Lassi")

        self.assertIsNotNone(veg_biryani, "Veg Biryani should exist in menu")
        self.assertIsNotNone(sweet_lassi, "Sweet Lassi should exist in menu")

        await self.order_svc.add_item(order.id, OrderItemAdd(menu_item_id=veg_biryani.id, quantity=1))
        await self.order_svc.add_item(order.id, OrderItemAdd(menu_item_id=sweet_lassi.id, quantity=1))

        # Check cart
        order = await self.order_svc.get_order(order.id)
        self.assertEqual(len(order.items), 2)
        self.assertEqual(order.status, "active")

        # 2. Simulate user sending "place my order"
        history = [
            {"role": "assistant", "content": "I've added the Veg Biryani and Sweet Lassi, Rahul. Would you like anything else with your meal?"},
        ]
        chat_req = ChatRequest(
            customer_id=customer_id,
            message="place my order",
            conversation_history=history,
            active_order_id=order.id,
        )

        bg_tasks = BackgroundTasks()
        dummy_req = DummyRequest()

        # 3. Call chat endpoint
        response: ChatResponse = await chat(chat_req, dummy_req, bg_tasks)

        print("\n--- TEST: 'place my order' Response ---")
        print("Message:", response.message)
        print("Order Actions:", [a.model_dump() for a in response.order_actions])
        print("Events:", [e.model_dump() for e in response.events])
        print("Updated Order Status:", response.updated_order.get("status") if response.updated_order else None)
        print("---------------------------------------")

        # 4. Verify terminal event and is_retryable flag
        self.assertTrue(len(response.events) > 0, "Response must include structured events")
        terminal_events = [e for e in response.events if e.is_retryable is False]
        self.assertTrue(len(terminal_events) > 0, "Must have an event with is_retryable=False")
        self.assertEqual(terminal_events[0].type, "order_confirmed")
        self.assertEqual(terminal_events[0].status, "confirmed")

        # 5. Verify order is confirmed in DB
        confirmed_order = await self.order_svc.get_order(order.id)
        self.assertEqual(confirmed_order.status, "confirmed")
        self.assertEqual(response.updated_order["status"], "confirmed")

        # 6. Verify LLM did NOT ask a follow-up question
        msg_lower = response.message.lower()
        forbidden_questions = [
            "anything else",
            "what else",
            "would you like to add",
            "something else",
            "can i get you anything",
            "add or change",
        ]
        for phrase in forbidden_questions:
            self.assertNotIn(
                phrase,
                msg_lower,
                f"Terminal response should not contain follow-up question '{phrase}'"
            )

        # 7. Verify response confirms the items
        self.assertTrue(
            "biryani" in msg_lower or "confirmed" in msg_lower or "order" in msg_lower,
            "Response should acknowledge the confirmed order"
        )

    async def test_add_item_is_retryable_true(self):
        """Verify adding an item produces is_retryable=True and allows conversation to continue."""
        customer_id = 1
        existing = await prisma.order.find_first(where={"customer_id": customer_id, "status": "active"})
        if existing:
            await prisma.order.update(where={"id": existing.id}, data={"status": "cancelled"})

        order = await self.order_svc.get_or_create_active_order(customer_id)

        chat_req = ChatRequest(
            customer_id=customer_id,
            message="Add 1 Veg Biryani to my order",
            conversation_history=[],
            active_order_id=order.id,
        )

        bg_tasks = BackgroundTasks()
        dummy_req = DummyRequest()
        response: ChatResponse = await chat(chat_req, dummy_req, bg_tasks)

        print("\n--- TEST: 'add item' Response ---")
        print("Message:", response.message)
        print("Events:", [e.model_dump() for e in response.events])
        print("---------------------------------")

        # Verify event has is_retryable = True
        self.assertTrue(len(response.events) > 0)
        self.assertTrue(all(e.is_retryable for e in response.events), "Non-terminal events must have is_retryable=True")
        self.assertEqual(response.events[0].type, "item_added")
        self.assertEqual(response.updated_order["status"], "active")

        # Now test that conversation can continue: follow up with place my order
        history = [
            {"role": "user", "content": "Add 1 Veg Biryani to my order"},
            {"role": "assistant", "content": response.message},
        ]
        chat_req_confirm = ChatRequest(
            customer_id=customer_id,
            message="place my order",
            conversation_history=history,
            active_order_id=order.id,
        )

        response_confirm: ChatResponse = await chat(chat_req_confirm, dummy_req, bg_tasks)
        print("\n--- TEST: Follow-up 'place my order' Response ---")
        print("Message:", response_confirm.message)
        print("Events:", [e.model_dump() for e in response_confirm.events])
        print("-------------------------------------------------")

        # Verify second turn is terminal with is_retryable=False
        terminal_events = [e for e in response_confirm.events if not e.is_retryable]
        self.assertTrue(len(terminal_events) > 0, "Confirm turn must produce is_retryable=False")
        self.assertEqual(response_confirm.updated_order["status"], "confirmed")
        self.assertNotIn("anything else", response_confirm.message.lower())


if __name__ == "__main__":
    unittest.main()

