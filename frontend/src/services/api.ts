// API base URL
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ─── Customers ────────────────────────────────────────────────────────────

export interface Customer {
  id: number;
  phone_number: string;
  name: string | null;
  created_at: string;
  updated_at: string;
  is_returning: boolean;
  preferences?: {
    spice_level?: string;
    allergies?: string;
    dietary_preferences?: string;
    favorite_dishes?: string;
    disliked_dishes?: string;
  };
  total_orders?: number;
}

export async function identifyCustomer(phone_number: string, name?: string): Promise<Customer> {
  return request('/customers/identify', {
    method: 'POST',
    body: JSON.stringify({ phone_number, name }),
  });
}

export async function getCustomerProfile(id: number): Promise<Customer> {
  return request(`/customers/${id}`);
}

// ─── Menu ─────────────────────────────────────────────────────────────────

export interface MenuItem {
  id: number;
  name: string;
  category: string;
  cuisine: string;
  description?: string;
  price: number;
  is_vegetarian: boolean;
  is_vegan: boolean;
  spice_level?: string;
  allergens?: string;
  is_available: boolean;
}

export async function getMenu(limit?: number): Promise<MenuItem[]> {
  const url = limit ? `/menu?limit=${limit}` : '/menu';
  return request(url);
}

export async function searchMenu(query: string): Promise<{ items: MenuItem[]; total: number }> {
  return request(`/menu/search?q=${encodeURIComponent(query)}`);
}

// ─── Orders ───────────────────────────────────────────────────────────────

export interface OrderItem {
  id: number;
  menu_item_id: number;
  menu_item_name: string;
  quantity: number;
  unit_price: number;
  customization_notes?: string;
  subtotal: number;
}

export interface Order {
  id: number;
  customer_id: number;
  status: 'active' | 'confirmed' | 'cancelled';
  total_amount: number;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

export async function getOrCreateOrder(customer_id: number): Promise<Order> {
  return request('/orders', {
    method: 'POST',
    body: JSON.stringify({ customer_id }),
  });
}

export async function getOrder(order_id: number): Promise<Order> {
  return request(`/orders/${order_id}`);
}

export async function addOrderItem(
  order_id: number,
  menu_item_id: number,
  quantity = 1,
  customization_notes?: string,
): Promise<Order> {
  return request(`/orders/${order_id}/items`, {
    method: 'POST',
    body: JSON.stringify({ menu_item_id, quantity, customization_notes }),
  });
}

export async function removeOrderItem(order_id: number, item_id: number): Promise<Order> {
  return request(`/orders/${order_id}/items/${item_id}`, { method: 'DELETE' });
}

export async function confirmOrder(order_id: number): Promise<Order> {
  return request(`/orders/${order_id}/confirm`, { method: 'PUT' });
}

export async function cancelOrder(order_id: number): Promise<Order> {
  return request(`/orders/${order_id}/cancel`, { method: 'PUT' });
}

// ─── Conversations ────────────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ConversationEvent {
  type: string;
  status: string;
  is_retryable: boolean;
  details?: Record<string, unknown>;
}

export interface OrderAction {
  action: string;
  menu_item_name?: string;
  menu_item_id?: number;
  quantity: number;
  customization_notes?: string;
  status?: string;
  is_retryable?: boolean;
}

export interface OrderDiscrepancy {
  field: string;
  item?: string | null;
  llm_value?: unknown;
  cart_value?: unknown;
  message?: string;
}

export interface OrderSyncStatus {
  is_synced: boolean;
  discrepancies: OrderDiscrepancy[];
}

export interface ChatResponse {
  message: string;
  order_actions: OrderAction[];
  events: ConversationEvent[];
  sync_status?: OrderSyncStatus;
  updated_order?: Order;
  recommendations: unknown[];
}

export async function sendChatMessage(
  customer_id: number,
  message: string,
  conversation_history: ChatMessage[],
  active_order_id?: number,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request('/conversations/chat', {
    method: 'POST',
    body: JSON.stringify({ customer_id, message, conversation_history, active_order_id }),
    signal,
  });
}

// ─── Voice ────────────────────────────────────────────────────────────────

export async function transcribeAudio(audioBlob: Blob): Promise<{ transcript: string }> {
  const form = new FormData();
  form.append('audio', audioBlob, 'recording.wav');
  const res = await fetch(`${BASE_URL}/voice/transcribe`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Transcription failed');
  return res.json();
}

export async function synthesizeSpeech(text: string, voice?: string): Promise<ArrayBuffer> {
  const params = new URLSearchParams({ text });
  if (voice) params.append('voice', voice);
  const res = await fetch(
    `${BASE_URL}/voice/synthesize?${params.toString()}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error('Synthesis failed');
  return res.arrayBuffer();
}

// ─── Recommendations ──────────────────────────────────────────────────────

export interface Recommendation {
  priority: number;
  reason: string;
  items: Array<{
    id: number;
    name: string;
    category: string;
    price: number;
    description?: string;
    is_vegetarian: boolean;
    spice_level?: string;
  }>;
}

export async function getRecommendations(customer_id: number): Promise<{ recommendations: Recommendation[] }> {
  return request(`/recommendations/${customer_id}`);
}

// ─── Order History ────────────────────────────────────────────────────────

/** Returns confirmed past orders for the given customer (newest first). */
export async function getCustomerOrders(customer_id: number): Promise<Order[]> {
  return request(`/orders/customer/${customer_id}`);
}

/** Get the active (unconfirmed) order, or null if none exists yet. */
export async function getActiveOrder(customer_id: number): Promise<Order | null> {
  try {
    return await request(`/orders`, {
      method: 'POST',
      body: JSON.stringify({ customer_id }),
    });
  } catch {
    return null;
  }
}

// ─── Session / Memory ─────────────────────────────────────────────────────

/**
 * Called on logout — saves the conversation as a memory so Aria remembers
 * the session next time. Non-blocking: errors are swallowed intentionally.
 */
export async function endSession(
  customer_id: number,
  conversation_history: ChatMessage[],
): Promise<void> {
  try {
    await request('/conversations/end-session', {
      method: 'POST',
      body: JSON.stringify({ customer_id, conversation_history }),
    });
  } catch {
    // Non-critical — don't block logout on memory save failure
  }
}
