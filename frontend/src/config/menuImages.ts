/**
 * Menu item image mapping.
 * Provides curated, stable, high-resolution food photography URLs for each dish on the menu.
 * 
 * Lookup resolution:
 *   menu item -> normalized name / slug -> image URL -> fallback by category
 */

export const menuImages: Record<string, string> = {
  // ── Indian Breakfast ──
  "masala-dosa": "https://images.unsplash.com/photo-1668236543090-82eba5ee5976?auto=format&fit=crop&w=400&q=80",
  "plain-dosa": "https://images.unsplash.com/photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=400&q=80",
  "idli-3-pcs": "https://images.unsplash.com/photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=400&q=80",
  "medu-vada-2-pcs": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "pongal": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "upma": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "aloo-paratha": "https://images.unsplash.com/photo-1626074353765-517a681e40be?auto=format&fit=crop&w=400&q=80",
  "poha": "https://images.unsplash.com/photo-1645177628172-a94c1f96e6db?auto=format&fit=crop&w=400&q=80",

  // ── American Breakfast ──
  "buttermilk-pancakes": "https://images.unsplash.com/photo-1528207776546-365bb710ee93?auto=format&fit=crop&w=400&q=80",
  "belgian-waffles": "https://images.unsplash.com/photo-1562376552-0d160a2f238d?auto=format&fit=crop&w=400&q=80",
  "french-toast": "https://images.unsplash.com/photo-1484723091739-30a097e8f929?auto=format&fit=crop&w=400&q=80",
  "classic-omelette": "https://images.unsplash.com/photo-1510693206972-df098062cb71?auto=format&fit=crop&w=400&q=80",
  "breakfast-sandwich": "https://images.unsplash.com/photo-1550547660-d9450f859349?auto=format&fit=crop&w=400&q=80",
  "avocado-toast": "https://images.unsplash.com/photo-1588137378633-dea1336ce1e2?auto=format&fit=crop&w=400&q=80",

  // ── Biryani ──
  "chicken-biryani": "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=400&q=80",
  "mutton-biryani": "https://images.unsplash.com/photo-1633945274405-b6c8069047b0?auto=format&fit=crop&w=400&q=80",
  "veg-biryani": "https://images.unsplash.com/photo-1642821373181-696a54913e9a?auto=format&fit=crop&w=400&q=80",
  "egg-biryani": "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=400&q=80",

  // ── Curries ──
  "butter-chicken": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=400&q=80",
  "chicken-tikka-masala": "https://images.unsplash.com/photo-1565557623262-b51c2513a641?auto=format&fit=crop&w=400&q=80",
  "paneer-butter-masala": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=400&q=80",
  "palak-paneer": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  "dal-makhani": "https://images.unsplash.com/photo-1546833999-b9f581a1996d?auto=format&fit=crop&w=400&q=80",
  "kadai-chicken": "https://images.unsplash.com/photo-1610057099443-fde8c4d50f91?auto=format&fit=crop&w=400&q=80",

  // ── Starters ──
  "chicken-65": "https://images.unsplash.com/photo-1626082927389-6cd097cdc6ec?auto=format&fit=crop&w=400&q=80",
  "paneer-tikka": "https://images.unsplash.com/photo-1599488615731-7e5c2823ff28?auto=format&fit=crop&w=400&q=80",
  "samosa-2-pcs": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  "pakora-platter": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "buffalo-wings-6-pcs": "https://images.unsplash.com/photo-1527477378708-011267866380?auto=format&fit=crop&w=400&q=80",
  "mac-cheese-bites": "https://images.unsplash.com/photo-1543339308-43e59d6b73a6?auto=format&fit=crop&w=400&q=80",
  "caesar-salad": "https://images.unsplash.com/photo-1550304943-4f24f54ddde9?auto=format&fit=crop&w=400&q=80",

  // ── Breads ──
  "butter-naan": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  "garlic-naan": "https://images.unsplash.com/photo-1633945274405-b6c8069047b0?auto=format&fit=crop&w=400&q=80",
  "plain-roti": "https://images.unsplash.com/photo-1626074353765-517a681e40be?auto=format&fit=crop&w=400&q=80",
  "plain-paratha": "https://images.unsplash.com/photo-1626074353765-517a681e40be?auto=format&fit=crop&w=400&q=80",

  // ── Rice ──
  "steamed-basmati-rice": "https://images.unsplash.com/photo-1516684732162-798a0062be99?auto=format&fit=crop&w=400&q=80",
  "jeera-rice": "https://images.unsplash.com/photo-1536304993881-ff6e9eefa2a6?auto=format&fit=crop&w=400&q=80",

  // ── Sides ──
  "raita": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "papad": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  "mixed-pickle": "https://images.unsplash.com/photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=400&q=80",
  "classic-fries": "https://images.unsplash.com/photo-1576107232684-1279f3908594?auto=format&fit=crop&w=400&q=80",
  "loaded-cheese-fries": "https://images.unsplash.com/photo-1585109649139-366815a0d713?auto=format&fit=crop&w=400&q=80",
  "onion-rings": "https://images.unsplash.com/photo-1639024471287-03521672c219?auto=format&fit=crop&w=400&q=80",
  "classic-coleslaw": "https://images.unsplash.com/photo-1625944525533-473f1a3d54e7?auto=format&fit=crop&w=400&q=80",
  "garlic-bread": "https://images.unsplash.com/photo-1573140247632-f8fd74997d5c?auto=format&fit=crop&w=400&q=80",

  // ── Burgers ──
  "classic-smash-burger": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=400&q=80",
  "bbq-bacon-burger": "https://images.unsplash.com/photo-1586190848861-99aa4a171e90?auto=format&fit=crop&w=400&q=80",
  "crispy-chicken-sandwich": "https://images.unsplash.com/photo-1625813506062-0aeb1d7a094b?auto=format&fit=crop&w=400&q=80",
  "veggie-beyond-burger": "https://images.unsplash.com/photo-1520072959219-c595dc870360?auto=format&fit=crop&w=400&q=80",

  // ── Mains ──
  "bbq-pulled-pork-platter": "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=400&q=80",
  "grilled-ribeye-steak": "https://images.unsplash.com/photo-1558030006-450675393462?auto=format&fit=crop&w=400&q=80",
  "new-york-style-pizza-12": "https://images.unsplash.com/photo-1513104890138-7c749659a591?auto=format&fit=crop&w=400&q=80",
  "bbq-chicken-pizza-12": "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=400&q=80",
  "penne-arrabbiata": "https://images.unsplash.com/photo-1621996346565-e3d5d6281699?auto=format&fit=crop&w=400&q=80",

  // ── Fusion ──
  "tandoori-chicken-sandwich": "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=400&q=80",
  "tikka-masala-wrap": "https://images.unsplash.com/photo-1626700051175-6818013e1d4f?auto=format&fit=crop&w=400&q=80",
  "masala-fries": "https://images.unsplash.com/photo-1585109649139-366815a0d713?auto=format&fit=crop&w=400&q=80",
  "paneer-quesadilla": "https://images.unsplash.com/photo-1618040996337-56904b7850b9?auto=format&fit=crop&w=400&q=80",

  // ── Beverages ──
  "mango-lassi": "https://images.unsplash.com/photo-1553530666-ba11a7da3888?auto=format&fit=crop&w=400&q=80",
  "masala-chai": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?auto=format&fit=crop&w=400&q=80",
  "sweet-lassi": "https://images.unsplash.com/photo-1553530666-ba11a7da3888?auto=format&fit=crop&w=400&q=80",
  "fresh-lime-soda": "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?auto=format&fit=crop&w=400&q=80",
  "classic-milkshake": "https://images.unsplash.com/photo-1572490122747-3968b75cc699?auto=format&fit=crop&w=400&q=80",
  "fresh-lemonade": "https://images.unsplash.com/photo-1621263764928-df1444c5e859?auto=format&fit=crop&w=400&q=80",
  "fresh-orange-juice": "https://images.unsplash.com/photo-1613478223719-2ab802602423?auto=format&fit=crop&w=400&q=80",
  "americano-coffee": "https://images.unsplash.com/photo-1509042239860-f550ce710b93?auto=format&fit=crop&w=400&q=80",
  "cappuccino": "https://images.unsplash.com/photo-1572442388796-11668a67e53d?auto=format&fit=crop&w=400&q=80",
  "craft-root-beer": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=400&q=80",

  // ── Desserts ──
  "gulab-jamun-2-pcs": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  "kheer": "https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=400&q=80",
  "new-york-cheesecake": "https://images.unsplash.com/photo-1533134242443-d4fd215305ad?auto=format&fit=crop&w=400&q=80",
  "warm-brownie-sundae": "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=400&q=80",
};

// Generic category fallbacks
export const categoryFallbacks: Record<string, string> = {
  breakfast: "https://images.unsplash.com/photo-1528207776546-365bb710ee93?auto=format&fit=crop&w=400&q=80",
  biryani: "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=400&q=80",
  curries: "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=400&q=80",
  starters: "https://images.unsplash.com/photo-1626082927389-6cd097cdc6ec?auto=format&fit=crop&w=400&q=80",
  breads: "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=400&q=80",
  rice: "https://images.unsplash.com/photo-1516684732162-798a0062be99?auto=format&fit=crop&w=400&q=80",
  sides: "https://images.unsplash.com/photo-1576107232684-1279f3908594?auto=format&fit=crop&w=400&q=80",
  burgers: "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=400&q=80",
  mains: "https://images.unsplash.com/photo-1558030006-450675393462?auto=format&fit=crop&w=400&q=80",
  beverages: "https://images.unsplash.com/photo-1553530666-ba11a7da3888?auto=format&fit=crop&w=400&q=80",
  desserts: "https://images.unsplash.com/photo-1533134242443-d4fd215305ad?auto=format&fit=crop&w=400&q=80",
  fusion: "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=400&q=80",
  default: "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=400&q=80",
};

/**
 * Normalizes an item name into a clean hyphenated slug:
 * e.g. "Idli (3 pcs)" -> "idli-3-pcs"
 *      "New York Style Pizza (12\")" -> "new-york-style-pizza-12"
 */
export function slugifyMenuItemName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[()"'"]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Dynamically resolves the high-res image URL for any MenuItem.
 * 1. Checks exact slug
 * 2. Checks cleaned name
 * 3. Falls back to category fallback
 * 4. Falls back to default food photo
 */
export function getMenuItemImage(item: { name: string; category?: string; cuisine?: string }): string {
  const slug = slugifyMenuItemName(item.name);
  if (menuImages[slug]) {
    return menuImages[slug];
  }

  // Try category fallback
  const catKey = (item.category || "").toLowerCase();
  if (categoryFallbacks[catKey]) {
    return categoryFallbacks[catKey];
  }

  return categoryFallbacks.default;
}
