import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/useApp';
import {
  sendChatMessage,
  getOrCreateOrder,
  confirmOrder,
  endSession,
  getCustomerProfile,
  synthesizeSpeech,
  getMenu,
  type ChatMessage,
  type Order,
  type MenuItem,
} from '../services/api';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder';
import './ChatPage.css';

const stopAudioSource = (source: AudioBufferSourceNode | null) => {
  if (source) {
    try { source.stop(); } catch { void 0; }
  }
};

function splitIntoSentences(text: string): string[] {
  const parts = text.match(/[^.!?\u2026]+(?:[.!?\u2026]+(?:\s|$)|\s*$)/g);
  if (!parts) return [text.trim()].filter(Boolean);
  return parts.map(s => s.trim()).filter(s => s.length > 0);
}

const formatPrice = (price: number) => `₹${price.toLocaleString('en-IN')}`;

export default function ChatPage() {
  const {
    customer, setCustomer,
    order, setOrder,
    messages, setMessages, addMessage,
    showToast,
  } = useApp();
  const navigate = useNavigate();

  const [isTyping, setIsTyping]           = useState(false);
  const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
  const [isPaused, setIsPaused]           = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const [menuItems, setMenuItems]         = useState<MenuItem[]>([]);
  // "session ended by cart" — voice stopped, user can restart or leave
  const [sessionEnded, setSessionEnded]   = useState(false);

  const messagesEndRef       = useRef<HTMLDivElement>(null);
  const audioCtxRef          = useRef<AudioContext | null>(null);
  const activeSourceRef      = useRef<AudioBufferSourceNode | null>(null);
  const scheduledSourcesRef  = useRef<AudioBufferSourceNode[]>([]);
  const playTTSAbortRef      = useRef<AbortController | null>(null);
  const abortControllerRef   = useRef<AbortController | null>(null);
  const isPausedRef          = useRef<boolean>(false);
  const startListeningRef    = useRef<() => void>(() => {});
  // Keep a live ref to the order so stale closures always see the current id
  const orderRef = useRef<Order | null>(order);
  useEffect(() => { orderRef.current = order; }, [order]);

  // Redirect if no customer
  useEffect(() => { if (!customer) navigate('/'); }, [customer, navigate]);

  // Fetch menu (up to 15 items)
  useEffect(() => {
    getMenu().then(items => setMenuItems(items.slice(0, 15))).catch(() => {});
  }, []);

  // Refresh customer profile on mount
  const customerId = customer?.id;
  useEffect(() => {
    if (customerId) getCustomerProfile(customerId).then(setCustomer).catch(() => {});
  }, [customerId, setCustomer]);

  // Init order on mount
  useEffect(() => {
    if (customer && !order) {
      getOrCreateOrder(customer.id)
        .then(setOrder)
        .catch(() => showToast('Could not start order session', 'error'));
    }
  }, [customer, order, setOrder, showToast]);

  /** Stop all scheduled TTS audio and cancel any in-progress synthesis. */
  const stopAllTTS = useCallback(() => {
    playTTSAbortRef.current?.abort();
    scheduledSourcesRef.current.forEach(s => stopAudioSource(s));
    scheduledSourcesRef.current = [];
    activeSourceRef.current = null;
  }, []);

  /**
   * Sentence-level progressive TTS.
   * onDone: optional callback run when the last sentence finishes (instead of auto-listen).
   */
  const playTTS = useCallback(async (text: string, onDone?: () => void) => {
    playTTSAbortRef.current?.abort();
    const abort = new AbortController();
    playTTSAbortRef.current = abort;

    scheduledSourcesRef.current.forEach(s => stopAudioSource(s));
    scheduledSourcesRef.current = [];
    activeSourceRef.current = null;

    try {
      if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
      const audioCtx = audioCtxRef.current;
      const sentences = splitIntoSentences(text);
      setIsAgentSpeaking(true);

      let scheduledUntil = audioCtx.currentTime;
      let sentencesScheduled = 0;

      for (let i = 0; i < sentences.length; i++) {
        if (abort.signal.aborted || isPausedRef.current) break;
        try {
          const buffer = await synthesizeSpeech(sentences[i]);
          if (abort.signal.aborted || isPausedRef.current) break;
          const decoded = await audioCtx.decodeAudioData(buffer);
          if (abort.signal.aborted || isPausedRef.current) break;

          const source = audioCtx.createBufferSource();
          source.buffer = decoded;
          source.connect(audioCtx.destination);

          const startAt = Math.max(scheduledUntil, audioCtx.currentTime + 0.01);
          scheduledUntil = startAt + decoded.duration;

          if (i === sentences.length - 1) {
            source.onended = () => {
              if (!abort.signal.aborted) {
                setIsAgentSpeaking(false);
                scheduledSourcesRef.current = [];
                activeSourceRef.current = null;
                if (onDone) {
                  onDone();
                } else if (!isPausedRef.current) {
                  startListeningRef.current();
                }
              }
            };
          }
          source.start(startAt);
          scheduledSourcesRef.current.push(source);
          activeSourceRef.current = source;
          sentencesScheduled++;
        } catch (e) {
          if (!abort.signal.aborted) console.error(`TTS sentence ${i + 1} failed:`, e);
        }
      }

      if (sentencesScheduled === 0 && !abort.signal.aborted) {
        setIsAgentSpeaking(false);
        if (onDone) onDone();
        else if (!isPausedRef.current) startListeningRef.current();
      }
    } catch (err) {
      if (!abort.signal.aborted) {
        console.error('TTS playback failed:', err);
        setIsAgentSpeaking(false);
        if (onDone) onDone();
        else if (!isPausedRef.current) startListeningRef.current();
      }
    }
  }, []);

  /**
   * Stop the voice session completely (TTS + mic) without navigating away.
   * The user can tap "Start Again" to resume.
   */
  const endVoiceSession = useCallback(() => {
    stopAllTTS();
    setIsAgentSpeaking(false);
    isPausedRef.current = true; // prevent auto-listen
    setSessionEnded(true);
  }, [stopAllTTS]);

  // Initial greeting — fires once
  useEffect(() => {
    if (customer && messages.length === 0) {
      const prefs = customer.preferences;
      let prefNote = '';
      if (prefs?.spice_level)    prefNote += ` I know you enjoy ${prefs.spice_level} food.`;
      if (prefs?.favorite_dishes) prefNote += ` Your favourites are ${prefs.favorite_dishes}.`;

      const greeting = customer.is_returning
        ? `Welcome back, ${customer.name || 'friend'}! Great to see you again.${prefNote} What can I get for you today?`
        : `Hi ${customer.name || 'there'}! I'm Diaa, your restaurant concierge. What are you in the mood for today?`;

      setMessages([{ role: 'assistant', content: greeting }]);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      playTTS(greeting);
    }
  }, [customer, messages, setMessages, playTTS]);

  // Auto-scroll transcript
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || !customer || sessionEnded) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    addMessage(userMsg);
    setIsTyping(true);

    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const history = [...messages, userMsg];
      const response = await sendChatMessage(
        customer.id,
        text,
        history.slice(-20),
        orderRef.current?.id,   // use ref to avoid stale closure
        controller.signal,
      );

      const aiMsg: ChatMessage = { role: 'assistant', content: response.message };
      addMessage(aiMsg);

      // Check for terminal condition based on is_retryable flag in events / order_actions
      const hasTerminalEvent =
        response.events?.some(e => e.is_retryable === false) ||
        response.order_actions?.some(a => a.is_retryable === false);

      const orderConfirmedOrCancelled = response.updated_order
        ? response.updated_order.status !== 'active'
        : false;

      const isTerminal = hasTerminalEvent || orderConfirmedOrCancelled;

      // Always sync order — backend always returns updated_order.
      if (response.updated_order) {
        setOrder(response.updated_order as Order);
      }

      // If terminal (is_retryable === false), immediately terminate the conversation/session:
      // Play the final confirmation/cancellation response and do not listen again.
      if (isTerminal) {
        playTTS(response.message, () => {
          endVoiceSession();
        });
      } else {
        playTTS(response.message);
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      addMessage({ role: 'assistant', content: "I'm having a moment — could you try again?" });
      showToast('Connection error', 'error');
    } finally {
      setIsTyping(false);
    }
  }, [customer, messages, addMessage, showToast, setOrder, playTTS, endVoiceSession, sessionEnded]);

  const { state: recorderState, toggleRecording } = useVoiceRecorder(sendMessage);

  useEffect(() => {
    startListeningRef.current = () => {
      if (recorderState === 'idle' && !isPausedRef.current) toggleRecording();
    };
  }, [recorderState, toggleRecording]);

  // ── "Start Again" — restart voice without losing cart ────────────────────
  const handleStartAgain = async () => {
    if (customer && order && order.status !== 'active') {
      try {
        const newOrder = await getOrCreateOrder(customer.id);
        setOrder(newOrder);
      } catch {
        showToast('Could not start a new order', 'error');
      }
    }
    setSessionEnded(false);
    isPausedRef.current = false;
    setIsPaused(false);
    // Start listening immediately
    setTimeout(() => {
      if (recorderState === 'idle') toggleRecording();
    }, 150);
  };

  const handleOrbClick = () => {
    if (sessionEnded) { handleStartAgain(); return; }
    if (isPaused)     { handleTogglePause(); return; }
    if (isAgentSpeaking) {
      stopAllTTS();
      setIsAgentSpeaking(false);
      setTimeout(() => { if (recorderState === 'idle') toggleRecording(); }, 100);
      return;
    }
    toggleRecording();
  };

  const handleTogglePause = () => {
    const next = !isPaused;
    setIsPaused(next);
    isPausedRef.current = next;
    if (next) {
      if (recorderState === 'recording') toggleRecording();
      stopAllTTS();
      setIsAgentSpeaking(false);
      showToast('Diaa Muted', 'info');
    } else {
      showToast('Diaa Resumed', 'success');
      if (recorderState === 'idle') toggleRecording();
    }
  };

  /** End Session → confirm pending order + navigate home */
  const handleEndConversation = async () => {
    if (!customer) return;

    if (abortControllerRef.current) abortControllerRef.current.abort();
    stopAllTTS();
    setIsAgentSpeaking(false);

    const currentOrder = orderRef.current;
    if (currentOrder && currentOrder.items?.length > 0 && currentOrder.status === 'active') {
      try {
        showToast('Confirming your order...', 'info');
        await confirmOrder(currentOrder.id);
        showToast('Order confirmed! Enjoy your meal.', 'success');
      } catch {
        showToast('Could not confirm order', 'error');
      }
    }

    if (messages.length > 1) endSession(customer.id, messages);

    setCustomer(null);
    setOrder(null);
    setMessages([]);
    navigate('/');
  };

  const getAgentState = (): 'ended' | 'paused' | 'listening' | 'thinking' | 'speaking' | 'idle' => {
    if (sessionEnded)                                   return 'ended';
    if (isPaused)                                       return 'paused';
    if (recorderState === 'recording')                  return 'listening';
    if (recorderState === 'processing' || isTyping)     return 'thinking';
    if (isAgentSpeaking)                                return 'speaking';
    return 'idle';
  };

  const agentState = getAgentState();

  const getStatusText = () => {
    switch (agentState) {
      case 'ended':     return order?.status === 'confirmed' ? 'Order Confirmed!' : 'Added to cart!';
      case 'paused':    return 'Muted';
      case 'listening': return 'Listening...';
      case 'thinking':  return 'Thinking...';
      case 'speaking':  return 'Diaa is speaking...';
      case 'idle':      return 'Tap orb to speak';
    }
  };

  const getStatusSubtext = () => {
    switch (agentState) {
      case 'ended':     return order?.status === 'confirmed' ? 'Tap "Start Again" to place a new order' : 'Tap the orb or "Start Again" to keep ordering';
      case 'paused':    return 'Tap Resume to continue';
      case 'listening': return 'Go ahead, tell me what you would like';
      case 'thinking':  return 'Diaa is processing your request';
      case 'speaking':  return 'Tap orb to interrupt';
      case 'idle':      return 'Say something like "I want to order biryani"';
    }
  };

  const initials = customer?.name
    ? customer.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : customer?.phone_number?.slice(-2) || '?';

  const orderTotal = order?.total_amount ?? 0;

  // Orb CSS class — 'ended' maps to 'idle' visually (stays blue/calm)
  const orbClass = agentState === 'ended' ? 'idle' : agentState;

  return (
    <div className="diaa-layout">

      {/* ── LEFT PANEL: Menu ─────────────────────────── */}
      <aside className="menu-panel">
        <div className="panel-header">
          <span className="panel-title">Menu</span>
          <span className="panel-subtitle">{menuItems.length} items</span>
        </div>
        <div className="menu-list">
          {menuItems.length === 0 ? (
            <div className="menu-loading">
              <div className="spinner" />
              <span>Loading menu...</span>
            </div>
          ) : (
            menuItems.map(item => (
              <div key={item.id} className="menu-row">
                <span className="menu-item-name">{item.name}</span>
                <span className="menu-item-price">{formatPrice(item.price)}</span>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* ── CENTER PANEL: Diaa Voice ─────────────────── */}
      <main className="diaa-center">

        {/* Header */}
        <header className="diaa-header">
          <div className="diaa-brand">
            <div className="brand-dot" />
            <span className="brand-name">Diaa</span>
            <span className="brand-tag">Restaurant Concierge</span>
          </div>
          {customer && (
            <div className="customer-chip">
              <div className="customer-avatar">{initials}</div>
              <span className="customer-name">{customer.name || customer.phone_number}</span>
            </div>
          )}
        </header>

        {/* Orb */}
        <div className="orb-section">
          <div className="orb-wrapper" onClick={handleOrbClick}>
            <div className={`voice-orb ${orbClass}`}>
              <div className="orb-core" />
            </div>
            <div className="orb-ring" />
            <div className="orb-ring" style={{ animationDelay: '0.8s' }} />
            <div className="orb-ring" style={{ animationDelay: '1.6s' }} />
          </div>

          <div className="status-container">
            <h2 className="status-text">{getStatusText()}</h2>
            <p className="status-subtext">{getStatusSubtext()}</p>
          </div>
        </div>

        {/* Transcript — collapsible toggle */}
        <section className="transcript-section">
          <button
            className={`transcript-toggle ${showTranscript ? 'active' : ''}`}
            onClick={() => setShowTranscript(s => !s)}
            id="transcript-toggle-btn"
          >
            <span className="toggle-icon">{showTranscript ? '▲' : '▼'}</span>
            {showTranscript ? 'Hide Transcript' : 'Show Transcript'}
          </button>

          {showTranscript && (
            <div className="transcript-box">
              {messages.map((msg, i) => (
                <div key={i} className={`transcript-message ${msg.role}`}>
                  <span className="message-label">
                    {msg.role === 'user' ? 'You' : 'Diaa'}
                  </span>
                  <div className="message-bubble">{msg.content}</div>
                </div>
              ))}
              {isTyping && (
                <div className="transcript-message assistant">
                  <span className="message-label">Diaa</span>
                  <div className="message-bubble typing-dots">
                    <span /><span /><span />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </section>

        {/* Controls */}
        <footer className="diaa-controls">

          {sessionEnded ? (
            /* Session ended (cart updated) — show Start Again */
            <button
              id="start-again-btn"
              className="ctrl-btn ctrl-btn--start"
              onClick={handleStartAgain}
            >
              <div className="ctrl-icon">🎙</div>
              <span className="ctrl-label">Start Again</span>
            </button>
          ) : (
            <button
              id="mute-btn"
              className={`ctrl-btn ${isPaused ? 'ctrl-btn--active' : ''}`}
              onClick={handleTogglePause}
              title={isPaused ? 'Resume Conversation' : 'Mute Diaa'}
            >
              <div className="ctrl-icon">{isPaused ? '▶' : '⏸'}</div>
              <span className="ctrl-label">{isPaused ? 'Resume' : 'Mute'}</span>
            </button>
          )}

          <button
            id="end-session-btn"
            className="ctrl-btn ctrl-btn--end"
            onClick={handleEndConversation}
            title="Confirm Order and End Session"
          >
            <div className="ctrl-icon">⏹</div>
            <span className="ctrl-label">End Session</span>
          </button>
        </footer>
      </main>

      {/* ── RIGHT PANEL: Order Summary ───────────────── */}
      <aside className="order-panel">
        <div className="panel-header">
          <span className="panel-title">Your Order</span>
          {order?.status && (
            <span className={`order-badge order-badge--${order.status}`}>
              {order.status}
            </span>
          )}
        </div>

        <div className="order-items-scroll">
          {!order || order.items.length === 0 ? (
            <div className="order-empty">
              <div className="empty-icon">🛒</div>
              <p>Your order is empty</p>
              <p className="empty-hint">Start talking to Diaa to add items</p>
            </div>
          ) : (
            order.items.map(item => (
              <div key={item.id} className="order-item-row">
                <div className="order-item-qty">{item.quantity}×</div>
                <div className="order-item-info">
                  <div className="order-item-name">{item.menu_item_name}</div>
                  {item.customization_notes && (
                    <div className="order-item-note">{item.customization_notes}</div>
                  )}
                </div>
                <div className="order-item-subtotal">{formatPrice(item.subtotal)}</div>
              </div>
            ))
          )}
        </div>

        {order && order.items.length > 0 && (
          <div className="order-footer">
            <div className="order-divider" />
            <div className="order-total-row">
              <span className="order-total-label">Total</span>
              <span className="order-total-value">{formatPrice(orderTotal)}</span>
            </div>
            <p className="order-hint">
              Say "confirm my order" or tap <strong>End Session</strong> to place it
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
