import { createContext } from 'react';
import type { Customer, Order, ChatMessage } from '../services/api';

// ─── Shared context type ──────────────────────────────────────────────────────
// Kept in a plain .ts file (no JSX) so both AppContext.tsx and useApp.ts can
// import it without triggering Vite Fast Refresh warnings.

export interface AppContextValue {
  customer: Customer | null;
  setCustomer: (c: Customer | null) => void;
  order: Order | null;
  setOrder: (o: Order | null) => void;
  orderHistory: Order[];
  setOrderHistory: (h: Order[]) => void;
  messages: ChatMessage[];
  setMessages: (m: ChatMessage[]) => void;
  addMessage: (m: ChatMessage) => void;
  toast: { message: string; type: 'success' | 'error' | 'info' } | null;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

// The context object — imported by AppContext.tsx (Provider) and useApp.ts (hook)
export const AppContext = createContext<AppContextValue | null>(null);
