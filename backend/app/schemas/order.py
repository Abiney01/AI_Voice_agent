from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Order Items ──────────────────────────────────────────────────────────────

class OrderItemAdd(BaseModel):
    menu_item_id: int
    quantity: int = Field(1, ge=1, le=20)
    customization_notes: Optional[str] = Field(None, max_length=300)


class OrderItemUpdate(BaseModel):
    quantity: int = Field(..., ge=0, le=50)



class OrderItemOut(BaseModel):
    id: int
    menu_item_id: int
    menu_item_name: str = ""
    quantity: int
    unit_price: float
    customization_notes: Optional[str]
    subtotal: float = 0.0

    model_config = {"from_attributes": True}


# ─── Order ────────────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_id: int


class OrderOut(BaseModel):
    id: int
    customer_id: int
    status: str
    total_amount: float
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemOut] = []

    model_config = {"from_attributes": True}


class OrderConfirm(BaseModel):
    """Optionally attach a note when confirming."""
    note: Optional[str] = None
