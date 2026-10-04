import type { MenuItem, OrderItem } from '../services/api';

/**
 * Given a list of items currently in the cart or a selected item,
 * extract and resolve complementary pairings from their canonical `pairs_with` metadata.
 * 
 * Rules:
 * - Only returns items that actually exist in the menu.
 * - Excludes items that are already present in the cart.
 * - Deduplicates suggestions.
 * - Limits to 2-3 most relevant suggestions.
 */
export function getComplementaryPairings(
  cartItems: OrderItem[],
  menuItems: MenuItem[],
  selectedItem?: MenuItem | null,
  limit: number = 3
): MenuItem[] {
  if (!menuItems || menuItems.length === 0) return [];

  const cartItemNames = new Set(cartItems.map(ci => ci.menu_item_name.toLowerCase().trim()));
  const menuByName = new Map<string, MenuItem>();

  for (const item of menuItems) {
    menuByName.set(item.name.toLowerCase().trim(), item);
    // Also index without parentheses e.g. "Idli" for "Idli (3 pcs)"
    const clean = item.name.toLowerCase().replace(/\s*\([^)]*\)/g, '').trim();
    if (!menuByName.has(clean)) {
      menuByName.set(clean, item);
    }
  }

  const suggestedPairs = new Set<MenuItem>();

  // 1. Check selected item first (if user tapped on a dish)
  if (selectedItem && selectedItem.pairs_with) {
    const rawPairs = selectedItem.pairs_with.split(',').map(s => s.trim());
    for (const pairName of rawPairs) {
      const match = menuByName.get(pairName.toLowerCase());
      if (match && !cartItemNames.has(match.name.toLowerCase())) {
        suggestedPairs.add(match);
      }
    }
  }

  // 2. Check cart items (most recent first)
  for (let i = cartItems.length - 1; i >= 0; i--) {
    if (suggestedPairs.size >= limit) break;
    const cartItem = cartItems[i];
    const menuItem = menuByName.get(cartItem.menu_item_name.toLowerCase());
    if (menuItem && menuItem.pairs_with) {
      const rawPairs = menuItem.pairs_with.split(',').map(s => s.trim());
      for (const pairName of rawPairs) {
        if (suggestedPairs.size >= limit) break;
        const match = menuByName.get(pairName.toLowerCase());
        if (match && !cartItemNames.has(match.name.toLowerCase())) {
          suggestedPairs.add(match);
        }
      }
    }
  }

  return Array.from(suggestedPairs).slice(0, limit);
}
