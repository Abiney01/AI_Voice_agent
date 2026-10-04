import type { MenuItem } from '../services/api';

export interface UserPreferences {
  spice_level?: string;
  allergies?: string;
  dietary_preferences?: string;
  favorite_dishes?: string;
  disliked_dishes?: string;
}

export interface FilterOptions {
  mealPeriod?: 'breakfast' | 'brunch' | 'lunch' | 'dinner' | 'snacks' | 'all';
  currentRequest?: string;
  preferences?: UserPreferences;
  orderHistory?: string[]; // past dish names
  selectedCategory?: string;
  searchQuery?: string;
}

/**
 * Detect current meal period based on IST time (matches backend).
 */
export function detectMealPeriod(): 'breakfast' | 'brunch' | 'lunch' | 'dinner' | 'snacks' {
  // IST = UTC + 5:30
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const istDate = new Date(utc + 3600000 * 5.5);
  const hour = istDate.getHours();

  if (5 <= hour && hour < 11) return 'breakfast';
  if (11 <= hour && hour < 14) return 'brunch';
  if (14 <= hour && hour < 17) return 'lunch';
  if (17 <= hour && hour < 20) return 'snacks';
  return 'dinner';
}

/**
 * Filter and rank menu items dynamically:
 * 1. Hard filters: vegetarian, vegan, allergies, strict spice restrictions, explicit meal times.
 * 2. Soft ranking: preferred cuisine, current request keywords, favorites, light/healthy cues, order history.
 */
export function filterAndRankMenu(items: MenuItem[], options: FilterOptions): MenuItem[] {
  const {
    mealPeriod,
    currentRequest = '',
    preferences = {},
    orderHistory = [],
    selectedCategory = 'All',
    searchQuery = '',
  } = options;

  const reqLower = currentRequest.toLowerCase();
  const searchLower = searchQuery.toLowerCase().trim();

  // ── 1. Detect Intent Flags from Current Request ──
  const wantsBreakfast = /\b(breakfast|morning|dosa|idli|pancake|waffle|toast|omelette|poha|upma)\b/.test(reqLower);
  const wantsLunch     = /\b(lunch|afternoon|biryani|curry|meal)\b/.test(reqLower);
  const wantsDinner    = /\b(dinner|night|steak|pizza)\b/.test(reqLower);
  const wantsSnacks    = /\b(snack|snacks|tea time|evening|starter|appetizer|bites|wings|samosa)\b/.test(reqLower);
  const wantsDrinks    = /\b(drink|drinks|beverage|beverages|juice|soda|coffee|tea|chai|shake|lassi)\b/.test(reqLower);
  const wantsDesserts  = /\b(dessert|desserts|sweet|sweets|ice cream|cake|jamun|kheer|brownie)\b/.test(reqLower);

  const wantsVeg       = /\b(veg|vegetarian|pure veg)\b/.test(reqLower) || preferences.dietary_preferences?.toLowerCase().includes('veg');
  const wantsVegan     = /\b(vegan)\b/.test(reqLower) || preferences.dietary_preferences?.toLowerCase().includes('vegan');
  const wantsMild      = /\b(mild|not spicy|less spicy|no spice|kids)\b/.test(reqLower) || preferences.spice_level?.toLowerCase() === 'mild';
  const wantsSpicy     = /\b(spicy|hot|extra spicy|tikka|masala)\b/.test(reqLower) && !wantsMild;
  const wantsLight     = /\b(light|healthy|diet|simple|refreshing|something light)\b/.test(reqLower);

  const wantsIndian    = /\b(indian|desi|curry|biryani|naan|roti|paratha|dosa)\b/.test(reqLower) || preferences.favorite_dishes?.toLowerCase().includes('indian');
  const wantsAmerican  = /\b(american|western|burger|fries|pizza|steak|wings|pancake)\b/.test(reqLower);

  // Parse allergies from preferences
  const allergies = (preferences.allergies || '')
    .toLowerCase()
    .split(/[,;]+/)
    .map(s => s.trim())
    .filter(Boolean);

  // Active meal period to filter (explicit request overrides auto-detected period)
  let activePeriod: string | undefined = mealPeriod;
  if (wantsBreakfast) activePeriod = 'breakfast';
  else if (wantsLunch) activePeriod = 'lunch';
  else if (wantsDinner) activePeriod = 'dinner';
  else if (wantsSnacks) activePeriod = 'snacks';

  // ── 2. Apply Hard Filters ──
  const filtered = items.filter(item => {
    if (!item.is_available) return false;

    // Search query filter
    if (searchLower) {
      const match =
        item.name.toLowerCase().includes(searchLower) ||
        item.category.toLowerCase().includes(searchLower) ||
        item.cuisine.toLowerCase().includes(searchLower) ||
        (item.description && item.description.toLowerCase().includes(searchLower));
      if (!match) return false;
    }

    // Manual category filter
    if (selectedCategory && selectedCategory !== 'All') {
      if (item.category.toLowerCase() !== selectedCategory.toLowerCase()) {
        return false;
      }
    }

    // Hard filter: Vegetarian
    if (wantsVeg && !item.is_vegetarian) {
      return false;
    }

    // Hard filter: Vegan
    if (wantsVegan && !item.is_vegan) {
      return false;
    }

    // Hard filter: Allergies
    if (allergies.length > 0 && item.allergens) {
      const itemAllergens = item.allergens.toLowerCase();
      for (const allergy of allergies) {
        if (itemAllergens.includes(allergy)) {
          return false;
        }
      }
    }

    // Hard filter: Strict Mild
    if (wantsMild && item.spice_level === 'hot') {
      return false;
    }

    // Hard filter: Meal period compatibility
    // (Only if meal period is specific, and user didn't explicitly pick "All" category)
    if (activePeriod && activePeriod !== 'all' && selectedCategory === 'All' && !searchLower) {
      const itemMeals = (item.meal_times || 'all').toLowerCase();
      const isBeverageOrDessert = item.category === 'Beverages' || item.category === 'Desserts';
      
      if (wantsDrinks && item.category !== 'Beverages') return false;
      if (wantsDesserts && item.category !== 'Desserts') return false;

      // Allow beverages & all-time items across any meal period
      if (!isBeverageOrDessert && !itemMeals.includes('all')) {
        const periodTokens = itemMeals.split(',').map(s => s.trim());
        if (!periodTokens.includes(activePeriod)) {
          // If asking for breakfast specifically, exclude non-breakfast
          if (wantsBreakfast) return false;
          // For general time of day, don't show heavy dinner steaks at breakfast
          if (activePeriod === 'breakfast' && !periodTokens.includes('brunch')) return false;
        }
      }
    }

    return true;
  });

  // ── 3. Soft Ranking & Prioritization ──
  // Calculate a relevance score for each surviving item
  const scored = filtered.map(item => {
    let score = 0;
    const nameLower = item.name.toLowerCase();
    const descLower = (item.description || '').toLowerCase();
    const cuisineLower = item.cuisine.toLowerCase();

    // Cuisine preference / request
    if (wantsIndian && cuisineLower === 'indian') score += 15;
    if (wantsAmerican && cuisineLower === 'american') score += 15;

    // Spiciness preference
    if (wantsSpicy && (item.spice_level === 'hot' || item.spice_level === 'medium')) score += 12;
    if (wantsMild && (item.spice_level === 'mild' || !item.spice_level)) score += 10;

    // Light / healthy request
    if (wantsLight) {
      const lightCategories = ['Breakfast', 'Beverages', 'Sides'];
      if (lightCategories.includes(item.category) || nameLower.includes('salad') || nameLower.includes('idli') || nameLower.includes('upma')) {
        score += 15;
      }
      if (item.category === 'Biryani' || item.category === 'Burgers') {
        score -= 10;
      }
    }

    // Direct keyword match with current request
    if (reqLower) {
      const words = reqLower.split(/\s+/).filter(w => w.length > 3);
      for (const word of words) {
        if (nameLower.includes(word)) score += 12;
        else if (descLower.includes(word)) score += 5;
      }
    }

    // Explicit Favorites match
    if (preferences.favorite_dishes) {
      const favs = preferences.favorite_dishes.toLowerCase();
      if (favs.includes(nameLower)) {
        score += 8;
      }
    }

    // Order History slight boost (never overrides current request)
    if (orderHistory && orderHistory.length > 0) {
      for (const prevName of orderHistory) {
        if (prevName.toLowerCase() === nameLower) {
          score += 2; // minor tie-breaker
          break;
        }
      }
    }

    return { item, score };
  });

  // Sort descending by score, then preserve standard menu order
  scored.sort((a, b) => b.score - a.score);

  return scored.map(s => s.item);
}
