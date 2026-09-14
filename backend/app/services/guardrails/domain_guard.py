"""
Domain guardrail module for the AI Voice Restaurant Concierge.

Performs fast, code-level filtering of user messages before they reach Gemini:
  1. Input sanitization (length, control characters)
  2. Prompt injection detection
  3. Off-domain request detection
  4. Restaurant fast-pass for obvious food queries
"""

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 500

# ─── Prompt Injection Patterns ────────────────────────────────────────────────
# Hard-block these — they are attempts to manipulate the AI's identity/instructions.

_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|your|above|any)\s+instructions?",
    r"you\s+are\s+now\s+(a|an)",
    r"forget\s+(you\s+are|that\s+you)",
    r"new\s+(instructions?|rules?|persona)\s*:",
    r"\bsystem\s+prompt\b",
    r"\[system\]",
    r"###\s*system",
    r"act\s+as\s+(if|a|an)\b",
    r"pretend\s+(you\s+are|to\s+be)",
    r"roleplay\s+as",
    r"disregard\s+(all|previous|your)\s+(instructions?|rules?)",
    r"override\s+(your|all)\s+(instructions?|rules?|guidelines?)",
    r"\bjailbreak\b",
    r"\bdan\s+mode\b",
    r"\bdo\s+anything\s+now\b",
    r"prompt\s+injection",
    r"from\s+now\s+on\s+(you\s+are|you\s+will)",
    r"your\s+new\s+(role|identity|instructions?)",
    r"you\s+have\s+no\s+restrictions?",
    r"enable\s+(developer|dev|god)\s+mode",
    r"bypass\s+(your|all|these)\s+(rules?|restrictions?|filters?)",
]

# ─── Off-Domain Patterns ───────────────────────────────────────────────────────
# Detect non-restaurant topics. Only checked if message doesn't fast-pass as food.

_OFF_DOMAIN_PATTERNS = [
    # Coding / software
    r"\b(write|create|make|build|generate)\s+(a\s+)?(python|javascript|typescript|java|c\+\+|code|program|function|script|algorithm|class|method)\b",
    r"\b(debug|compile|runtime\s+error|stack\s+trace|syntax\s+error|github|repository|pull\s+request|dockerfile)\b",
    r"\bhow\s+to\s+(code|program|install|setup|configure|deploy)\b",
    # Math
    r"\b(calculate|solve|compute|evaluate)\s+(the\s+)?(equation|integral|derivative|limit|sum|product)\b",
    r"\b(algebra|calculus|geometry|trigonometry|statistics|probability)\b",
    r"\bfactorial\s+of\b",
    r"\bsolve\s+for\s+[a-z]\b",
    r"\bwhat\s+is\s+\d+\s*[\+\-\*\/\^]\s*\d+\b",
    # Essay / writing
    r"\b(write|compose|draft|create)\s+(me\s+)?(a\s+|an\s+)?(essay|poem|story|article|letter|email|report|thesis|cover\s+letter|blog\s+post|speech)\b",
    # General knowledge
    r"\bwho\s+(is|was|invented|discovered|founded)\b",
    r"\bwhat\s+is\s+the\s+(capital|population|currency|president|prime\s+minister)\b",
    r"\bhistory\s+of\b",
    r"\bexplain\s+(quantum|relativity|evolution|democracy|capitalism)\b",
    r"\btell\s+me\s+(about\s+the\s+history|the\s+history\s+of)\b",
    # Medical
    r"\b(diagnose|symptoms|prescription|disease|treatment|therapy|medication|side\s+effects)\b",
    r"\bam\s+i\s+(sick|pregnant|diabetic|allergic)\b",
    # Financial
    r"\b(stock\s+market|invest(ing|ment)?|crypto|bitcoin|ethereum|trading|forex|mutual\s+fund)\b",
    # Translation requests (not menu-related)
    r"\btranslate\s+(this\s+)?(sentence|text|word|paragraph)\b",
]

# ─── Restaurant Fast-Pass Patterns ────────────────────────────────────────────
# If any of these match, skip off-domain check entirely.

_RESTAURANT_FAST_PASS = [
    # Core food ordering verbs
    r"\b(order|add|remove|cancel|confirm|checkout)\b",
    # Food-related nouns
    r"\b(menu|food|eat|hungry|thirsty|dish|meal|drink|beverage|dessert|starter|main\s+course|appetizer|entree|side)\b",
    # Common menu items
    r"\b(biryani|pizza|burger|curry|rice|chicken|mutton|paneer|dosa|idli|naan|roti|dal|samosa|tikka|kebab|soup|salad|pasta|sandwich|lassi|mango|gulab|kulfi|raita|chutney|paratha|puri|bhaji|korma|masala|tandoori|vindaloo|saag|palak|malai|butter|chole|bhature|vada)\b",
    # Dietary / preference
    r"\b(spicy|spice|mild|vegetarian|vegan|halal|kosher|gluten.?free|allergy|allergen|dairy.?free|non.?veg|eggless|jain)\b",
    # Price / cart
    r"\b(price|cost|how\s+much|total|bill|cart|basket|rupee|rs\.|inr)\b",
    # Recommendations — this was missing several key phrases
    r"\b(recommend|recommendation|suggest|suggestion|popular|special|specials|today.?s\s+special|offer|bestseller|favourite|favorite|must.?try|house\s+special|chef.?s\s+(special|choice|recommend))\b",
    # Discovery / question phrases that are always restaurant-related
    r"\b(what.?s\s+(good|great|nice|best|hot|new|available|on\s+the\s+menu)|what\s+do\s+you\s+(have|serve|offer|recommend)|do\s+you\s+(have|serve|offer)|what\s+would\s+you\s+(suggest|recommend)|what.?s\s+your\s+(best|favourite|favorite|top))\b",
    r"\b(anything|something)\s+(spicy|vegetarian|vegan|light|heavy|sweet|good|nice|popular|special)\b",
    # Conversational fillers — always pass these through
    r"\b(yes|no|okay|ok|sure|please|thanks|thank\s+you|hello|hi|hey|bye|goodbye|sounds\s+good|perfect|great|alright|go\s+ahead)\b",
    # Open-ended 'what' questions are almost always restaurant-related in this context
    r"^(what|what.?s|show\s+me|i\s+want|i.?d\s+like|can\s+i\s+(have|get|see)|do\s+you\s+have|how\s+(many|much)|which)",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
_OFF_DOMAIN_RE = [re.compile(p, re.IGNORECASE) for p in _OFF_DOMAIN_PATTERNS]
_FAST_PASS_RE = [re.compile(p, re.IGNORECASE) for p in _RESTAURANT_FAST_PASS]

_REJECTION_REPLY = (
    "I'm Aria, your restaurant assistant! I can only help you with food orders "
    "and our menu. What would you like to eat today? 🍽️"
)
_INJECTION_REPLY = (
    "I'm Aria, your restaurant assistant! I'm here to help you order delicious food. "
    "What can I get for you today? 🍽️"
)


def check_guardrails(message: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Validate and sanitize a user message.

    Returns:
        (clean_message, None)        — message passed all checks; use clean_message
        (None, rejection_reply)      — message rejected; return rejection_reply to user
    """
    # ── Length check ─────────────────────────────────────────────────────────
    if len(message) > MAX_MESSAGE_LENGTH:
        return None, "I'm Aria, your restaurant assistant! Please keep your message a bit shorter and I'll be happy to help. 🍽️"

    # ── Strip control characters ──────────────────────────────────────────────
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", message).strip()
    if not clean:
        return None, "I didn't catch that — could you repeat your order?"

    lower = clean.lower()

    # ── Prompt injection check — hard reject ──────────────────────────────────
    for pattern in _INJECTION_RE:
        if pattern.search(lower):
            logger.warning("Prompt injection attempt blocked: %.100s", clean)
            return None, _INJECTION_REPLY

    # ── Restaurant fast-pass — skip off-domain check ──────────────────────────
    for pattern in _FAST_PASS_RE:
        if pattern.search(lower):
            return clean, None

    # ── Off-domain check ──────────────────────────────────────────────────────
    for pattern in _OFF_DOMAIN_RE:
        if pattern.search(lower):
            logger.info("Off-domain request blocked: %.100s", clean)
            return None, _REJECTION_REPLY

    # ── Default pass — short/ambiguous messages allowed through ───────────────
    return clean, None
