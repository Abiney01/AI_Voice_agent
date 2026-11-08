from typing import List, Optional
from fastapi import HTTPException
from app.prisma_client.models import Order
from app.repositories.menu_repository import MenuRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.customer_repository import CustomerRepository
from app.schemas.order import OrderItemAdd
from app.services.restrictions.allergy_validator import check_dish_conflict


def _split_pref(val) -> List[str]:
    """Split a comma-separated preference string into a list of stripped tokens.

    Handles the three storage shapes that may appear in the DB:
    - None / empty string   → []
    - 'peanut, shellfish'   → ['peanut', 'shellfish']
    - "['peanut', 'nut']"   → ['peanut', 'nut']   (Python-repr artefact from old bug)
    """
    if not val:
        return []
    text = str(val).strip()
    # Strip Python list repr brackets produced by the old str(list) serialisation bug
    if text.startswith('[') and text.endswith(']'):
        text = text[1:-1]
    return [s.strip().strip("'\"") for s in text.split(',') if s.strip().strip("'\"")]


class OrderService:
    def __init__(self):
        self.order_repo = OrderRepository()
        self.menu_repo = MenuRepository()
        self.customer_repo = CustomerRepository()

    async def get_or_create_active_order(self, customer_id: int) -> Order:
        """Get existing active order or start a fresh one."""
        order = await self.order_repo.get_active_order(customer_id)
        if not order:
            order = await self.order_repo.create_order(customer_id)
        return order

    async def get_order(self, order_id: int) -> Order:
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    async def add_item(self, order_id: int, data: OrderItemAdd) -> Order:
        order = await self.get_order(order_id)
        if order.status != "active":
            raise HTTPException(status_code=400, detail="Cannot modify a confirmed or cancelled order")

        menu_item = await self.menu_repo.get_by_id(data.menu_item_id)
        if not menu_item:
            raise HTTPException(status_code=404, detail="Menu item not found")
        if not menu_item.is_available:
            raise HTTPException(status_code=400, detail=f"{menu_item.name} is currently unavailable")

        # Backend allergy & disliked food validation
        if getattr(order, "customer_id", None):
            customer = await self.customer_repo.get_by_id(order.customer_id)
            if customer and getattr(customer, "preferences", None):
                allergies = _split_pref(customer.preferences.allergies)
                dislikes = _split_pref(customer.preferences.disliked_dishes)
                conflict_type, conflict_ing = check_dish_conflict(menu_item, allergies, dislikes)
                if conflict_type == "allergy":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot add {menu_item.name}: dish contains {conflict_ing}, which violates known customer allergy."
                    )
                elif conflict_type == "dislike":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot add {menu_item.name}: dish contains {conflict_ing}, which customer has stated they dislike."
                    )

        await self.order_repo.add_item(order, menu_item, data.quantity, data.customization_notes)
        return await self.order_repo.get_by_id(order_id)

    async def remove_item(self, order_id: int, order_item_id: int) -> Order:
        order = await self.get_order(order_id)
        if order.status != "active":
            raise HTTPException(status_code=400, detail="Cannot modify a confirmed order")

        removed = await self.order_repo.remove_item(order, order_item_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Order item not found")
        return await self.order_repo.get_by_id(order_id)

    async def confirm_order(self, order_id: int) -> Order:
        order = await self.get_order(order_id)
        if order.status != "active":
            raise HTTPException(status_code=400, detail="Order is not active")
        if not order.items:
            raise HTTPException(status_code=400, detail="Cannot confirm an empty order")
        return await self.order_repo.update_status(order, "confirmed")

    async def cancel_order(self, order_id: int) -> Order:
        order = await self.get_order(order_id)
        return await self.order_repo.update_status(order, "cancelled")

    async def update_item_quantity(self, order_id: int, order_item_id: int, quantity: int) -> Order:
        order = await self.get_order(order_id)
        if order.status != "active":
            raise HTTPException(status_code=400, detail="Cannot modify a confirmed or cancelled order")
        await self.order_repo.update_item_quantity(order_id, order_item_id, quantity)
        return await self.order_repo.get_by_id(order_id)

    async def update_item(
        self,
        order_id: int,
        order_item_id: int,
        quantity: Optional[int] = None,
        customization_notes: Optional[str] = None,
    ) -> Order:
        order = await self.get_order(order_id)
        if order.status != "active":
            raise HTTPException(status_code=400, detail="Cannot modify a confirmed or cancelled order")
        await self.order_repo.update_item(
            order_id=order_id,
            order_item_id=order_item_id,
            quantity=quantity,
            customization_notes=customization_notes,
        )
        return await self.order_repo.get_by_id(order_id)

    async def get_customer_history(self, customer_id: int, limit: int = 5):
        return await self.order_repo.get_customer_orders(customer_id, limit)
