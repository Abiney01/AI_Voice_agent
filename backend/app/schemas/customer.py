from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─── Customer Preferences ─────────────────────────────────────────────────────

class CustomerPreferencesBase(BaseModel):
    spice_level: Optional[str] = Field(None, examples=["mild", "medium", "hot", "extra-hot"])
    allergies: Optional[str] = Field(None, examples=["nuts, shellfish"])
    dietary_preferences: Optional[str] = Field(None, examples=["vegetarian, halal"])
    favorite_dishes: Optional[str] = Field(None, examples=["Chicken Biryani, Butter Chicken"])
    disliked_dishes: Optional[str] = None


class CustomerPreferencesUpdate(CustomerPreferencesBase):
    pass


class CustomerPreferencesOut(CustomerPreferencesBase):
    id: int
    customer_id: int
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Customer ─────────────────────────────────────────────────────────────────

class CustomerIdentify(BaseModel):
    """Used to register or look up a customer by phone number."""
    phone_number: str = Field(..., min_length=7, max_length=20, examples=["+919876543210"])
    name: Optional[str] = Field(None, max_length=100, examples=["Arun Kumar"])


class CustomerOut(BaseModel):
    id: int
    phone_number: str
    name: Optional[str]
    created_at: datetime
    updated_at: datetime
    preferences: Optional[CustomerPreferencesOut] = None
    is_returning: bool = False  # True if customer already existed

    model_config = {"from_attributes": True}


class CustomerProfile(CustomerOut):
    """Extended profile with order history summary."""
    total_orders: int = 0
    last_order_date: Optional[datetime] = None
