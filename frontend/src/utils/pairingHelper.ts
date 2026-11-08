import type { MenuItem, OrderItem } from '../services/api';

const CANONICAL_PAIRINGS: Record<string, string[]> = {
  'paneer butter masala': ['Butter Naan', 'Garlic Naan'],
  'butter chicken': ['Butter Naan', 'Jeera Rice'],
  'chicken biryani': ['Raita'],
  'mutton biryani': ['Raita'],
  'veg biryani': ['Raita'],
  'egg biryani': ['Raita'],
  'veg fried rice': ['Gobi Manchurian'],
  'fried rice': ['Gobi Manchurian'],
};

/**
 * Given a list of items currently in the cart or a selected item,
 * extract and resolve complementary pairings from their canonical `pairs_with` metadata
 * or known food pairings.
 * 
 * Rules:
 * - Suggests 1–2 complementary sides.
 * - Only returns items that actually exist in the menu and are available.
 * - Excludes items that are already present in the cart.
 * - Deduplicates suggestions.
 * - Never auto-adds to the cart.
 */
export function getComplementaryPairings(
  cartItems: OrderItem[],
  menuItems: MenuItem[],
  selectedItem?: MenuItem | null,
  limit: number = 2
): MenuItem[] {
  if (!menuItems || menuItems.length === 0) return [];

  const cartItemNames = new Set(cartItems.map(ci => ci.menu_item_name.toLowerCase().trim()));
  const menuByName = new Map<string, MenuItem>();

  for (const item of menuItems) {
    if (!item.is_available) continue;
    menuByName.set(item.name.toLowerCase().trim(), item);
    // Also index without parentheses e.g. "Idli" for "Idli (3 pcs)"
    const clean = item.name.toLowerCase().replace(/\s*\([^)]*\)/g, '').trim();
    if (!menuByName.has(clean)) {
      menuByName.set(clean, item);
    }
  }

  const suggestedPairs = new Set<MenuItem>();

  const addPairCandidate = (candidateName: string) => {
    if (suggestedPairs.size >= limit) return;
    const match = menuByName.get(candidateName.toLowerCase().trim());
    if (match && !cartItemNames.has(match.name.toLowerCase().trim()) && match.is_available) {
      suggestedPairs.add(match);
    }
  };

  // Helper to extract pair candidates from item
  const processItem = (itemName: string, pairsWith?: string) => {
    const cleanName = itemName.toLowerCase().replace(/\s*\([^)]*\)/g, '').trim();
    // 1. Check canonical hard mappings
    const canonical = CANONICAL_PAIRINGS[cleanName] || (cleanName.includes('biryani') ? ['Raita'] : null) || (cleanName.includes('fried rice') ? ['Gobi Manchurian'] : null);
    if (canonical) {
      for (const p of canonical) addPairCandidate(p);
    }
    // 2. Check pairs_with metadata
    if (pairsWith) {
      const rawPairs = pairsWith.split(',').map(s => s.trim());
      for (const p of rawPairs) addPairCandidate(p);
    }
  };

  // 1. Check selected item first (if user clicked on a dish)
  if (selectedItem) {
    processItem(selectedItem.name, selectedItem.pairs_with);
  }

  // 2. Check cart items (most recent first)
  for (let i = cartItems.length - 1; i >= 0; i--) {
    if (suggestedPairs.size >= limit) break;
    const cartItem = cartItems[i];
    const menuItem = menuByName.get(cartItem.menu_item_name.toLowerCase().trim());
    processItem(cartItem.menu_item_name, menuItem?.pairs_with);
  }

  return Array.from(suggestedPairs).slice(0, limit);
}
