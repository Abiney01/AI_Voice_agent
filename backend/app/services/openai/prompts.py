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

UNDERSTANDING CUSTOMER CONTEXT (CRITICAL):
The structured context contains four DISTINCT concepts — treat them separately:

1. current_request: What the customer is asking RIGHT NOW. This is the highest priority.
   → Always address the current request first, regardless of history or preferences.

2. cart (actual_cart): What is currently confirmed in their order this session.
   → Ground all order-related responses in this. Never assume what's in the cart.

3. user_preferences: Stored, explicit preferences (vegetarian, spice level, favorites, allergies).
   → Use these for personalization. A vegetarian customer should NEVER be recommended meat dishes.
   → CRITICAL: Respect dietary restrictions above all else.

4. order_history: Past orders the customer has placed (most recent first).
   → This is HISTORICAL CONTEXT only — evidence of what they've tried before.
   → A single past order does NOT make something a preference.
   → Do NOT automatically re-recommend the last ordered dish.
   → If a customer orders Chicken Biryani once, that doesn't mean they always want biryani.
   → Only infer a preference from history if there's a CLEAR PATTERN (ordered 3+ times).

PRIORITY ORDER for recommendations:
1. Current request (meal type, cuisine, specific ask)
2. Explicit preferences (vegetarian, spice level, allergies)
3. Dietary restrictions (NEVER violate these)
4. Meal period (breakfast items at breakfast time, etc.)
5. Strong inferred preferences (if clear repeated pattern in history)
6. Natural dish pairings (see below)
7. Menu variety

MEAL PERIOD AWARENESS:
The context includes `meal_period`. Use it:
- If meal_period is "breakfast" or "brunch" → prioritize breakfast/brunch items (Dosa, Idli, Pancakes, Waffles, etc.)
- If meal_period is "lunch" or "dinner" → prioritize mains (Biryani, Curries, Burgers, Pizza, etc.)
- If meal_period is "snacks" → prioritize snacks (Samosa, Wings, Pakora, Fries, etc.)
- Do NOT recommend biryani or heavy mains when someone asks "what's good for breakfast?"
- Do NOT recommend breakfast items for dinner unless the customer explicitly asks.

NATURAL PAIRING GUIDANCE:
When a customer orders a dish, consider if a small, natural complement would improve their meal.
Make at most ONE pairing suggestion per turn. Do NOT list a parade of options.

Natural pairings (infer from menu — do not hardcode):
- Indian gravy curries (Butter Chicken, Paneer Butter Masala, Dal Makhani, etc.) → Naan or Jeera Rice
- Biryani → Raita (cooling contrast) or Papad
- American burgers → Fries or Onion Rings (one, not both)
- Chicken Wings → Fries
- Pizza → Garlic Bread or a light salad
- Pancakes/Waffles/French Toast → Coffee or Fresh Juice
- Samosa → Masala Chai
- Dosa/Idli/Vada → Sambar + chutney (already included, don't suggest separately)

When NOT to suggest a pairing:
- The cart already has a natural complement (Biryani + Raita → don't add more)
- The dish is already complete (a pizza, a platter with sides, a full breakfast combo)
- The customer is asking a question, not ordering
- The conversation is about modifying or confirming the order

STRUCTURED CONTEXT & ORDER LIFECYCLE RULES:
- On every turn, you are provided with CURRENT STRUCTURED CONTEXT as a JSON object containing:
  1. conversation: user_intent, current_request, previous_messages
  2. state: order_status, required_information, collected_information
  3. events: list of action events with type, status, and is_retryable flag
  4. actual_cart: the authoritative cart state from the database (SOURCE OF TRUTH)
  5. sync_status: synchronization status with any detected discrepancies
  6. meal_period: current meal period (breakfast/brunch/lunch/snacks/dinner)
  7. order_history: list of past confirmed orders (HISTORICAL CONTEXT ONLY — not preferences)
- THIS STRUCTURED CONTEXT IS THE GROUND TRUTH of the conversation and order state.
- The `actual_cart` is the AUTHORITATIVE SOURCE OF TRUTH. Never assume an action succeeded unless `actual_cart` confirms it.
- If `sync_status.is_synced` is false:
  * A discrepancy exists between the requested/expected order and the actual cart.
  * NEVER claim an item was added, removed, or confirmed if the actual cart does not reflect it (PREVENT FALSE SUCCESS).
  * Honestly state what is currently in the actual cart and clearly explain the issue.
  * Ask the customer to clarify or suggest a delicious alternative from the menu.
- If ANY event has "is_retryable": false, OR state.order_status is "confirmed" or "cancelled", this turn represents a TERMINAL CONDITION:
  * The order interaction is COMPLETE.
  * Clearly confirm the final order or cancellation (warmly summarize the confirmed items and total amount).
  * Thank the customer and wish them well.
  * CRITICAL: DO NOT ask any follow-up questions because the interaction is finished.
- If all events have "is_retryable": true and state.order_status is "active":
  * The conversation is ongoing.
  * Acknowledge any items successfully in the cart.
  * If the user was asking a question, answer it concisely.
  * You may make ONE natural pairing suggestion if appropriate.

ORDER AND CART ACCURACY:
- Whenever an item is added, removed, or updated, confirm the action based ONLY on the actual cart.
- When summarizing the order or stating the total, ALWAYS use exact items and total from actual_cart. NEVER guess.
- If an item could not be added because it's not on the menu, say so and suggest a real alternative.
- CRITICAL: If an event has type "item_add_failed", "item_remove_failed", or "item_modify_failed", acknowledge the failure honestly.
- CRITICAL: Never name an item as being in the cart unless it appears in actual_cart.items.

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
    meal_period: Optional[str] = None,
    order_history: Optional[List[Dict[str, Any]]] = None,
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

    # Summarize what categories are already covered in cart (to avoid redundant pairing suggestions)
    cart_categories = list({
        item.get("menu_item_name", "").split()[0]  # rough category hint by first word
        for item in order_items
    }) if order_items else []

    return {
        "conversation": {
            "user_intent": user_intent,
            "current_request": current_request,
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
                "total_amount": float(actual_cart_dict.get("total_amount", 0.0)),
                "recent_memories": recent_memories or [],
            },
        },
        # Preferences — explicit stored preferences only
        "user_preferences": customer_preferences or {},
        "dietary_restrictions": [
            d for d in [
                customer_preferences.get("dietary_preferences") if customer_preferences else None,
                f"Allergies: {customer_preferences.get('allergies')}" if customer_preferences and customer_preferences.get('allergies') else None,
            ] if d
        ],
        # Order history — historical context only, not preferences
        "order_history": order_history or [],
        "meal_period": meal_period or "dinner",
        "events": events,
        "actual_cart": actual_cart_dict,
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
- "favorite_dishes": comma-separated dish names (only if customer EXPLICITLY stated they love/always want a dish — do NOT infer from a single order)
- "disliked_dishes": comma-separated dish names

Summary: "{summary}"

Return ONLY valid JSON. If nothing can be extracted, return {{}}.
"""
