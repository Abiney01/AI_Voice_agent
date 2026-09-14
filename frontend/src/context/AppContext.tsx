import { useState, useCallback, type ReactNode } from 'react';
import type { Customer, Order, ChatMessage } from '../services/api';
import { AppContext, type AppContextValue } from './contextTypes';

// ─── Provider component ───────────────────────────────────────────────────────
// This file exports ONLY the AppProvider component.
// • AppContext (context object) → appContext.ts  (plain .ts, no JSX)
// • useApp (hook)               → useApp.ts
// This split is required for Vite Fast Refresh to work on all three files.

export function AppProvider({ children }: { children: ReactNode }) {
  const [customer, setCustomerState] = useState<Customer | null>(() => {
    const saved = localStorage.getItem('avrc_customer');
    return saved ? JSON.parse(saved) : null;
  });
  const [order, setOrder] = useState<Order | null>(null);
  const [orderHistory, setOrderHistory] = useState<Order[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toast, setToast] = useState<AppContextValue['toast']>(null);

  const setCustomer = useCallback((c: Customer | null) => {
    setCustomerState(c);
    if (c) {
      localStorage.setItem('avrc_customer', JSON.stringify(c));
    } else {
      localStorage.removeItem('avrc_customer');
    }
  }, []);

  const addMessage = useCallback((m: ChatMessage) => {
    setMessages(prev => [...prev, m]);
  }, []);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  }, []);

  return (
    <AppContext.Provider value={{
      customer, setCustomer,
      order, setOrder,
      orderHistory, setOrderHistory,
      messages, setMessages, addMessage,
      toast, showToast,
    }}>
      {children}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </AppContext.Provider>
  );
}
