import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { identifyCustomer } from '../services/api';
import { useApp } from '../context/useApp';

export default function WelcomePage() {
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { setCustomer, setOrder, setMessages, showToast } = useApp();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone.trim()) return;

    setLoading(true);
    setError('');

    try {
      const customer = await identifyCustomer(phone.trim(), name.trim() || undefined);
      
      // Clear out previous session data before setting new customer
      setOrder(null);
      setMessages([]);
      
      setCustomer(customer);

      if (customer.is_returning) {
        showToast(`Welcome back, ${customer.name || 'friend'}! 👋`, 'success');
      } else {
        showToast('Welcome! Your profile has been created.', 'success');
      }

      navigate('/chat');
    } catch (err) {
      setError((err as Error).message || 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="welcome-page">
      <div className="welcome-bg" />

      <div className="welcome-content">
        {/* Logo */}
        <div className="welcome-logo">🍽️</div>

        {/* Hero */}
        <h1 className="welcome-title">
          Meet Diaa,<br />Your AI Concierge
        </h1>
        <p className="welcome-subtitle">
          Order food naturally with voice or text. Diaa remembers your preferences
          and makes personalized recommendations just for you.
        </p>

        {/* Features */}
        <div className="flex gap-md mb-lg" style={{ flexWrap: 'wrap', justifyContent: 'center' }}>
          {['🎤 Voice Ordering', '🧠 AI Memory', '⭐ Personalized Picks'].map(f => (
            <span key={f} className="tag tag-orange">{f}</span>
          ))}
        </div>

        {/* Login Card */}
        <div className="login-card">
          <h2>Enter your phone number to begin</h2>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="phone">Phone Number</label>
              <input
                id="phone"
                className="form-input"
                type="tel"
                placeholder="+91 98765 43210"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="name">Your Name <span style={{ color: 'var(--clr-text-3)' }}>(optional)</span></label>
              <input
                id="name"
                className="form-input"
                type="text"
                placeholder="What should Diaa call you?"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={loading}
              />
            </div>

            {error && (
              <p style={{ color: 'var(--clr-error)', fontSize: '0.85rem', marginBottom: '1rem' }}>
                ⚠️ {error}
              </p>
            )}

            <button
              className="btn btn-primary btn-full btn-lg"
              type="submit"
              id="start-ordering-btn"
              disabled={loading || !phone.trim()}
            >
              {loading ? (
                <><div className="spinner" />Connecting...</>
              ) : (
                <>🚀 Start Ordering</>
              )}
            </button>
          </form>

          <p style={{ fontSize: '0.75rem', color: 'var(--clr-text-3)', textAlign: 'center', marginTop: '1rem' }}>
            Your phone number is only used to remember your preferences.
            No OTP, no password.
          </p>
        </div>
      </div>
    </div>
  );
}
