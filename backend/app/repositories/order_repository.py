from typing import List, Optional
from app.core.prisma import prisma
from app.prisma_client.models import Order, OrderItem, MenuItem


class OrderRepository:
    async def create_order(self, customer_id: int) -> Order:
        return await prisma.order.create(
            data={
                "customer_id": customer_id,
                "status": "active",
                "total_amount": 0.0
            },
            include={"items": {"include": {"menu_item": True}}}
        )

    async def get_by_id(self, order_id: int) -> Optional[Order]:
        return await prisma.order.find_unique(
            where={"id": order_id},
            include={"items": {"include": {"menu_item": True}}}
        )

    async def get_active_order(self, customer_id: int) -> Optional[Order]:
        """Get the current active (unconfirmed) order for a customer."""
        orders = await prisma.order.find_many(
            where={
                "customer_id": customer_id,
                "status": "active"
            },
            include={"items": {"include": {"menu_item": True}}},
            order={"created_at": "desc"},
            take=1
        )
        return orders[0] if orders else None

    async def get_customer_orders(self, customer_id: int, limit: int = 5) -> List[Order]:
        return await prisma.order.find_many(
            where={
                "customer_id": customer_id,
                "status": "confirmed"
            },
            include={"items": {"include": {"menu_item": True}}},
            order={"created_at": "desc"},
            take=limit
        )

    async def add_item(
        self,
        order: Order,
        menu_item: MenuItem,
        quantity: int,
        customization_notes: Optional[str] = None,
    ) -> OrderItem:
        # Check if item already exists in this order
        items = await prisma.orderitem.find_many(where={"order_id": order.id})
        existing = next(
            (i for i in items if i.menu_item_id == menu_item.id), None
        )
        if existing:
            item = await prisma.orderitem.update(
                where={"id": existing.id},
                data={"quantity": existing.quantity + quantity}
            )
        else:
            item = await prisma.orderitem.create(
                data={
                    "order_id": order.id,
                    "menu_item_id": menu_item.id,
                    "quantity": quantity,
                    "unit_price": menu_item.price,
                    "customization_notes": customization_notes,
                }
            )

        await self._recalculate_total(order.id)
        return item

    async def remove_item(self, order: Order, order_item_id: int) -> bool:
        # Check if item belongs to order
        item = await prisma.orderitem.find_first(
            where={
                "id": order_item_id,
                "order_id": order.id
            }
        )
        if not item:
            return False
        await prisma.orderitem.delete(where={"id": order_item_id})
        await self._recalculate_total(order.id)
        return True

    async def update_item_quantity(self, order_id: int, order_item_id: int, quantity: int) -> None:
        if quantity <= 0:
            await prisma.orderitem.delete(where={"id": order_item_id})
        else:
            await prisma.orderitem.update(
                where={"id": order_item_id},
                data={"quantity": quantity}
            )
        await self._recalculate_total(order_id)

    async def update_status(self, order: Order, status: str) -> Order:
        return await prisma.order.update(
            where={"id": order.id},
            data={"status": status},
            include={"items": {"include": {"menu_item": True}}}
        )

    async def _recalculate_total(self, order_id: int) -> None:
        items = await prisma.orderitem.find_many(where={"order_id": order_id})
        total = sum(float(i.unit_price) * i.quantity for i in items)
        await prisma.order.update(
            where={"id": order_id},
            data={"total_amount": total}
        )
