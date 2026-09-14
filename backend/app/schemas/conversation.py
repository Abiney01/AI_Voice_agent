from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    customer_id: int
    message: str
    conversation_history: List[ChatMessage] = []
    active_order_id: Optional[int] = None


class OrderAction(BaseModel):
    """Extracted order action from AI conversation."""
    action: str  # "add" | "remove" | "modify" | "confirm" | "cancel" | "none"
    menu_item_name: Optional[str] = None
    menu_item_id: Optional[int] = None
    quantity: int = 1
    customization_notes: Optional[str] = None


class ChatResponse(BaseModel):
    message: str  # AI response text
    order_actions: List[OrderAction] = []
    updated_order: Optional[Dict[str, Any]] = None
    recommendations: List[Dict[str, Any]] = []


class RecommendationOut(BaseModel):
    priority: int
    reason: str
    items: List[Dict[str, Any]]
