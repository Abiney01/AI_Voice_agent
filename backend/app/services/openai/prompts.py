"""
System prompts and prompt builders for the AI concierge.
"""

from typing import Any, Dict, List, Optional


# ─── System Prompt ────────────────────────────────────────────────────────────
# ROOT CAUSE FIX: The previous prompt contained a hard REFUSE instruction that
# told the LLM to reply with the generic "I'm Aria..." fallback for ANY message
# that seemed off-topic. Because GPT-4o-mini is aggressive about following that
# instruction, valid questions like "what's popular?" or "do you have anything
# spicy?" were being caught by the LLM's own interpretation of "off-domain" —
# even though the guardrail layer already handles true off-domain requests.
#
# Fix: Remove the hard REFUSE instruction entirely. The domain_guard.py regex
# layer handles real abuse before this prompt is ever reached. Inside the LLM,
# Aria should focus on being helpful, not on policing her own input.

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

RECOMMENDATION GUIDANCE:
- When asked for recommendations, pick 2-3 dishes from the menu and briefly say why they're great
- When asked about specials or what's popular, mention top items confidently
- When asked about vegetarian options, guide them to the vegetarian dishes
- When asked about spice level, describe the dishes on the menu that match their preference
- Always root recommendations in the actual menu provided to you

CONVERSATION STYLE:
- DO NOT start every reply with "I'm Diaa" — only introduce yourself at the very beginning
- DO NOT give long paragraphs — speak in short, natural sentences
- DO NOT repeat the same phrase twice in one response
- DO sound like a real person having a real conversation
- DO ask a follow-up question when it helps move the conversation forward

RULES:
- Only recommend dishes that are on the provided menu
- Never make up items, prices, or ingredients
- Confirm items when adding them to an order
- Spoken format only — no bullet points, no markdown, no special characters
"""


# ─── Conversation Messages Builder (OpenAI native format) ────────────────────

def build_conversation_messages(
    customer_name: Optional[str],
    preferences: Optional[Dict[str, Any]],
    menu_summary: str,
    current_order: Optional[Dict[str, Any]],
    recent_memories: List[str],
    conversation_history: List[Dict[str, str]],
    user_message: str,
) -> List[Dict[str, str]]:
    """
    Build a proper OpenAI messages array for multi-turn conversation.

    Structure:
        [system: identity+rules, system: session context, ...history..., user: message]

    Using native role assignments instead of cramming everything into one giant
    user message — which is what gpt-4o-mini (and all OpenAI models) expect.
    """

    # ── Build context block ───────────────────────────────────────────────────
    context_lines: List[str] = [f"CUSTOMER NAME: {customer_name or 'Unknown'}"]

    if preferences:
        pref_lines = []
        if preferences.get("spice_level"):
            pref_lines.append(f"- Spice preference: {preferences['spice_level']}")
        if preferences.get("dietary_preferences"):
            pref_lines.append(f"- Dietary: {preferences['dietary_preferences']}")
        if preferences.get("allergies"):
            pref_lines.append(f"- Allergies: {preferences['allergies']}")
        if preferences.get("favorite_dishes"):
            pref_lines.append(f"- Favorites: {preferences['favorite_dishes']}")
        if preferences.get("disliked_dishes"):
            pref_lines.append(f"- Dislikes: {preferences['disliked_dishes']}")
        if pref_lines:
            context_lines.append("CUSTOMER PREFERENCES:\n" + "\n".join(pref_lines))

    if recent_memories:
        context_lines.append(
            "CUSTOMER HISTORY (use this to personalise your response):\n"
            + "\n".join(f"- {m}" for m in recent_memories)
        )

    context_lines.append(f"\nMENU (only recommend items from this list):\n{menu_summary}")

    if current_order and current_order.get("items"):
        order_lines = [f"ORDER #{current_order['id']} (Status: {current_order['status']})"]
        for item in current_order["items"]:
            order_lines.append(
                f"  - {item['quantity']}x {item['menu_item_name']} @ \u20b9{item['unit_price']:.2f}"
                + (f" [{item['customization_notes']}]" if item.get("customization_notes") else "")
            )
        order_lines.append(f"  Total: \u20b9{current_order['total_amount']:.2f}")
        context_lines.append("\nCURRENT ORDER:\n" + "\n".join(order_lines))
    else:
        context_lines.append("\nCURRENT ORDER: Empty (nothing ordered yet)")

    context_block = "\n".join(context_lines)

    # ── Assemble messages array ───────────────────────────────────────────────
    messages: List[Dict[str, str]] = [
        # 1. Core identity & behaviour rules
        {"role": "system", "content": SYSTEM_PROMPT},
        # 2. Live session context (customer, menu, order) as a second system message
        {"role": "system", "content": f"--- SESSION CONTEXT ---\n{context_block}\n--- END CONTEXT ---"},
    ]

    # 3. Conversation history using native user/assistant roles (last 10 turns)
    for msg in conversation_history[-10:]:
        role = "user" if msg["role"] == "user" else "assistant"
        content = msg.get("content", "").replace("\r", " ")
        if content:
            messages.append({"role": role, "content": content})

    # 4. Current user message (sanitise CR to avoid role-injection)
    safe_user_message = user_message.replace("\r", " ")
    messages.append({"role": "user", "content": safe_user_message})

    return messages


ORDER_EXTRACTION_PROMPT = """You are an order extraction assistant for a restaurant. Extract order actions from the customer message.

Current order (items already in the cart):
{current_order}

Last assistant message (what you said in the previous turn, use this to resolve relative references like "add that" or "add the suggested items"):
{last_assistant_message}

Return a JSON array of actions. Each action has:
- "action": one of "add", "remove", "modify", "replace", "confirm", "cancel", "none"
- "menu_item_name": the item name as the customer mentioned it (for add/remove/modify)
- "quantity": number meaning:
    - For "add": the amount to ADD (delta). "Add one more Coke" → quantity 1
    - For "modify": the NEW absolute quantity. "Make it 2 biryanis" → quantity 2
    - For "replace": quantity of the new item (default 1)
- "customization_notes": any special instructions (null if none)
- "old_item_name": (only for "replace") the item being replaced
- "new_item_name": (only for "replace") the item to replace it with

Customer message:
\"\"\"{message}\"\"\"

Return ONLY a valid JSON array, no explanation.
Examples:
  Add:     [{{"action": "add", "menu_item_name": "Chicken Biryani", "quantity": 1, "customization_notes": null}}]
  Remove:  [{{"action": "remove", "menu_item_name": "Coke", "quantity": 1, "customization_notes": null}}]
  Modify:  [{{"action": "modify", "menu_item_name": "Chicken Biryani", "quantity": 2, "customization_notes": null}}]
  Replace: [{{"action": "replace", "old_item_name": "Coke", "new_item_name": "Lassi", "quantity": 1, "customization_notes": null}}]
  Confirm: [{{"action": "confirm", "menu_item_name": null, "quantity": 1, "customization_notes": null}}]
  Cancel:  [{{"action": "cancel", "menu_item_name": null, "quantity": 1, "customization_notes": null}}]

If no order action is detected, return: [{{"action": "none"}}]
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
