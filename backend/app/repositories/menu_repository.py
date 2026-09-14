from typing import List, Optional
from app.core.prisma import prisma
from app.prisma_client.models import MenuItem
from app.schemas.menu import MenuItemCreate


class MenuRepository:
    async def get_all(self, available_only: bool = True) -> List[MenuItem]:
        where = {"is_available": True} if available_only else {}
        return await prisma.menuitem.find_many(
            where=where,
            order=[
                {"cuisine": "asc"},
                {"category": "asc"},
                {"name": "asc"}
            ]
        )

    async def get_by_id(self, item_id: int) -> Optional[MenuItem]:
        return await prisma.menuitem.find_unique(where={"id": item_id})

    async def search(self, query: str) -> List[MenuItem]:
        return await prisma.menuitem.find_many(
            where={
                "is_available": True,
                "OR": [
                    {"name": {"contains": query, "mode": "insensitive"}},
                    {"category": {"contains": query, "mode": "insensitive"}},
                    {"cuisine": {"contains": query, "mode": "insensitive"}},
                    {"description": {"contains": query, "mode": "insensitive"}},
                ]
            },
            order={"name": "asc"}
        )

    async def find_by_name(self, name: str) -> Optional[MenuItem]:
        """Fuzzy name lookup for order extraction."""
        import re
        # Clean the input name of any annotations like (V) or [spice_level]
        cleaned_name = name.strip()
        # Remove (V) or (v)
        cleaned_name = re.sub(r'\s*\([vV]\)\s*', ' ', cleaned_name)
        # Remove anything in square brackets [spice_level]
        cleaned_name = re.sub(r'\s*\[[^\]]+\]\s*', ' ', cleaned_name)
        cleaned_name = cleaned_name.strip()

        # Try equals match first (case-insensitive)
        item = await prisma.menuitem.find_first(
            where={
                "name": {"equals": cleaned_name, "mode": "insensitive"},
                "is_available": True
            }
        )
        if item:
            return item

        # If not found, try contains match
        item = await prisma.menuitem.find_first(
            where={
                "name": {"contains": cleaned_name, "mode": "insensitive"},
                "is_available": True
            }
        )
        if item:
            return item

        # If not found, try a reverse contains: the DB item name is contained
        # within the customer's query (e.g. "biryani" in "spicy biryani please")
        # This avoids fetching all items into Python for a loop.
        all_items = await prisma.menuitem.find_many(where={"is_available": True})
        query_lower = cleaned_name.lower()
        for item in all_items:
            if item.name.lower() in query_lower:
                return item

        return None


    async def create(self, data: MenuItemCreate) -> MenuItem:
        return await prisma.menuitem.create(data=data.model_dump())

    async def count(self) -> int:
        return await prisma.menuitem.count()
