import { useContext } from 'react';
import { AppContext } from './contextTypes';

/**
 * Hook to access app-wide state (customer, order, messages, etc.).
 * Kept in its own file so AppContext.tsx can export only the AppProvider
 * component — satisfying Vite's Fast Refresh requirement.
 */
export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
