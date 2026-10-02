import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from app.repositories.customer_repository import CustomerRepository
from app.repositories.menu_repository import MenuRepository
from app.schemas.conversation import (
    ChatRequest,
    ChatResponse,
    ConversationEvent,
    OrderAction,
    OrderDiscrepancy,
    OrderSyncStatus,
)
from app.schemas.order import OrderItemAdd
from app.services.openai.conversation_service import ConversationService
from app.services.openai.prompts import build_structured_context_dict
from app.services.guardrails.domain_guard import check_guardrails
from app.services.memory.memory_service import MemoryService
from app.services.order_service import OrderService
from app.services.order_sync import clean_dish_name, compute_llm_expected_order, validate_order_sync


class SessionEndRequest(BaseModel):
    customer_id: int
    conversation_history: List[Dict] = []

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ─── Menu Cache ───────────────────────────────────────────────────────────────
# The full menu is fetched on every chat turn without caching.
# Since menu items rarely change, we cache the compiled summary string.

_menu_cache: Dict = {"summary": None, "dish_names": "", "item_names": [], "expires": 0.0}
_menu_lock = asyncio.Lock()
_MENU_CACHE_TTL = 600  # 10 minutes


async def _get_cached_menu_data(menu_repo: MenuRepository):
    """Return cached menu summary, formatted dish names, and list of items, refreshing if expired."""
    async with _menu_lock:
        now = time.monotonic()
        if _menu_cache["summary"] and now < _menu_cache["expires"]:
            return _menu_cache["summary"], _menu_cache["dish_names"], _menu_cache["item_names"]
        items = await menu_repo.get_all(available_only=True)
        _menu_cache["summary"] = _build_menu_summary(items)
        _menu_cache["item_names"] = [it.name for it in items]
        _menu_cache["dish_names"] = ", ".join(_menu_cache["item_names"])
        _menu_cache["expires"] = now + _MENU_CACHE_TTL
        logger.debug("Menu cache refreshed")
        return _menu_cache["summary"], _menu_cache["dish_names"], _menu_cache["item_names"]


async def _get_cached_menu_summary(menu_repo: MenuRepository) -> str:
    """Return cached menu summary string."""
    summary, _, _ = await _get_cached_menu_data(menu_repo)
    return summary


def invalidate_menu_cache() -> None:
    """Call this if menu items are ever updated at runtime."""
    _menu_cache["expires"] = 0.0


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_menu_summary(items) -> str:
    """Build a compact menu string for the LLM context."""
    lines = []
    current_category = None
    for item in items:
        if item.category != current_category:
            current_category = item.category
            lines.append(f"\n[{item.cuisine.upper()} — {item.category}]")
        veg = " (V)" if item.is_vegetarian else ""
        spice = f" [{item.spice_level}]" if item.spice_level else ""
        lines.append(f"  - {item.name}{veg}{spice} — ₹{float(item.price):.0f}")
    return "\n".join(lines)


def _build_order_dict(order) -> Dict[str, Any]:
    """Return an OrderOut-compatible dict so the frontend Order type is satisfied."""
    items_list = []
    if order.items:
        for item in order.items:
            unit_price = float(item.unit_price)
            quantity = item.quantity
            items_list.append({
                "id": item.id,
                "menu_item_id": getattr(item, "menu_item_id", None),
                "menu_item_name": item.menu_item.name if item.menu_item else "",
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": round(unit_price * quantity, 2),
                "customization_notes": (
                    item.customization_notes.replace("\n", " ").replace("\r", " ")
                    if item.customization_notes else None
                ),
            })
    # created_at / updated_at may be datetime objects — serialize to ISO string
    def _dt(val):
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    return {
        "id": order.id,
        "customer_id": getattr(order, "customer_id", None),
        "status": order.status,
        "total_amount": float(order.total_amount),
        "created_at": _dt(getattr(order, "created_at", None)),
        "updated_at": _dt(getattr(order, "updated_at", None)),
        "items": items_list,
    }


def _build_order_summary(order) -> str:
    """Build a compact current-order string for the extraction LLM."""
    if not order or not order.items:
        return "Empty (nothing ordered yet)"
    lines = []
    for item in order.items:
        name = item.menu_item.name if item.menu_item else f"item#{item.menu_item_id}"
        lines.append(f"  - {item.quantity}x {name} @ ₹{float(item.unit_price):.0f}")
    return "\n".join(lines)


# ─── Order Intent Detection ───────────────────────────────────────────────────

_AFFIRMATIVE_RE = re.compile(
    r"\b(yes|yeah|yep|sure|ok|okay|please|go\s+ahead|do\s+that|add\s+that|sounds\s+good|both|all\s+of\s+them|that\s+one|why\s+not)\b",
    re.IGNORECASE,
)

_ORDER_INTENT_RE = re.compile(
    r"\b(add|order|place|finish|finalize|done|pay|complete|checkout|bill|"
    r"remove|delete|cancel|confirm|"
    r"give\s+me|get\s+me|bring\s+me|make\s+it|make\s+that|"
    r"change|modify|update|replace|swap|take\s+away|drop|"
    r"more|less|another|extra|quantity|minus|plus|"
    r"skip|scratch|don'?t\s+want|leave\s+(off|out)|without|"
    r"i('d|\s+would|\s+will)?\s+like|i('ll|\s+will)\s+(take|have|get)|"
    r"can\s+i\s+(have|get)|put\s+in|throw\s+in|include|exclude|"
    r"biryani|rice|coke|milkshake|burger|fries|naan|dal|paneer|chicken|"
    r"mutton|samosa|lassi|tea|chai|pizza|steak|wings|rings|salad|brownie|"
    r"cheesecake|lemonade|jamun|kheer|roti|paratha|curry|masala|tikka|raita|papad|sandwich|coleslaw|bites|pork|platter|beer|sundae)\b",
    re.IGNORECASE,
)


def _has_order_intent(message: str, last_assistant_msg: str = "", menu_dish_names: List[str] = None) -> bool:
    """Return True if the message likely contains an ordering action."""
    # 1. Action keywords
    if bool(_ORDER_INTENT_RE.search(message)):
        return True

    # 2. Contextual affirmation: assistant recently recommended/asked something
    if last_assistant_msg and bool(_AFFIRMATIVE_RE.search(message)):
        last_lower = last_assistant_msg.lower()
        if any(w in last_lower for w in ["?", "recommend", "suggest", "would you like", "how about", "try", "get you", "add"]):
            return True

    # 3. Direct dish name mention from menu
    if menu_dish_names:
        msg_lower = message.lower()
        for dish in menu_dish_names:
            clean_dish = dish.lower().split("(")[0].strip()
            if len(clean_dish) > 3 and clean_dish in msg_lower:
                return True

    return False



# ─── Simple-Turn Detection ────────────────────────────────────────────────────
# Skip the Gemini embedding API round-trip for short, obviously non-semantic
# turns. After turn 1, memories are already visible in the conversation history.

_SIMPLE_TURN_RE = re.compile(
    r"^(yes|no|ok|okay|sure|thanks|thank\s+you|please|yeah|yep|nope|"
    r"hmm|uh|um|alright|fine|great|perfect|got\s+it|sounds\s+good|"
    r"add\s+one\s+more|one\s+more|same\s+again|that'?s\s+all)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def _needs_memory_retrieval(message: str, history_len: int) -> bool:
    """
    Return False for turns where semantic memory search adds no value.
    After the first turn, memories from turn 1 are already in the conversation
    history, so re-embedding short / obviously simple messages is wasteful.
    """
    if history_len > 0 and (
        len(message) <= 60 or bool(_SIMPLE_TURN_RE.match(message.strip()))
    ):
        return False
    return True


# ─── Chat Endpoint ─────────────────────────────────────────────────────────────

# Hard server-side cap on conversation history sent by client.
# Aligns with the 10-turn slice in build_conversation_messages to avoid
# deserialising more messages than the prompt builder will actually use.
_MAX_HISTORY_TURNS = 10


@router.post("/chat", response_model=ChatResponse, summary="Send a message to the AI concierge")
async def chat(chat_request: ChatRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Main conversational endpoint.

    Performance optimisations applied:
    - Guardrail check (fast regex) before any DB/LLM work
    - Conditional memory retrieval: skip Gemini embedding on simple/mid-conv turns
    - Parallel DB prefetch: customer + menu + active order (+ memories if needed)
    - Intent detection: skip order-extraction LLM call for non-order messages
    - Parallel LLM calls when extraction is needed
    - Batch menu-item lookups (parallel, no N+1 queries)
    - Skip order reload from DB when no actions were applied
    - Menu summary cached for 10 minutes
    - Disconnect check before expensive LLM calls
    """

    # ── Layer 1 & 2: Guardrails ──────────────────────────────────────────────
    # Fast regex checks — no DB/LLM cost. Runs before anything else.
    clean_message, rejection = check_guardrails(chat_request.message)
    if rejection is not None:
        return ChatResponse(
            message=rejection,
            order_actions=[],
            updated_order=None,
            recommendations=[],
            sync_status=OrderSyncStatus(is_synced=True, discrepancies=[]),
        )

    customer_repo = CustomerRepository()
    menu_repo = MenuRepository()
    order_svc = OrderService()
    memory_svc = MemoryService()
    conv_svc = ConversationService()

    t_start = time.monotonic()

    # ── Parallel prefetch — with conditional memory retrieval ———————————————
    # History length tells us whether memories are already in the context window.
    history_len = len(chat_request.conversation_history)
    run_memory = _needs_memory_retrieval(clean_message, history_len)

    if run_memory:
        customer, (menu_summary, menu_dish_names, menu_item_names), order, memories = await asyncio.gather(
            customer_repo.get_by_id(chat_request.customer_id),
            _get_cached_menu_data(menu_repo),
            order_svc.get_or_create_active_order(chat_request.customer_id),
            memory_svc.search_relevant_memories(chat_request.customer_id, clean_message),
        )
    else:
        customer, (menu_summary, menu_dish_names, menu_item_names), order = await asyncio.gather(
            customer_repo.get_by_id(chat_request.customer_id),
            _get_cached_menu_data(menu_repo),
            order_svc.get_or_create_active_order(chat_request.customer_id),
        )
        memories: List[str] = []
        logger.debug("[PERF] Memory retrieval skipped (simple/mid-conversation turn)")

    t_prefetch = time.monotonic()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # ── Build customer context ───────────────────────────────────────────────
    prefs = None
    if customer.preferences:
        p = customer.preferences
        prefs = {
            "spice_level": p.spice_level,
            "dietary_preferences": p.dietary_preferences,
            "allergies": p.allergies,
            "favorite_dishes": p.favorite_dishes,
            "disliked_dishes": p.disliked_dishes,
        }

    # Enforce server-side history limit to prevent token overflow
    history = [
        m.model_dump()
        for m in chat_request.conversation_history[-_MAX_HISTORY_TURNS:]
    ]

    # ── Disconnect check ─────────────────────────────────────────────────────
    if await request.is_disconnected():
        logger.info(
            "Client disconnected before processing (customer_id=%s)",
            chat_request.customer_id,
        )
        raise HTTPException(status_code=503, detail="Client disconnected")

    # ── Order Action Extraction ───────────────────────────────────────────────
    last_assistant_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_assistant_msg = msg.get("content", "")
            break

    has_intent = _has_order_intent(clean_message, last_assistant_msg, menu_dish_names=menu_item_names)
    if has_intent:
        order_summary = _build_order_summary(order)
        raw_actions = await conv_svc.extract_order_actions(
            message=clean_message,
            current_order_summary=order_summary,
            last_assistant_message=last_assistant_msg,
            available_menu_items=menu_dish_names,
        )
        logger.debug("[PERF] Order extraction fired (intent detected)")
    else:
        raw_actions = [{"action": "none"}]
        logger.debug("[PERF] Order extraction skipped (no order intent)")

    t_extract = time.monotonic()
    logger.info("[PERF] extract=%.0fms intent=%s", (t_extract - t_prefetch) * 1000, has_intent)

    # ── Apply order actions & generate structured events ───────────────────────
    order_actions: List[OrderAction] = []
    events: List[ConversationEvent] = []
    applied_actions: List[OrderAction] = []
    order_was_confirmed = False
    order_was_cancelled = False

    logger.info("[CHAT] Extracted actions: %s", raw_actions)

    # Pre-fetch all referenced menu items in parallel — avoids N+1 sequential queries.
    item_names_set: set = set()
    for raw in raw_actions:
        action = raw.get("action", "none")
        if action in ("none", "confirm", "cancel"):
            continue
        if action == "replace":
            if raw.get("old_item_name"):
                item_names_set.add(raw["old_item_name"])
            if raw.get("new_item_name"):
                item_names_set.add(raw["new_item_name"])
        elif raw.get("menu_item_name"):
            item_names_set.add(raw["menu_item_name"])
    item_names = list(item_names_set)
    if item_names:
        fetched_items = await asyncio.gather(*[menu_repo.find_by_name(n) for n in item_names])
        menu_item_cache: Dict[str, Any] = dict(zip(item_names, fetched_items))
    else:
        menu_item_cache = {}

    # Resolve canonical menu item names for expected LLM order state
    resolved_raw_actions = []
    for raw in raw_actions:
        r = dict(raw)
        act = r.get("action", "none")
        if act == "replace":
            old_n = r.get("old_item_name")
            new_n = r.get("new_item_name")
            if old_n and menu_item_cache.get(old_n):
                r["old_item_name"] = menu_item_cache[old_n].name
            if new_n and menu_item_cache.get(new_n):
                r["new_item_name"] = menu_item_cache[new_n].name
        elif r.get("menu_item_name"):
            item_n = r.get("menu_item_name")
            if item_n and menu_item_cache.get(item_n):
                r["menu_item_name"] = menu_item_cache[item_n].name
        resolved_raw_actions.append(r)

    base_order_dict = _build_order_dict(order)
    llm_order = compute_llm_expected_order(base_order_dict, resolved_raw_actions)

    for raw in raw_actions:
        action = raw.get("action", "none")
        if action == "none":
            oa = OrderAction(action="none", status="none", is_retryable=True)
            order_actions.append(oa)
            events.append(ConversationEvent(
                type="conversation_turn",
                status="in_progress",
                is_retryable=True,
            ))
            continue

        if action == "replace":
            item_name = raw.get("new_item_name", "") or raw.get("menu_item_name", "")
        else:
            item_name = raw.get("menu_item_name", "")

        menu_item = menu_item_cache.get(item_name) if item_name else None
        if action != "replace":
            if item_name and not menu_item:
                logger.warning("[CHAT] Menu item not found for name: '%s'", item_name)
            elif item_name and menu_item:
                logger.info("[CHAT] Matched menu item '%s' (id=%s)", menu_item.name, menu_item.id)

        try:
            if action == "add":
                if menu_item:
                    oa = OrderAction(
                        action="add",
                        menu_item_name=menu_item.name,
                        menu_item_id=menu_item.id,
                        quantity=raw.get("quantity", 1),
                        customization_notes=raw.get("customization_notes"),
                        status="success",
                        is_retryable=True,
                    )
                    await order_svc.add_item(
                        order.id,
                        OrderItemAdd(
                            menu_item_id=menu_item.id,
                            quantity=oa.quantity,
                            customization_notes=oa.customization_notes,
                        ),
                    )
                    order_actions.append(oa)
                    applied_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_added",
                        status="success",
                        is_retryable=True,
                        details={"item_name": menu_item.name, "quantity": oa.quantity},
                    ))
                    logger.info("[CHAT] Added %sx '%s' to order #%s", oa.quantity, menu_item.name, order.id)
                else:
                    oa = OrderAction(
                        action="add",
                        menu_item_name=item_name,
                        quantity=raw.get("quantity", 1),
                        status="item_not_found",
                        is_retryable=True,
                    )
                    order_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_add_failed",
                        status="item_not_found",
                        is_retryable=True,
                        details={"item_name": item_name},
                    ))
                    logger.warning("[CHAT] Skipped ADD — menu item '%s' not found in DB", item_name)

            elif action == "remove":
                order = await order_svc.get_order(order.id)
                matching_item = None
                if order.items:
                    for item in order.items:
                        if menu_item and item.menu_item_id == menu_item.id:
                            matching_item = item
                            break
                        elif item_name and item.menu_item and item.menu_item.name.lower() == item_name.lower():
                            matching_item = item
                            break
                if matching_item:
                    oa = OrderAction(
                        action="remove",
                        menu_item_name=matching_item.menu_item.name if matching_item.menu_item else item_name,
                        menu_item_id=matching_item.menu_item_id,
                        quantity=raw.get("quantity", 1),
                        status="success",
                        is_retryable=True,
                    )
                    await order_svc.remove_item(order.id, matching_item.id)
                    order_actions.append(oa)
                    applied_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_removed",
                        status="success",
                        is_retryable=True,
                        details={"item_name": oa.menu_item_name},
                    ))
                    logger.info("[CHAT] Removed '%s' from order #%s", oa.menu_item_name, order.id)
                else:
                    oa = OrderAction(
                        action="remove",
                        menu_item_name=item_name,
                        quantity=raw.get("quantity", 1),
                        status="item_not_in_cart",
                        is_retryable=True,
                    )
                    order_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_remove_failed",
                        status="item_not_in_cart",
                        is_retryable=True,
                        details={"item_name": item_name},
                    ))
                    logger.warning("[CHAT] Skipped REMOVE — item '%s' not in order", item_name)

            elif action == "modify":
                order = await order_svc.get_order(order.id)
                matching_item = None
                if order.items:
                    for item in order.items:
                        if menu_item and item.menu_item_id == menu_item.id:
                            matching_item = item
                            break
                        elif item_name and item.menu_item and item.menu_item.name.lower() == item_name.lower():
                            matching_item = item
                            break
                if matching_item:
                    target_qty = raw.get("quantity", 1)
                    oa = OrderAction(
                        action="modify",
                        menu_item_name=matching_item.menu_item.name if matching_item.menu_item else item_name,
                        menu_item_id=matching_item.menu_item_id,
                        quantity=target_qty,
                        status="success",
                        is_retryable=True,
                    )
                    await order_svc.update_item_quantity(order.id, matching_item.id, target_qty)
                    order_actions.append(oa)
                    applied_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_modified",
                        status="success",
                        is_retryable=True,
                        details={"item_name": oa.menu_item_name, "quantity": target_qty},
                    ))
                    logger.info("[CHAT] Modified '%s' quantity to %s in order #%s", oa.menu_item_name, target_qty, order.id)
                else:
                    oa = OrderAction(
                        action="modify",
                        menu_item_name=item_name,
                        quantity=raw.get("quantity", 1),
                        status="item_not_in_cart",
                        is_retryable=True,
                    )
                    order_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_modify_failed",
                        status="item_not_in_cart",
                        is_retryable=True,
                        details={"item_name": item_name},
                    ))
                    logger.warning("[CHAT] Skipped MODIFY — item '%s' not in order", item_name)

            elif action == "replace":
                old_name = raw.get("old_item_name", "")
                new_name = raw.get("new_item_name", "")
                old_menu_item = menu_item_cache.get(old_name) if old_name else None
                new_menu_item = menu_item_cache.get(new_name) if new_name else None

                order = await order_svc.get_order(order.id)
                old_order_item = None
                if order.items:
                    for item in order.items:
                        if old_menu_item and item.menu_item_id == old_menu_item.id:
                            old_order_item = item
                            break
                        elif old_name and item.menu_item and item.menu_item.name.lower() == old_name.lower():
                            old_order_item = item
                            break
                if old_order_item:
                    await order_svc.remove_item(order.id, old_order_item.id)
                    logger.info("[CHAT] Replace: removed '%s' from order #%s", old_name, order.id)

                if new_menu_item:
                    oa = OrderAction(
                        action="replace",
                        menu_item_name=new_menu_item.name,
                        menu_item_id=new_menu_item.id,
                        quantity=raw.get("quantity", 1),
                        customization_notes=raw.get("customization_notes"),
                        status="success",
                        is_retryable=True,
                    )
                    await order_svc.add_item(
                        order.id,
                        OrderItemAdd(
                            menu_item_id=new_menu_item.id,
                            quantity=oa.quantity,
                            customization_notes=oa.customization_notes,
                        ),
                    )
                    order_actions.append(oa)
                    applied_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_replaced",
                        status="success",
                        is_retryable=True,
                        details={"old_item": old_name, "new_item": new_name},
                    ))
                    logger.info("[CHAT] Replace: added '%s' to order #%s", new_name, order.id)
                else:
                    oa = OrderAction(
                        action="replace",
                        menu_item_name=new_name,
                        status="item_not_found",
                        is_retryable=True,
                    )
                    order_actions.append(oa)
                    events.append(ConversationEvent(
                        type="item_replace_failed",
                        status="item_not_found",
                        is_retryable=True,
                        details={"new_item": new_name},
                    ))

            elif action == "confirm":
                current_cart = await order_svc.get_order(order.id)
                if current_cart.items:
                    await order_svc.confirm_order(order.id)
                    order_was_confirmed = True
                    oa = OrderAction(
                        action="confirm",
                        status="confirmed",
                        is_retryable=False,
                    )
                    order_actions.append(oa)
                    applied_actions.append(oa)
                    events.append(ConversationEvent(
                        type="order_confirmed",
                        status="confirmed",
                        is_retryable=False,
                        details={"order_id": order.id, "total_amount": float(current_cart.total_amount)},
                    ))
                    logger.info("[CHAT] Order #%s confirmed", order.id)
                else:
                    oa = OrderAction(
                        action="confirm",
                        status="failed_empty_order",
                        is_retryable=True,
                    )
                    order_actions.append(oa)
                    events.append(ConversationEvent(
                        type="order_confirmation_failed",
                        status="failed_empty_order",
                        is_retryable=True,
                        details={"message": "Cannot confirm an empty order"},
                    ))
                    logger.warning("[CHAT] Skipped CONFIRM — order #%s is empty", order.id)

            elif action == "cancel":
                await order_svc.cancel_order(order.id)
                order_was_cancelled = True
                oa = OrderAction(
                    action="cancel",
                    status="cancelled",
                    is_retryable=False,
                )
                order_actions.append(oa)
                applied_actions.append(oa)
                events.append(ConversationEvent(
                    type="order_cancelled",
                    status="cancelled",
                    is_retryable=False,
                    details={"order_id": order.id},
                ))
                logger.info("[CHAT] Order #%s cancelled", order.id)

        except Exception as e:
            logger.error("[CHAT] Failed to apply action '%s': %s", action, e, exc_info=True)
            events.append(ConversationEvent(
                type=f"action_{action}_error",
                status="error",
                is_retryable=True,
                details={"error": str(e)},
            ))

    if not events:
        events.append(ConversationEvent(
            type="conversation_turn",
            status="in_progress",
            is_retryable=True,
        ))

    t_actions = time.monotonic()
    logger.info("[PERF] actions=%.0fms applied=%d", (t_actions - t_extract) * 1000, len(applied_actions))

    # ── Reload updated order if actions changed it ───────────────────────────
    if applied_actions:
        updated_order = await order_svc.get_order(order.id)
    else:
        updated_order = order
    updated_order_dict = _build_order_dict(updated_order)

    # ── Validate order synchronization against actual cart (SOURCE OF TRUTH) ─
    sync_status = validate_order_sync(llm_order, updated_order_dict)
    if not sync_status.is_synced:
        logger.warning(
            "[CHAT] Order sync discrepancies detected: %s",
            [d.model_dump() for d in sync_status.discrepancies],
        )
        events.append(
            ConversationEvent(
                type="order_sync_discrepancy",
                status="discrepancy_detected",
                is_retryable=True,
                details={"discrepancies": [d.model_dump() for d in sync_status.discrepancies]},
            )
        )
        sync_instruction = (
            "Reconcile the order with the actual cart state before continuing. "
            "The actual cart is the authoritative truth. Never claim items exist if missing."
        )
    else:
        sync_instruction = "Actual cart and LLM order are synchronized."

    # ── Determine user intent for structured context ─────────────────────────
    if order_was_confirmed:
        user_intent = "order_confirm"
    elif order_was_cancelled:
        user_intent = "order_cancel"
    elif any(a.action == "add" for a in applied_actions):
        user_intent = "order_add"
    elif any(a.action == "remove" for a in applied_actions):
        user_intent = "order_remove"
    elif any(a.action == "modify" for a in applied_actions):
        user_intent = "order_modify"
    elif any(a.action == "replace" for a in applied_actions):
        user_intent = "order_replace"
    elif has_intent:
        user_intent = "order_request"
    else:
        user_intent = "inquiry"

    # ── Build unified structured context JSON ────────────────────────────────
    structured_context = build_structured_context_dict(
        user_intent=user_intent,
        current_request=clean_message,
        conversation_history=history,
        order=updated_order_dict,
        customer_name=customer.name,
        customer_preferences=prefs,
        recent_memories=memories,
        events=[e.model_dump() for e in events],
        llm_order=llm_order,
        actual_cart=updated_order_dict,
        sync_status=sync_status.model_dump(),
        instruction=sync_instruction,
    )

    # ── Disconnect check before chat LLM call ────────────────────────────────
    if await request.is_disconnected():
        logger.info(
            "Client disconnected before chat LLM call (customer_id=%s)",
            chat_request.customer_id,
        )
        raise HTTPException(status_code=503, detail="Client disconnected")

    # ── Call LLM with complete structured context ─────────────────────────────
    ai_response = await conv_svc.chat(
        customer_name=customer.name,
        preferences=prefs,
        menu_summary=menu_summary,
        current_order=updated_order_dict,
        recent_memories=memories,
        conversation_history=history,
        user_message=clean_message,
        structured_context=structured_context,
    )

    # ── Guard against false success in AI response when discrepancy exists ────
    if not sync_status.is_synced:
        cart_item_names = {
            clean_dish_name(it.get("menu_item_name", ""))
            for it in updated_order_dict.get("items", [])
        }
        for d in sync_status.discrepancies:
            if d.field == "item_missing" and d.item:
                clean_d_item = clean_dish_name(d.item)
                if clean_d_item not in cart_item_names:
                    pattern = rf"\b(added|adding|got you|put in)\b[^\.\?!]*\b{re.escape(clean_d_item)}\b"
                    has_false_claim = bool(re.search(pattern, ai_response.lower()))
                    has_disclaimer = any(
                        w in ai_response.lower()
                        for w in [
                            "sorry",
                            "unfortunately",
                            "don't have",
                            "unavailable",
                            "not on the menu",
                            "not in the cart",
                            "couldn't add",
                            "cannot add",
                        ]
                    )
                    if has_false_claim and not has_disclaimer:
                        logger.warning("[CHAT] Overriding false success claim for missing item '%s'", d.item)
                        ai_response = (
                            f"I'm sorry, but {d.item} isn't available on our menu, so I couldn't add it to your order. "
                            f"Would you like to try something else from our menu?"
                        )
                        break
            elif d.field == "quantity" and d.item:
                clean_d_item = clean_dish_name(d.item)
                pattern = rf"\b(added|got)\s+{d.llm_value}\s+{re.escape(clean_d_item)}\b"
                if bool(re.search(pattern, ai_response.lower())):
                    logger.warning("[CHAT] Overriding false quantity claim for '%s'", d.item)
                    ai_response = (
                        f"I was only able to add {d.cart_value} {d.item} to your order. "
                        f"Would you like me to try adding more or keep it at {d.cart_value}?"
                    )
                    break

    t_end = time.monotonic()
    logger.info("[PERF] total=%.0fms intent=%s order_reloaded=%s synced=%s",
                (t_end - t_start) * 1000, has_intent, bool(applied_actions), sync_status.is_synced)

    # ── After confirm/cancel: store memory ───────────────────────────────────
    if order_was_confirmed or order_was_cancelled:
        convo_lines = [
            f"{('Customer' if m['role'] == 'user' else 'Diaa')}: {m['content']}"
            for m in history[-10:]
        ]
        convo_lines.append(f"Customer: {clean_message}")
        convo_lines.append(f"Diaa: {ai_response}")
        convo_text = "\n".join(convo_lines)
        background_tasks.add_task(
            memory_svc.store_conversation_summary,
            chat_request.customer_id,
            convo_text,
        )

    return ChatResponse(
        message=ai_response,
        order_actions=order_actions,
        events=events,
        updated_order=updated_order_dict,
        recommendations=[],
        sync_status=sync_status,
    )


# ─── Session End (Logout) ─────────────────────────────────────────────────────


@router.post("/end-session", summary="Save memory when customer ends session")
async def end_session(body: SessionEndRequest, background_tasks: BackgroundTasks):
    """
    Called by the frontend when the user signs out.
    Saves a conversation summary so Aria remembers the session next time,
    even if no order was confirmed. Fires as a background task so the
    logout response is instant.
    """
    if len(body.conversation_history) < 2:
        return {"saved": False, "reason": "Not enough history to summarize"}

    memory_svc = MemoryService()
    convo_text = "\n".join(
        f"{('Customer' if m.get('role') == 'user' else 'Diaa')}: {m.get('content', '')}"
        for m in body.conversation_history[-10:]
    )

    background_tasks.add_task(
        memory_svc.store_conversation_summary,
        body.customer_id,
        convo_text,
    )
    return {"saved": True}
