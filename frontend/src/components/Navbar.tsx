import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/useApp';
import { endSession, cancelOrder } from '../services/api';

export default function Navbar() {
  const { customer, setCustomer, setOrder, setMessages, order, messages } = useApp();
  const navigate = useNavigate();

  const handleLogout = async () => {
    // Cancel the current active order before logging out so it is not left active in the DB
    if (order && order.status === 'active') {
      try {
        await cancelOrder(order.id);
      } catch (err) {
        console.error('Failed to cancel active order on logout:', err);
      }
    }

    // Save conversation memory before clearing state — fire-and-forget
    if (customer && messages.length > 1) {
      endSession(customer.id, messages); // intentionally not awaited
    }

    setCustomer(null);
    setOrder(null);
    setMessages([]);
    navigate('/');
  };

  const initials = customer?.name
    ? customer.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : customer?.phone_number?.slice(-2) || '?';

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <div className="logo-icon">🍽️</div>
        <div>
          <span className="brand-name">AI Concierge</span>
          <span className="brand-tagline">Powered by Gemini</span>
        </div>
      </div>

      <div className="navbar-customer">
        {order && order.items.length > 0 && (
          <span className="tag tag-orange">
            🛒 {order.items.length} item{order.items.length !== 1 ? 's' : ''}
          </span>
        )}
        {customer && (
          <div className="customer-badge">
            <div className="avatar">{initials}</div>
            <span>{customer.name || customer.phone_number}</span>
          </div>
        )}
        <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </nav>
  );
}
