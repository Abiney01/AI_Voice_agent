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
    action: str  # "add" | "remove" | "modify" | "confirm" | "cancel" | "none" | "replace"
    menu_item_name: Optional[str] = None
    menu_item_id: Optional[int] = None
    quantity: int = 1
    customization_notes: Optional[str] = None
    status: Optional[str] = None
    is_retryable: bool = True


class ConversationEvent(BaseModel):
    """Structured event capturing an action, status, and retryability/terminal condition."""
    type: str  # "order_confirmed", "order_cancelled", "item_added", "item_removed", "conversation_turn", etc.
    status: str  # "confirmed", "cancelled", "success", "failed", "in_progress", etc.
    is_retryable: bool = True
    details: Optional[Dict[str, Any]] = None


class OrderDiscrepancy(BaseModel):
    """Specific discrepancy between the LLM's expected order and the actual cart."""
    field: str  # "quantity", "item_missing", "unexpected_item", "order_status", "variant_mismatch"
    item: Optional[str] = None
    llm_value: Any = None
    cart_value: Any = None
    message: str = ""


class OrderSyncStatus(BaseModel):
    """Synchronization status comparing LLM order state against authoritative cart."""
    is_synced: bool = True
    discrepancies: List[OrderDiscrepancy] = []


class ChatResponse(BaseModel):
    message: str  # AI response text
    order_actions: List[OrderAction] = []
    events: List[ConversationEvent] = []
    sync_status: Optional[OrderSyncStatus] = None
    updated_order: Optional[Dict[str, Any]] = None
    recommendations: List[Dict[str, Any]] = []


class RecommendationOut(BaseModel):
    priority: int
    reason: str
    items: List[Dict[str, Any]]

