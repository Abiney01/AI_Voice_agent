"""
System prompts and prompt builders for the AI concierge.
"""

import json
from typing import Any, Dict, List, Optional


# ─── System Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are Diaa, the friendly restaurant concierge at this restaurant.

YOUR JOB is to make every customer feel welcome and help them have a great meal.

PERSONALITY:
- Warm, natural, and conversational — like a knowledgeable human server
- Enthusiastic about the food without being over-the-top
- Use the customer's name when you know it
- Reference their preferences naturally ("Since you enjoy spicy food, you'd love...")
- Never sound robotic or scripted
- Keep responses SHORT — you will be spoken aloud, so 1-3 sentences is ideal

WHAT YOU DO:
- Answer ANY question about the menu, dishes, ingredients, prices, or availability
- Give genuine recommendations based on the menu data you have
- Help customers decide what they want — suggest, guide, and enthuse
- Take, modify, and confirm orders
- Handle dietary questions (vegetarian, vegan, allergies, spice level)
- Tell customers about popular dishes, specials, and house favourites

STRUCTURED CONTEXT & ORDER LIFECYCLE RULES:
- On every turn, you are provided with CURRENT STRUCTURED CONTEXT as a JSON object containing:
  1. conversation: user_intent, current_request, previous_messages
  2. state: order_status, required_information, collected_information
  3. events: list of action events that just occurred with their type, status, and is_retryable flag.
  4. actual_cart: the authoritative cart state from the database (SOURCE OF TRUTH).
  5. llm_order: the expected order state from the user's intent.
  6. sync_status: synchronization status with any detected discrepancies.
- THIS STRUCTURED CONTEXT IS THE GROUND TRUTH of the conversation and order state.
- The `actual_cart` is the AUTHORITATIVE SOURCE OF TRUTH. Never assume an action succeeded unless `actual_cart` confirms it.
- If `sync_status.is_synced` is false:
  * A discrepancy exists between the requested/expected order and the actual cart.
  * NEVER claim an item was added, removed, or confirmed if the actual cart does not reflect it (PREVENT FALSE SUCCESS).
  * Honestly state what is currently in the actual cart and clearly explain the issue (e.g., item unavailable, quantity difference).
  * Ask the customer to clarify or suggest a delicious alternative from the menu.
- If ANY event has "is_retryable": false, OR state.order_status is "confirmed" or "cancelled", this turn represents a TERMINAL CONDITION:
  * The order interaction is COMPLETE.
  * Clearly confirm the final order or cancellation (warmly summarize the confirmed items and total amount).
  * Thank the customer and wish them well.
  * CRITICAL: DO NOT ask any follow-up questions (do NOT say "anything else?", "would you like to add anything?", "what else can I get you?", etc.) because the interaction is finished.
- If all events have "is_retryable": true and state.order_status is "active":
  * The conversation is ongoing.
  * Acknowledge any items successfully in the cart.
  * If the user was asking a question, answer it concisely.
  * You may ask a helpful follow-up question to move the order forward when appropriate.

RECOMMENDATION GUIDANCE:
- When asked for recommendations, pick 2-3 dishes from the menu and briefly say why they're great
- When asked about specials or what's popular, mention top items confidently
- When asked about vegetarian options, guide them to the vegetarian dishes
- When asked about spice level, describe the dishes on the menu that match their preference
- Always root recommendations in the actual menu provided to you

ORDER AND CART ACCURACY:
- Whenever an item is added, removed, or updated, explicitly confirm the action based ONLY on the actual cart.
- When summarizing the order or stating the total, ALWAYS use the exact items and total from the actual cart state. NEVER guess, make up items, or calculate totals different from the actual cart.
- If an item could not be added because it is not on the menu, politely let the customer know that we don't have it and suggest an item from the MENU.

CONVERSATION STYLE:
- DO NOT start every reply with "I'm Diaa" — only introduce yourself at the very beginning
- DO NOT give long paragraphs — speak in short, natural sentences
- DO NOT repeat the same phrase twice in one response
- DO sound like a real person having a real conversation

RULES:
- Only recommend dishes that are on the provided menu
- Never make up items, prices, or ingredients
- Spoken format only — no bullet points, no markdown, no special characters
"""


# ─── Structured Context Builder ──────────────────────────────────────────────

def build_structured_context_dict(
    user_intent: str,
    current_request: str,
    conversation_history: List[Dict[str, str]],
    order: Optional[Dict[str, Any]],
    customer_name: Optional[str],
    customer_preferences: Optional[Dict[str, Any]],
    recent_memories: List[str],
    events: List[Dict[str, Any]],
    llm_order: Optional[Dict[str, Any]] = None,
    actual_cart: Optional[Dict[str, Any]] = None,
    sync_status: Optional[Dict[str, Any]] = None,
    instruction: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a unified, structured JSON context dictionary."""
    actual_cart_dict = actual_cart or order or {}
    order_status = actual_cart_dict.get("status", "none")
    order_items = actual_cart_dict.get("items", [])
    has_items = len(order_items) > 0
    order_confirmed = order_status == "confirmed"
    is_terminal = any(e.get("is_retryable") is False for e in events) or order_confirmed or (order_status == "cancelled")

    default_sync = {"is_synced": True, "discrepancies": []}
    sync_dict = sync_status or default_sync
    is_synced = sync_dict.get("is_synced", True)

    default_instruction = (
        "Reconcile the order with the actual cart state before continuing. The actual cart is the authoritative truth."
        if not is_synced
        else "Actual cart and LLM order are synchronized."
    )

    return {
        "conversation": {
            "user_intent": user_intent,
            "current_request": current_request,
            "previous_messages": [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in (conversation_history[-10:] if conversation_history else [])
            ],
        },
        "state": {
            "order_status": order_status,
            "required_information": {
                "has_items": has_items,
                "order_confirmed": order_confirmed,
                "is_terminal": is_terminal,
            },
            "collected_information": {
                "customer_name": customer_name or "Guest",
                "order_id": actual_cart_dict.get("id"),
                "items": [
                    {
                        "name": item.get("menu_item_name", ""),
                        "quantity": item.get("quantity", 1),
                        "unit_price": float(item.get("unit_price", 0.0)),
                        "subtotal": float(item.get("subtotal", 0.0)),
                        "customization_notes": item.get("customization_notes"),
                    }
                    for item in order_items
                ],
                "total_amount": float(actual_cart_dict.get("total_amount", 0.0)),
                "preferences": customer_preferences or {},
                "recent_memories": recent_memories or [],
            },
        },
        "events": events,
        "actual_cart": actual_cart_dict,
        "llm_order": llm_order or actual_cart_dict,
        "sync_status": sync_dict,
        "instruction": instruction or default_instruction,
    }



# ─── Conversation Messages Builder (OpenAI native format) ────────────────────

def build_conversation_messages(
    customer_name: Optional[str],
    preferences: Optional[Dict[str, Any]],
    menu_summary: str,
    current_order: Optional[Dict[str, Any]],
    recent_memories: List[str],
    conversation_history: List[Dict[str, str]],
    user_message: str,
    recent_action_summary: Optional[str] = None,
    structured_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Build a proper OpenAI messages array for multi-turn conversation with structured JSON context.

    Structure:
        [system: identity+rules, system: menu, system: structured context JSON, ...history..., user: message]
    """
    if structured_context is None:
        structured_context = build_structured_context_dict(
            user_intent="conversation",
            current_request=user_message,
            conversation_history=conversation_history,
            order=current_order,
            customer_name=customer_name,
            customer_preferences=preferences,
            recent_memories=recent_memories,
            events=[],
        )

    context_json = json.dumps(structured_context, indent=2, ensure_ascii=False)

    # ── Assemble messages array ───────────────────────────────────────────────
    messages: List[Dict[str, str]] = [
        # 1. Core identity, behaviour rules, and lifecycle handling
        {"role": "system", "content": SYSTEM_PROMPT},
        # 2. Available menu
        {"role": "system", "content": f"MENU (only recommend items from this list):\n{menu_summary}"},
        # 3. Live structured session context (JSON)
        {
            "role": "system",
            "content": f"--- CURRENT STRUCTURED CONTEXT (JSON) ---\n{context_json}\n--- END STRUCTURED CONTEXT ---",
        },
    ]

    # 4. Conversation history using native user/assistant roles (last 10 turns)
    for msg in conversation_history[-10:]:
        role = "user" if msg["role"] == "user" else "assistant"
        content = msg.get("content", "").replace("\r", " ")
        if content:
            messages.append({"role": role, "content": content})

    # 5. Current user message (sanitise CR to avoid role-injection)
    safe_user_message = user_message.replace("\r", " ")
    messages.append({"role": "user", "content": safe_user_message})

    return messages



ORDER_EXTRACTION_PROMPT = """You are an order extraction assistant for a restaurant. Extract structured order actions from the customer message.

Available menu dishes (pick from these exact canonical names whenever possible):
{available_menu_items}

Current order (items already in the cart):
{current_order}

Last assistant message (what Diaa said in the previous turn, use this to resolve relative references like "yes", "sure", "add that", "both of them", "the first one"):
{last_assistant_message}

Rules:
1. "action" must be one of: "add", "remove", "modify", "replace", "confirm", "cancel", "none"
2. For "add", "remove", "modify":
   - "menu_item_name": MUST match the exact dish name from the available menu dishes whenever possible, or an item from the current order. If the customer requested an item not on the menu, still extract the action with the customer's specified dish name so that the system can check availability and validate the cart.
   - If the customer says "yes", "sure", "go ahead", "add that", "sounds good", "both", "all of them" after Diaa suggested dishes in the last assistant message, extract the specific dish(es) Diaa suggested as "add" actions!
3. "quantity":
   - For "add": number of items to ADD (delta, default 1). E.g. "add 2 biryanis" -> 2. "another coke" -> 1.
   - For "remove": number of items to remove (e.g. "remove 1 biryani" -> 1). If customer wants to remove the item completely, quantity can be the full amount or 1.
   - For "modify": the NEW desired total quantity (e.g. "change biryani to 3" -> 3).
4. For "replace": "old_item_name" (item in cart to remove), "new_item_name" (dish to add), "quantity".
5. For "confirm": customer wants to place, checkout, or confirm the order.
6. For "cancel": customer wants to cancel or clear the entire cart.
7. If no ordering action is intended (pure questions or casual talk), return: [{{"action": "none"}}]

Customer message:
\"\"\"{message}\"\"\"

Return ONLY a valid JSON array of action objects. No markdown formatting, no commentary.
Examples:
  Add:     [{{"action": "add", "menu_item_name": "Chicken Biryani", "quantity": 1, "customization_notes": null}}]
  Remove:  [{{"action": "remove", "menu_item_name": "Garlic Naan", "quantity": 1, "customization_notes": null}}]
  Modify:  [{{"action": "modify", "menu_item_name": "Chicken Biryani", "quantity": 2, "customization_notes": null}}]
  Replace: [{{"action": "replace", "old_item_name": "Mango Lassi", "new_item_name": "Sweet Lassi", "quantity": 1, "customization_notes": null}}]
  Confirm: [{{"action": "confirm", "menu_item_name": null, "quantity": 1, "customization_notes": null}}]
  Cancel:  [{{"action": "cancel", "menu_item_name": null, "quantity": 1, "customization_notes": null}}]
"""




# ─── Memory Summarization Prompt ─────────────────────────────────────────────

MEMORY_SUMMARIZE_PROMPT = """Summarize the key facts about this customer from their conversation.
Focus on: food preferences, dislikes, dietary restrictions, ordering patterns, and any complaints.
Keep it to 2-3 concise sentences.

Conversation:
{conversation}

Summary:"""


# ─── Preference Extraction Prompt ────────────────────────────────────────────

PREFERENCE_EXTRACTION_PROMPT = """Extract customer food preferences from this conversation summary.
Return JSON with these optional fields:
- "spice_level": "mild" | "medium" | "hot" | "extra-hot"
- "allergies": comma-separated list
- "dietary_preferences": comma-separated (vegetarian, vegan, halal, etc.)
- "favorite_dishes": comma-separated dish names
- "disliked_dishes": comma-separated dish names

Summary: "{summary}"

Return ONLY valid JSON. If nothing can be extracted, return {{}}.
"""
