import logging
from typing import Any, Dict, List, Optional
from app.core.prisma import prisma
from app.prisma_client.models import Customer, MenuItem
from app.repositories.customer_repository import CustomerRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.menu_repository import MenuRepository
from app.services.memory.memory_service import MemoryService

logger = logging.getLogger(__name__)


class RecommendationService:
    def __init__(self):
        self.customer_repo = CustomerRepository()
        self.order_repo = OrderRepository()
        self.menu_repo = MenuRepository()
        self.memory_svc = MemoryService()

    async def get_recommendations(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Returns a prioritized list of recommendations following the 4-priority strategy.
        """
        recommendations = []
        seen_ids = set()

        customer = await self.customer_repo.get_by_id(customer_id)
        if not customer:
            return []

        # Priority 1: Personal Preferences / Favorites
        p1 = await self._priority_1_personal(customer, seen_ids)
        if p1:
            recommendations.append({
                "priority": 1,
                "reason": "Based on your favorites",
                "items": p1,
            })
            for item in p1:
                seen_ids.add(item["id"])

        # Priority 2: Frequently Ordered Items
        p2 = await self._priority_2_frequent(customer_id, seen_ids)
        if p2:
            recommendations.append({
                "priority": 2,
                "reason": "You frequently order these",
                "items": p2,
            })
            for item in p2:
                seen_ids.add(item["id"])

        # Priority 3: Frequently Bought Together
        p3 = await self._priority_3_bought_together(customer_id, seen_ids)
        if p3:
            recommendations.append({
                "priority": 3,
                "reason": "Often ordered together with your favorites",
                "items": p3,
            })
            for item in p3:
                seen_ids.add(item["id"])

        # Priority 4: Similar Customer Recommendations
        p4 = await self._priority_4_similar_customers(customer_id, customer, seen_ids)
        if p4:
            recommendations.append({
                "priority": 4,
                "reason": "Popular with customers who share your taste",
                "items": p4,
            })

        return recommendations

    async def _priority_1_personal(
        self, customer: Customer, seen_ids: set
    ) -> List[Dict[str, Any]]:
        """Recommend from customer's favorite_dishes preference field."""
        prefs = customer.preferences
        if not prefs or not prefs.favorite_dishes:
            return []

        results = []
        for dish_name in prefs.favorite_dishes.split(","):
            dish_name = dish_name.strip()
            if not dish_name:
                continue
            item = await self.menu_repo.find_by_name(dish_name)
            if item and item.id not in seen_ids and item.is_available:
                results.append(self._item_to_dict(item))
                if len(results) >= 3:
                    break
        return results

    async def _priority_2_frequent(
        self, customer_id: int, seen_ids: set
    ) -> List[Dict[str, Any]]:
        """Top ordered items by this customer."""
        rows = await prisma.query_raw(
            '''
            SELECT oi.menu_item_id, SUM(oi.quantity) as total_qty
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.customer_id = $1 AND o.status = 'confirmed'
            GROUP BY oi.menu_item_id
            ORDER BY total_qty DESC
            LIMIT 5
            ''',
            customer_id
        )

        items = []
        for row in rows:
            menu_item_id = row.get("menu_item_id")
            if menu_item_id is None or menu_item_id in seen_ids:
                continue
            item = await self.menu_repo.get_by_id(menu_item_id)
            if item and item.is_available:
                items.append(self._item_to_dict(item))
        return items[:3]

    async def _priority_3_bought_together(
        self, customer_id: int, seen_ids: set
    ) -> List[Dict[str, Any]]:
        """Items frequently bought in the same orders as frequently ordered items."""
        # Get this customer's frequently ordered item IDs
        freq_result = await prisma.query_raw(
            '''
            SELECT oi.menu_item_id, SUM(oi.quantity) as total_qty
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.customer_id = $1 AND o.status = 'confirmed'
            GROUP BY oi.menu_item_id
            ORDER BY total_qty DESC
            LIMIT 3
            ''',
            customer_id
        )
        frequent_ids = [row.get("menu_item_id") for row in freq_result if row.get("menu_item_id") is not None]
        if not frequent_ids:
            return []

        # Find orders that contain those items
        co_orders = await prisma.query_raw(
            '''
            SELECT DISTINCT oi.order_id
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.menu_item_id = ANY($1) AND o.status = 'confirmed'
            ''',
            frequent_ids
        )
        order_ids = [row.get("order_id") for row in co_orders if row.get("order_id") is not None]
        if not order_ids:
            return []

        # Find items bought in those orders (excluding already-seen and frequent items)
        co_items = await prisma.query_raw(
            '''
            SELECT oi.menu_item_id, COUNT(*) as co_count
            FROM order_items oi
            WHERE oi.order_id = ANY($1) AND NOT (oi.menu_item_id = ANY($2))
            GROUP BY oi.menu_item_id
            ORDER BY co_count DESC
            LIMIT 5
            ''',
            order_ids,
            frequent_ids
        )

        items = []
        for row in co_items:
            menu_item_id = row.get("menu_item_id")
            if menu_item_id is None or menu_item_id in seen_ids:
                continue
            item = await self.menu_repo.get_by_id(menu_item_id)
            if item and item.is_available:
                items.append(self._item_to_dict(item))
        return items[:3]

    async def _priority_4_similar_customers(
        self, customer_id: int, customer: Customer, seen_ids: set
    ) -> List[Dict[str, Any]]:
        """Items ordered by customers with similar preferences."""
        prefs = customer.preferences
        if not prefs:
            return []

        pref_text = " ".join(filter(None, [
            prefs.spice_level,
            prefs.dietary_preferences,
            prefs.favorite_dishes,
        ]))
        if not pref_text.strip():
            return []

        similar_customer_ids = await self.memory_svc.get_similar_customer_ids(
            customer_id, pref_text
        )
        if not similar_customer_ids:
            return []

        # Find what those similar customers order most
        if seen_ids:
            result = await prisma.query_raw(
                '''
                SELECT oi.menu_item_id, SUM(oi.quantity) as total
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = ANY($1)
                  AND o.status = 'confirmed'
                  AND NOT (oi.menu_item_id = ANY($2))
                GROUP BY oi.menu_item_id
                ORDER BY total DESC
                LIMIT 5
                ''',
                similar_customer_ids,
                list(seen_ids)
            )
        else:
            result = await prisma.query_raw(
                '''
                SELECT oi.menu_item_id, SUM(oi.quantity) as total
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = ANY($1)
                  AND o.status = 'confirmed'
                GROUP BY oi.menu_item_id
                ORDER BY total DESC
                LIMIT 5
                ''',
                similar_customer_ids
            )

        items = []
        for row in result:
            menu_item_id = row.get("menu_item_id")
            if menu_item_id is None:
                continue
            item = await self.menu_repo.get_by_id(menu_item_id)
            if item and item.is_available:
                items.append(self._item_to_dict(item))
        return items[:3]

    def _item_to_dict(self, item: MenuItem) -> Dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "cuisine": item.cuisine,
            "price": float(item.price),
            "description": item.description,
            "is_vegetarian": item.is_vegetarian,
            "spice_level": item.spice_level,
        }
