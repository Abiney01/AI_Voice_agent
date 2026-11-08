"""
Allergy and Disliked Food Validation Service.

Enforces strict dietary and safety validation before any cart mutations:
1. Validates dish ingredients against known customer allergies.
2. Validates dish ingredients against customer disliked foods.
3. Automatically scans and removes conflicting items already in the cart when a customer discloses an allergy or dislike.
4. Detects allergies and dislikes dynamically from conversational turns.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Ingredient and allergen synonyms and cross-references
ALLERGEN_SYNONYMS: Dict[str, Set[str]] = {
    "peanut": {"peanut", "peanuts", "groundnut", "groundnuts", "peanut butter", "peanut sauce"},
    "nut": {"nut", "nuts", "cashew", "cashews", "almond", "almonds", "walnut", "walnuts", "pistachio", "pistachios", "hazelnut", "peanut", "peanuts"},
    "tree nut": {"nut", "nuts", "cashew", "cashews", "almond", "almonds", "walnut", "walnuts", "pistachio", "hazelnut"},
    "shellfish": {"shellfish", "prawn", "prawns", "shrimp", "shrimps", "crab", "crabs", "lobster", "lobsters", "seafood"},
    "prawn": {"prawn", "prawns", "shrimp", "shrimps", "shellfish", "seafood"},
    "shrimp": {"prawn", "prawns", "shrimp", "shrimps", "shellfish", "seafood"},
    "seafood": {"seafood", "fish", "prawn", "prawns", "shrimp", "shrimps", "shellfish", "crab", "lobster"},
    "fish": {"fish", "salmon", "tuna", "cod", "seafood"},
    "dairy": {"dairy", "milk", "cheese", "paneer", "butter", "cream", "ghee", "curd", "yogurt", "cheddar", "mozzarella"},
    "milk": {"dairy", "milk", "cheese", "paneer", "butter", "cream", "ghee", "curd", "yogurt"},
    "cheese": {"cheese", "paneer", "cheddar", "mozzarella", "dairy"},
    "paneer": {"paneer", "cheese", "dairy"},
    "gluten": {"gluten", "wheat", "flour", "bread", "naan", "roti", "paratha", "pasta", "pizza", "toast", "waffle", "waffles", "pancake", "pancakes", "bun"},
    "wheat": {"gluten", "wheat", "flour", "bread", "naan", "roti", "paratha"},
    "egg": {"egg", "eggs", "omelette", "mayo", "mayonnaise"},
    "soy": {"soy", "soya", "tofu", "soy sauce", "edamame"},
    "mushroom": {"mushroom", "mushrooms"},
    "mustard": {"mustard", "mustard seeds"},
    "sesame": {"sesame", "sesame seeds", "tahini"},
}

_ALLERGY_PATTERNS = [
    re.compile(r"\b(?:i\s+am|i'm|im|i\s+have|i\s+got)\s+(?:an?\s+)?allergic\s+to\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\b(?:i\s+have|i\s+got)\s+(?:an?\s+)?([a-zA-Z\s]+?)\s+allergy\b", re.IGNORECASE),
    re.compile(r"\ballergy\s+to\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\b(?:allergic\s+to)\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\bactually,?\s+(?:i\s+am|i'm|im)\s+allergic\s+to\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\bno\s+([a-zA-Z\s]+?),?\s+(?:i\s+am|i'm|im)\s+allergic\b", re.IGNORECASE),
    re.compile(r"\b(?:can'?t\s+have|cannot\s+have)\s+([a-zA-Z\s]+?),?\s+(?:i\s+am|i'm|im)\s+allergic\b", re.IGNORECASE),
]

_DISLIKE_PATTERNS = [
    re.compile(r"\b(?:i\s+don'?t\s+like|i\s+dislike|i\s+hate|i\s+can'?t\s+stand)\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\b(?:i\s+don'?t\s+eat|i\s+avoid|don'?t\s+want\s+any)\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
    re.compile(r"\bno\s+([a-zA-Z\s]+?)\s+please,?\s+i\s+don'?t\s+like\b", re.IGNORECASE),
    re.compile(r"\bnot\s+a\s+fan\s+of\s+([a-zA-Z\s,]+?)(?:\.|\band\b|$)", re.IGNORECASE),
]

_STOPWORDS = {
    "food", "foods", "dish", "dishes", "item", "items", "any", "the", "some", "eating",
    "thing", "things", "stuff", "meals", "meal", "with", "containing", "in", "it",
}


def _clean_token(token: str) -> str:
    """Normalize extracted ingredient/allergen token."""
    clean = re.sub(r"[^a-zA-Z\s]", " ", token).strip().lower()
    words = [w for w in clean.split() if w not in _STOPWORDS]
    result = " ".join(words)
    # Basic singularization for common words
    if result.endswith("s") and len(result) > 3 and not result.endswith("ss"):
        if result == "peanuts":
            return "peanut"
        if result == "mushrooms":
            return "mushroom"
        if result == "prawns":
            return "prawn"
        if result == "shrimps":
            return "shrimp"
        if result == "nuts":
            return "nut"
        if result == "eggs":
            return "egg"
        if result == "onions":
            return "onion"
        if result.endswith("es") and len(result) > 4:
            if result.endswith("tomatoes"):
                return "tomato"
            if result.endswith("potatoes"):
                return "potato"
        return result[:-1]
    return result


def extract_restrictions_from_text(text: str) -> Tuple[List[str], List[str]]:
    """
    Extract allergens and disliked foods from a text message.
    Returns (allergies_list, dislikes_list).
    """
    if not text:
        return [], []

    allergies: Set[str] = set()
    dislikes: Set[str] = set()

    for pattern in _ALLERGY_PATTERNS:
        matches = pattern.findall(text)
        for m in matches:
            if isinstance(m, tuple):
                for part in m:
                    for sub in re.split(r"[,;]+|\band\b", part):
                        cleaned = _clean_token(sub)
                        if cleaned and len(cleaned) >= 3:
                            allergies.add(cleaned)
            else:
                for sub in re.split(r"[,;]+|\band\b", m):
                    cleaned = _clean_token(sub)
                    if cleaned and len(cleaned) >= 3:
                        allergies.add(cleaned)

    for pattern in _DISLIKE_PATTERNS:
        matches = pattern.findall(text)
        for m in matches:
            if isinstance(m, tuple):
                for part in m:
                    for sub in re.split(r"[,;]+|\band\b", part):
                        cleaned = _clean_token(sub)
                        if cleaned and len(cleaned) >= 3:
                            dislikes.add(cleaned)
            else:
                for sub in re.split(r"[,;]+|\band\b", m):
                    cleaned = _clean_token(sub)
                    if cleaned and len(cleaned) >= 3:
                        dislikes.add(cleaned)

    return sorted(list(allergies)), sorted(list(dislikes))


def get_synonyms_for(term: str) -> Set[str]:
    """Retrieve full synonym set for a given allergen/ingredient term."""
    term_lower = term.lower().strip()
    synonyms = {term_lower}
    # Direct match in synonym dictionary
    if term_lower in ALLERGEN_SYNONYMS:
        synonyms.update(ALLERGEN_SYNONYMS[term_lower])
    # Check if term matches any synonym group
    for key, syn_set in ALLERGEN_SYNONYMS.items():
        if term_lower in syn_set or key in term_lower:
            synonyms.update(syn_set)
    # Singular/plural variants
    if term_lower.endswith("s"):
        synonyms.add(term_lower[:-1])
    else:
        synonyms.add(term_lower + "s")
    return synonyms


def check_dish_conflict(
    menu_item: Any,
    allergies: List[str],
    dislikes: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Validate a dish against customer allergies and dislikes.
    
    Returns:
        (conflict_type, conflict_ingredient)
        conflict_type: "allergy" | "dislike" | "uncertain_ingredient" | None
        conflict_ingredient: the specific offending ingredient/allergen or None
    """
    if not menu_item:
        return None, None

    item_name = getattr(menu_item, "name", "").lower()
    item_desc = (getattr(menu_item, "description", "") or "").lower()
    item_allergens = (getattr(menu_item, "allergens", "") or "").lower()

    dish_text = f"{item_name} {item_desc} {item_allergens}"

    # 1. Check Allergies (STRICT RESTRICTION - HIGHEST PRIORITY)
    for allergy in allergies:
        if not allergy or len(allergy.strip()) < 2:
            continue
        synonyms = get_synonyms_for(allergy)
        for syn in synonyms:
            pattern = r"\b" + re.escape(syn) + r"\b"
            if re.search(pattern, dish_text, re.IGNORECASE):
                logger.warning(
                    "[ALLERGY-CHECK] Dish '%s' violates allergy '%s' (matched '%s')",
                    getattr(menu_item, "name", ""), allergy, syn
                )
                return "allergy", allergy

    # 2. Check Disliked Foods
    for dislike in dislikes:
        if not dislike or len(dislike.strip()) < 2:
            continue
        synonyms = get_synonyms_for(dislike)
        for syn in synonyms:
            pattern = r"\b" + re.escape(syn) + r"\b"
            if re.search(pattern, dish_text, re.IGNORECASE):
                logger.info(
                    "[DISLIKE-CHECK] Dish '%s' violates dislike '%s' (matched '%s')",
                    getattr(menu_item, "name", ""), dislike, syn
                )
                return "dislike", dislike

    # 3. Check for Uncertain Ingredient when allergy is present and allergen metadata is empty
    # If customer is allergic to common staples (gluten, dairy, nuts) and allergens field is entirely missing,
    # flag for kitchen clarification rather than assuming safety.
    critical_staples = {"peanut", "nut", "shellfish", "prawn", "dairy", "gluten", "egg"}
    has_critical_allergy = any(a in critical_staples for a in allergies)
    if has_critical_allergy and not item_allergens and not item_desc:
        return "uncertain_ingredient", "ingredient details unavailable"

    return None, None


async def scan_and_remove_cart_conflicts(
    order: Any,
    allergies: List[str],
    dislikes: List[str],
    order_svc: Any,
) -> List[Dict[str, Any]]:
    """
    Check all items currently in the cart. If any item conflicts with newly
    disclosed or stored allergies/dislikes, immediately remove it from the database cart.
    
    Returns list of removed items:
        [{"item_id": int, "item_name": str, "type": "allergy"|"dislike", "ingredient": str}]
    """
    if not order or not getattr(order, "items", None):
        return []

    removed_records = []
    # Make a copy of items to iterate safely
    cart_items = list(order.items)

    for item in cart_items:
        menu_item = item.menu_item
        if not menu_item:
            continue
        conflict_type, conflict_ingredient = check_dish_conflict(
            menu_item=menu_item,
            allergies=allergies,
            dislikes=dislikes,
        )
        if conflict_type in ("allergy", "dislike"):
            try:
                await order_svc.remove_item(order.id, item.id)
                logger.info(
                    "[CART-ALLERGY-AUTO-REMOVE] Removed '%s' from order #%s due to %s on '%s'",
                    menu_item.name, order.id, conflict_type, conflict_ingredient
                )
                removed_records.append({
                    "item_id": item.id,
                    "item_name": menu_item.name,
                    "type": conflict_type,
                    "ingredient": conflict_ingredient,
                })
            except Exception as e:
                logger.error(
                    "[CART-ALLERGY-AUTO-REMOVE] Failed to remove conflicting item '%s': %s",
                    menu_item.name, e, exc_info=True
                )

    return removed_records
