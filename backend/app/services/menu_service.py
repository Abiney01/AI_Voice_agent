from typing import List, Optional
from app.prisma_client.models import MenuItem
from app.repositories.menu_repository import MenuRepository
from app.schemas.menu import MenuItemCreate


class MenuService:
    def __init__(self):
        self.repo = MenuRepository()

    async def get_all(self) -> List[MenuItem]:
        return await self.repo.get_all()

    async def get_by_id(self, item_id: int) -> Optional[MenuItem]:
        return await self.repo.get_by_id(item_id)

    async def search(self, query: str) -> List[MenuItem]:
        return await self.repo.search(query)

    async def find_by_name(self, name: str) -> Optional[MenuItem]:
        return await self.repo.find_by_name(name)

    async def create(self, data: MenuItemCreate) -> MenuItem:
        return await self.repo.create(data)

    async def is_seeded(self) -> bool:
        count = await self.repo.count()
        return count > 0
