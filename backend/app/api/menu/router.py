from typing import List
from fastapi import APIRouter, Query, HTTPException
from app.schemas.menu import MenuItemOut, MenuSearchResult
from app.services.menu_service import MenuService

router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("", response_model=List[MenuItemOut], summary="Get full menu")
async def get_menu():
    service = MenuService()
    return await service.get_all()


@router.get("/search", response_model=MenuSearchResult, summary="Search menu items")
async def search_menu(
    q: str = Query(..., min_length=1, description="Search query"),
):
    service = MenuService()
    items = await service.search(q)
    return MenuSearchResult(items=items, total=len(items))


@router.get("/{item_id}", response_model=MenuItemOut, summary="Get a specific menu item")
async def get_menu_item(item_id: int):
    service = MenuService()
    item = await service.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return item
