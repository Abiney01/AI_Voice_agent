"""
Order synchronization and discrepancy detection service.

Connects the LLM's expected order state with the authoritative database cart,
detects discrepancies, and prevents false success.
"""

import re
from typing import Any, Dict, List, Optional
from app.schemas.conversation import OrderDiscrepancy, OrderSyncStatus


def clean_dish_name(name: str) -> str:
    """Normalize dish name for robust, case-insensitive comparison."""
    if not name:
        return ""
    # Remove (V), [spice level], and extra whitespace
    cleaned = re.sub(r"\s*\([vV]\)\s*", " ", name)
    cleaned = re.sub(r"\s*\[[^\]]+\]\s*", " ", cleaned)
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"['\"]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def compute_llm_expected_order(
    base_cart: Optional[Dict[str, Any]],
    raw_actions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute what the LLM expects the cart/order to look like after applying raw_actions.
    This creates the explicit 'llm_order' JSON representation.
    """
    base_cart = base_cart or {}
    expected_status = base_cart.get("status", "active")

    # Start with existing cart items: dict of clean_name -> {name, quantity}
    items_map: Dict[str, Dict[str, Any]] = {}
    for item in base_cart.get("items", []):
        display_name = item.get("menu_item_name", "")
        clean_key = clean_dish_name(display_name)
        qty = int(item.get("quantity", 1))
        if clean_key:
            items_map[clean_key] = {
                "name": display_name,
                "quantity": qty,
            }

    # Apply raw_actions sequentially to mirror the LLM's intent
    for raw in raw_actions:
        action = raw.get("action", "none")
        if action == "none":
            continue

        if action == "add":
            item_name = raw.get("menu_item_name", "")
            qty = int(raw.get("quantity", 1))
            clean_key = clean_dish_name(item_name)
            if clean_key:
                if clean_key in items_map:
                    items_map[clean_key]["quantity"] += qty
                else:
                    items_map[clean_key] = {
                        "name": item_name,
                        "quantity": qty,
                    }

        elif action == "remove":
            item_name = raw.get("menu_item_name", "")
            qty = int(raw.get("quantity", 1))
            clean_key = clean_dish_name(item_name)
            if clean_key and clean_key in items_map:
                items_map[clean_key]["quantity"] -= qty
                if items_map[clean_key]["quantity"] <= 0:
                    del items_map[clean_key]

        elif action == "modify":
            item_name = raw.get("menu_item_name", "")
            qty = int(raw.get("quantity", 1))
            clean_key = clean_dish_name(item_name)
            if clean_key:
                if qty <= 0:
                    items_map.pop(clean_key, None)
                else:
                    items_map[clean_key] = {
                        "name": item_name or items_map.get(clean_key, {}).get("name", ""),
                        "quantity": qty,
                    }

        elif action == "replace":
            old_name = raw.get("old_item_name", "")
            new_name = raw.get("new_item_name", "")
            qty = int(raw.get("quantity", 1))
            old_key = clean_dish_name(old_name)
            new_key = clean_dish_name(new_name)
            if old_key:
                items_map.pop(old_key, None)
            if new_key:
                items_map[new_key] = {
                    "name": new_name,
                    "quantity": qty,
                }

        elif action == "confirm":
            expected_status = "confirmed"

        elif action == "cancel":
            expected_status = "cancelled"
            items_map.clear()

    return {
        "id": base_cart.get("id"),
        "status": expected_status,
        "items": [
            {
                "menu_item_name": data["name"],
                "quantity": data["quantity"],
            }
            for data in items_map.values()
            if data["quantity"] > 0
        ],
    }


def validate_order_sync(
    llm_order: Dict[str, Any],
    actual_cart: Dict[str, Any],
) -> OrderSyncStatus:
    """
    Compare the LLM's expected order state against the authoritative actual cart state.

    Detects:
    - Item missing from cart
    - Unexpected item in cart
    - Incorrect quantity
    - Order status differences
    - False success conditions
    """
    discrepancies: List[OrderDiscrepancy] = []

    # 1. Compare Order Status
    llm_status = llm_order.get("status", "active")
    cart_status = actual_cart.get("status", "active")
    if llm_status != cart_status:
        discrepancies.append(
            OrderDiscrepancy(
                field="order_status",
                item=None,
                llm_value=llm_status,
                cart_value=cart_status,
                message=(
                    f"Expected order status '{llm_status}', but actual cart status is '{cart_status}'."
                ),
            )
        )

    # 2. Build normalized item lookups
    llm_items: Dict[str, Dict[str, Any]] = {}
    for it in llm_order.get("items", []):
        name = it.get("menu_item_name", "")
        clean_key = clean_dish_name(name)
        if clean_key:
            llm_items[clean_key] = {
                "name": name,
                "quantity": int(it.get("quantity", 1)),
            }

    cart_items: Dict[str, Dict[str, Any]] = {}
    for it in actual_cart.get("items", []):
        name = it.get("menu_item_name", "")
        clean_key = clean_dish_name(name)
        if clean_key:
            cart_items[clean_key] = {
                "name": name,
                "quantity": int(it.get("quantity", 1)),
            }

    # 3. Check for items expected by LLM
    for clean_key, llm_data in llm_items.items():
        expected_qty = llm_data["quantity"]
        item_name = llm_data["name"]

        if clean_key not in cart_items:
            discrepancies.append(
                OrderDiscrepancy(
                    field="item_missing",
                    item=item_name,
                    llm_value=expected_qty,
                    cart_value=0,
                    message=(
                        f"Item '{item_name}' (qty {expected_qty}) was expected, "
                        f"but is missing from the actual cart."
                    ),
                )
            )
        else:
            cart_qty = cart_items[clean_key]["quantity"]
            if cart_qty != expected_qty:
                discrepancies.append(
                    OrderDiscrepancy(
                        field="quantity",
                        item=item_name,
                        llm_value=expected_qty,
                        cart_value=cart_qty,
                        message=(
                            f"Expected quantity {expected_qty} for '{item_name}', "
                            f"but actual cart has {cart_qty}."
                        ),
                    )
                )

    # 4. Check for unexpected items in actual cart
    for clean_key, cart_data in cart_items.items():
        if clean_key not in llm_items:
            item_name = cart_data["name"]
            cart_qty = cart_data["quantity"]
            discrepancies.append(
                OrderDiscrepancy(
                    field="unexpected_item",
                    item=item_name,
                    llm_value=0,
                    cart_value=cart_qty,
                    message=(
                        f"Unexpected item '{item_name}' (qty {cart_qty}) found in actual cart."
                    ),
                )
            )

    is_synced = len(discrepancies) == 0
    return OrderSyncStatus(is_synced=is_synced, discrepancies=discrepancies)
