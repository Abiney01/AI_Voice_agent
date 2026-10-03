from typing import List, Optional

from pydantic import BaseModel, Field


class MenuItemBase(BaseModel):
    name: str = Field(..., max_length=150)
    category: str = Field(..., max_length=80)
    cuisine: str = Field("indian", examples=["indian", "american"])
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    is_vegetarian: bool = False
    is_vegan: bool = False
    spice_level: Optional[str] = Field(None, examples=["mild", "medium", "hot"])
    allergens: Optional[str] = None
    is_available: bool = True
    meal_times: Optional[str] = Field(None, examples=["breakfast,brunch", "all", "lunch,dinner"])


class MenuItemCreate(MenuItemBase):
    pass


class MenuItemOut(MenuItemBase):
    id: int

    model_config = {"from_attributes": True}


class MenuSearchResult(BaseModel):
    items: List[MenuItemOut]
    total: int


class MenuCategory(BaseModel):
    category: str
    cuisine: str
    items: List[MenuItemOut]
