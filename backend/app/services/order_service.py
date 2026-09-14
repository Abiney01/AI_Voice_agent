from typing import Optional
from fastapi import HTTPException
from app.prisma_client.models import Order
from app.repositories.menu_repository import MenuRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderItemAdd


class OrderService:
    def __init__(self):
        self.order_repo = OrderRepository()
        self.menu_repo = MenuRepository()

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

    async def get_customer_history(self, customer_id: int, limit: int = 5):
        return await self.order_repo.get_customer_orders(customer_id, limit)
