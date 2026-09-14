import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from app.repositories.customer_repository import CustomerRepository
from app.repositories.menu_repository import MenuRepository
from app.schemas.conversation import ChatRequest, ChatResponse, OrderAction
from app.schemas.order import OrderItemAdd
from app.services.openai.conversation_service import ConversationService
from app.services.guardrails.domain_guard import check_guardrails
from app.services.memory.memory_service import MemoryService
from app.services.order_service import OrderService


class SessionEndRequest(BaseModel):
    customer_id: int
    conversation_history: List[Dict] = []

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ─── Menu Cache ───────────────────────────────────────────────────────────────
# The full menu is fetched on every chat turn without caching.
# Since menu items rarely change, we cache the compiled summary string.

_menu_cache: Dict = {"summary": None, "expires": 0.0}
_menu_lock = asyncio.Lock()
_MENU_CACHE_TTL = 600  # 10 minutes


async def _get_cached_menu_summary(menu_repo: MenuRepository) -> str:
    """Return cached menu summary, refreshing if expired."""
    async with _menu_lock:
        now = time.monotonic()
        if _menu_cache["summary"] and now < _menu_cache["expires"]:
            return _menu_cache["summary"]
        items = await menu_repo.get_all(available_only=True)
        _menu_cache["summary"] = _build_menu_summary(items)
        _menu_cache["expires"] = now + _MENU_CACHE_TTL
        logger.debug("Menu cache refreshed")
        return _menu_cache["summary"]


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
        lines.append(f"  - {item.quantity}x {name} @ \u20b9{float(item.unit_price):.0f}")
    return "\n".join(lines)


# ─── Order Intent Detection ───────────────────────────────────────────────────
# Lightweight regex pre-filter that decides whether to fire the order-extraction
# LLM call. Skipping it on non-order turns saves ~1,500 ms + token cost.

_ORDER_INTENT_RE = re.compile(
    r"\b(add|order|remove|delete|cancel|confirm|checkout|"
    r"give\s+me|get\s+me|bring\s+me|make\s+it|make\s+that|"
    r"change|modify|update|replace|swap|take\s+away|drop|"
    r"more|less|another|extra|quantity|"
    r"i('d|\s+would|\s+will)?\s+like|i('ll|\s+will)\s+(take|have|get)|"
    r"can\s+i\s+(have|get)|put\s+in|throw\s+in|include|exclude|"
    r"biryani|rice|coke|milkshake|burger|fries|naan|dal|paneer|chicken|"
    r"mutton|samosa|lassi|tea|chai|pizza|steak|wings|rings|salad|brownie|"
    r"cheesecake|lemonade|jamun|kheer|roti|paratha|curry|masala|tikka|raita|papad|sandwich|coleslaw|bites|pork|platter|beer|sundae)\b",
    re.IGNORECASE,
)


def _has_order_intent(message: str) -> bool:
    """Return True if the message likely contains an ordering action."""
    return bool(_ORDER_INTENT_RE.search(message))


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
        customer, menu_summary, order, memories = await asyncio.gather(
            customer_repo.get_by_id(chat_request.customer_id),
            _get_cached_menu_summary(menu_repo),
            order_svc.get_or_create_active_order(chat_request.customer_id),
            memory_svc.search_relevant_memories(chat_request.customer_id, clean_message),
        )
    else:
        customer, menu_summary, order = await asyncio.gather(
            customer_repo.get_by_id(chat_request.customer_id),
            _get_cached_menu_summary(menu_repo),
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
    # Check if client navigated away before we make the expensive LLM calls.
    # This avoids wasting Gemini quota on abandoned requests.
    if await request.is_disconnected():
        logger.info(
            "Client disconnected before LLM call (customer_id=%s)",
            chat_request.customer_id,
        )
        raise HTTPException(status_code=503, detail="Client disconnected")

    # ── Conditional LLM calls ──────────────────────────────────────────────────────────────────
    # Only fire the order-extraction LLM call when the message has order intent.
    # This saves ~1,500 ms + token cost on conversational / Q&A turns (~50% of turns).
    # When extraction is needed, both calls run concurrently via asyncio.gather.
    chat_coro = conv_svc.chat(
        customer_name=customer.name,
        preferences=prefs,
        menu_summary=menu_summary,
        current_order=_build_order_dict(order),
        recent_memories=memories,
        conversation_history=history,
        user_message=clean_message,
    )
    has_intent = _has_order_intent(clean_message)
    if has_intent:
        order_summary = _build_order_summary(order)
        last_assistant_msg = ""
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                last_assistant_msg = msg.get("content", "")
                break
        ai_response, raw_actions = await asyncio.gather(
            chat_coro,
            conv_svc.extract_order_actions(clean_message, order_summary, last_assistant_msg),
        )
        logger.debug("[PERF] Order extraction fired (intent detected)")
    else:
        ai_response = await chat_coro
        raw_actions = [{"action": "none"}]
        logger.debug("[PERF] Order extraction skipped (no order intent)")

    t_llm = time.monotonic()
    logger.info("[PERF] llm=%.0fms intent=%s", (t_llm - t_prefetch) * 1000, has_intent)

    # ── Apply order actions ──────────────────────────────────────────────────────────────────────
    order_actions: List[OrderAction] = []
    applied_actions: List[OrderAction] = []
    order_was_confirmed = False
    order_was_cancelled = False

    logger.info("[CHAT] Extracted actions: %s", raw_actions)

    # Pre-fetch all referenced menu items in parallel — avoids N+1 sequential queries.
    # Collect names from add/remove/modify AND both sides of replace actions.
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

    for raw in raw_actions:
        action = raw.get("action", "none")
        if action == "none":
            continue

        # For replace actions, the display name is the new item being added.
        # Regular add/remove/modify use menu_item_name.
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

        oa = OrderAction(
            action=action,
            menu_item_name=item_name,
            menu_item_id=menu_item.id if menu_item else None,
            quantity=raw.get("quantity", 1),
            customization_notes=raw.get("customization_notes"),
        )
        order_actions.append(oa)

        try:
            if action == "add" and menu_item:
                await order_svc.add_item(
                    order.id,
                    OrderItemAdd(
                        menu_item_id=menu_item.id,
                        quantity=oa.quantity,
                        customization_notes=oa.customization_notes,
                    ),
                )
                applied_actions.append(oa)
                logger.info("[CHAT] Added %sx '%s' to order #%s", oa.quantity, menu_item.name, order.id)
            elif action == "add" and not menu_item:
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
                    await order_svc.remove_item(order.id, matching_item.id)
                    applied_actions.append(oa)
                    logger.info("[CHAT] Removed '%s' from order #%s", matching_item.menu_item.name, order.id)
                else:
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
                    await order_svc.update_item_quantity(order.id, matching_item.id, target_qty)
                    applied_actions.append(oa)
                    logger.info("[CHAT] Modified '%s' quantity to %s in order #%s", matching_item.menu_item.name, target_qty, order.id)
                else:
                    logger.warning("[CHAT] Skipped MODIFY — item '%s' not in order", item_name)
            elif action == "replace":
                old_name = raw.get("old_item_name", "")
                new_name = raw.get("new_item_name", "")
                old_menu_item = menu_item_cache.get(old_name) if old_name else None
                new_menu_item = menu_item_cache.get(new_name) if new_name else None

                # Step 1: Remove the old item
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
                else:
                    logger.warning("[CHAT] Replace: old item '%s' not in order — skipping remove", old_name)

                # Step 2: Add the new item
                if new_menu_item:
                    await order_svc.add_item(
                        order.id,
                        OrderItemAdd(
                            menu_item_id=new_menu_item.id,
                            quantity=oa.quantity,
                            customization_notes=oa.customization_notes,
                        ),
                    )
                    applied_actions.append(oa)
                    logger.info("[CHAT] Replace: added '%s' to order #%s", new_name, order.id)
                else:
                    logger.warning("[CHAT] Replace: new item '%s' not found in DB", new_name)
            elif action == "confirm":
                if order.items:
                    await order_svc.confirm_order(order.id)
                    applied_actions.append(oa)
                    order_was_confirmed = True
                    logger.info("[CHAT] Order #%s confirmed", order.id)
                else:
                    logger.warning("[CHAT] Skipped CONFIRM — order #%s is empty", order.id)
            elif action == "cancel":
                await order_svc.cancel_order(order.id)
                applied_actions.append(oa)
                order_was_cancelled = True
                logger.info("[CHAT] Order #%s cancelled", order.id)
        except Exception as e:
            logger.error("[CHAT] Failed to apply action '%s': %s", action, e, exc_info=True)

    t_actions = time.monotonic()
    logger.info("[PERF] actions=%.0fms applied=%d", (t_actions - t_llm) * 1000, len(applied_actions))

    # ── Reload updated order (only when something actually changed) ─────────────────────
    # Skip the extra DB round-trip for pure conversational turns where no
    # add/remove/confirm/cancel actions were applied.
    if applied_actions:
        updated_order = await order_svc.get_order(order.id)
    else:
        updated_order = order  # reuse the already-fetched order — nothing changed

    logger.info("[PERF] total=%.0fms order_reloaded=%s",
                (time.monotonic() - t_start) * 1000, bool(applied_actions))

    # ── After confirm/cancel: store memory ───────────────────────────────────
    # Memory storage is fired as a background task so it never delays the response.
    if order_was_confirmed or order_was_cancelled:
        # Build conversation text for memory from the last N turns
        if len(history) >= 2:
            convo_text = "\n".join(
                f"{('Customer' if m['role'] == 'user' else 'Diaa')}: {m['content']}"
                for m in history[-10:]
            )
            background_tasks.add_task(
                memory_svc.store_conversation_summary,
                chat_request.customer_id,
                convo_text,
            )

    return ChatResponse(
        message=ai_response,
        order_actions=order_actions,
        # Return the confirmed/cancelled order so the frontend can display the final state.
        updated_order=_build_order_dict(updated_order),
        recommendations=[],
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
