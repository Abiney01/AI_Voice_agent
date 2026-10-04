import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
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
  addOrderItem,
  removeOrderItem,
  type ChatMessage,
  type Order,
  type MenuItem,
} from '../services/api';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder';
import { getMenuItemImage } from '../config/menuImages';
import { filterAndRankMenu, detectMealPeriod } from '../utils/menuFilter';
import { getComplementaryPairings } from '../utils/pairingHelper';
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

function extractDishesFromText(text: string, menu: MenuItem[]): MenuItem[] {
  if (!text || !menu.length) return [];
  const textLower = text.toLowerCase();
  const matched: MenuItem[] = [];
  const seenIds = new Set<number>();

  const sortedMenu = [...menu].sort((a, b) => b.name.length - a.name.length);

  for (const item of sortedMenu) {
    const nameLower = item.name.toLowerCase();
    const escaped = nameLower.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
    const regex = new RegExp(`\\b${escaped}\\b`, 'i');
    if (regex.test(textLower) || textLower.includes(nameLower)) {
      if (!seenIds.has(item.id)) {
        seenIds.add(item.id);
        matched.push(item);
      }
    }
  }
  return matched;
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

  const [isTyping, setIsTyping]                   = useState(false);
  const [isAgentSpeaking, setIsAgentSpeaking]     = useState(false);
  const [isPaused, setIsPaused]                   = useState(false);
  const [allMenuItems, setAllMenuItems]           = useState<MenuItem[]>([]);
  const [sessionEnded, setSessionEnded]           = useState(false);

  // Dynamic Personalization Controls
  const [activeMealPeriod, setActiveMealPeriod]   = useState<'all' | 'breakfast' | 'brunch' | 'lunch' | 'dinner' | 'snacks'>('all');
  const [selectedDish, setSelectedDish]           = useState<MenuItem | null>(null);
  const [llmRecommendations, setLlmRecommendations] = useState<MenuItem[] | null>(null);

  const audioCtxRef          = useRef<AudioContext | null>(null);
  const activeSourceRef      = useRef<AudioBufferSourceNode | null>(null);
  const scheduledSourcesRef  = useRef<AudioBufferSourceNode[]>([]);
  const playTTSAbortRef      = useRef<AbortController | null>(null);
  const abortControllerRef   = useRef<AbortController | null>(null);
  const isPausedRef          = useRef<boolean>(false);
  const startListeningRef    = useRef<() => void>(() => {});
  const orderRef             = useRef<Order | null>(order);

  useEffect(() => { orderRef.current = order; }, [order]);

  // Redirect if no customer
  useEffect(() => { if (!customer) navigate('/'); }, [customer, navigate]);

  // Auto-detect meal period on initial mount
  useEffect(() => {
    const detected = detectMealPeriod();
    setActiveMealPeriod(detected);
  }, []);

  // Fetch full menu data to score and personalize
  useEffect(() => {
    getMenu()
      .then(items => setAllMenuItems(items))
      .catch(() => showToast('Could not load menu items', 'error'));
  }, [showToast]);

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

  // Stop all scheduled TTS audio
  const stopAllTTS = useCallback(() => {
    playTTSAbortRef.current?.abort();
    scheduledSourcesRef.current.forEach(s => stopAudioSource(s));
    scheduledSourcesRef.current = [];
    activeSourceRef.current = null;
  }, []);

  // Sentence-level progressive TTS
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

  const endVoiceSession = useCallback(() => {
    stopAllTTS();
    setIsAgentSpeaking(false);
    isPausedRef.current = true;
    setSessionEnded(true);
  }, [stopAllTTS]);

  // Initial greeting
  useEffect(() => {
    if (customer && messages.length === 0) {
      const prefs = customer.preferences;
      let prefNote = '';
      if (prefs?.spice_level)     prefNote += ` I know you enjoy ${prefs.spice_level} food.`;
      if (prefs?.favorite_dishes) prefNote += ` Your favourites are ${prefs.favorite_dishes}.`;

      const greeting = customer.is_returning
        ? `Welcome back, ${customer.name || 'friend'}! Great to see you again.${prefNote} What can I get for you today?`
        : `Hi ${customer.name || 'there'}! I'm Diaa, your restaurant concierge. What are you in the mood for today?`;

      setMessages([{ role: 'assistant', content: greeting }]);
      playTTS(greeting);
    }
  }, [customer, messages, setMessages, playTTS]);

  // Extract latest user message for dynamic intent filtering
  const latestUserMsg = useMemo(() => {
    return [...messages].reverse().find(m => m.role === 'user')?.content || '';
  }, [messages]);

  // Initial frequently ordered / favorite dishes (before LLM personalization request)
  const initialFrequentlyOrdered = useMemo(() => {
    if (!allMenuItems.length) return [];

    // 1. Customer's explicit favorites
    const favNames = (customer?.preferences?.favorite_dishes || '')
      .toLowerCase()
      .split(/[,;]+/)
      .map(s => s.trim())
      .filter(Boolean);

    const favItems = allMenuItems.filter(item =>
      favNames.some(fn => item.name.toLowerCase().includes(fn) || fn.includes(item.name.toLowerCase()))
    );

    // 2. Customer's past orders
    const pastNames = (order?.items || []).map(i => i.menu_item_name.toLowerCase());
    const pastItems = allMenuItems.filter(item =>
      pastNames.includes(item.name.toLowerCase()) && !favItems.some(f => f.id === item.id)
    );

    // 3. Signature popular dishes (Biryani, Butter Chicken, Dosa, Espresso, Burgers, Pizza)
    const popularKeywords = ['biryani', 'butter chicken', 'dosa', 'burger', 'pizza', 'tandoori', 'coffee', 'shake'];
    const popularItems = allMenuItems.filter(item =>
      popularKeywords.some(kw => item.name.toLowerCase().includes(kw)) &&
      !favItems.some(f => f.id === item.id) &&
      !pastItems.some(p => p.id === item.id)
    );

    const combined = [...favItems, ...pastItems, ...popularItems, ...allMenuItems];
    const unique: MenuItem[] = [];
    const seen = new Set<number>();
    for (const it of combined) {
      if (!seen.has(it.id)) {
        seen.add(it.id);
        unique.push(it);
      }
    }
    return unique.slice(0, 5);
  }, [allMenuItems, customer?.preferences?.favorite_dishes, order?.items]);

  // Dynamic Recommendations:
  // Shows exact LLM produced dishes once user asks for recommendations; falls back to frequently ordered initially
  const personalizedDishes = useMemo(() => {
    if (llmRecommendations && llmRecommendations.length > 0) {
      return llmRecommendations.slice(0, 5);
    }
    return initialFrequentlyOrdered;
  }, [llmRecommendations, initialFrequentlyOrdered]);

  // Natural Complementary Pairings based on cart items & highlighted dish
  const complementaryPairings = useMemo(() => {
    return getComplementaryPairings(order?.items || [], allMenuItems, selectedDish, 3);
  }, [order?.items, allMenuItems, selectedDish]);

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
        orderRef.current?.id,
        controller.signal,
      );

      const aiMsg: ChatMessage = { role: 'assistant', content: response.message };
      addMessage(aiMsg);

      // Extract and surface exact recommendations produced by LLM
      let newRecs: MenuItem[] = [];
      if (response.recommendations && response.recommendations.length > 0) {
        const recNames = new Set(
          response.recommendations.map((r: any) => (r.name || r).toString().toLowerCase())
        );
        newRecs = allMenuItems.filter(item => recNames.has(item.name.toLowerCase()));
      }
      if (newRecs.length === 0 && response.message) {
        newRecs = extractDishesFromText(response.message, allMenuItems);
      }
      if (newRecs.length > 0) {
        setLlmRecommendations(newRecs.slice(0, 5));
      }

      const hasTerminalEvent =
        response.events?.some(e => e.is_retryable === false) ||
        response.order_actions?.some(a => a.is_retryable === false);

      const orderConfirmedOrCancelled = response.updated_order
        ? response.updated_order.status !== 'active'
        : false;

      const isTerminal = hasTerminalEvent || orderConfirmedOrCancelled;

      if (response.updated_order) {
        setOrder(response.updated_order as Order);
      }

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

  // Restart voice without losing cart
  const handleStartAgain = async () => {
    setLlmRecommendations(null);
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

  // Quick direct add from UI / Pairings
  const handleQuickAdd = async (item: MenuItem) => {
    if (!customer) return;
    try {
      let currentOrder = orderRef.current;
      if (!currentOrder || currentOrder.status !== 'active') {
        currentOrder = await getOrCreateOrder(customer.id);
        setOrder(currentOrder);
      }
      const updated = await addOrderItem(currentOrder.id, item.id, 1);
      setOrder(updated);
      showToast(`Added ${item.name} to order`, 'success');
    } catch {
      showToast('Could not add item to order', 'error');
    }
  };

  const handleQuickRemove = async (itemId: number) => {
    if (!orderRef.current) return;
    try {
      const updated = await removeOrderItem(orderRef.current.id, itemId);
      setOrder(updated);
      showToast('Item removed', 'info');
    } catch {
      showToast('Could not remove item', 'error');
    }
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
      case 'ended':     return order?.status === 'confirmed' ? 'Order Confirmed' : 'Session Complete';
      case 'paused':    return 'Muted';
      case 'listening': return 'Listening...';
      case 'thinking':  return 'Diaa is thinking...';
      case 'speaking':  return 'Diaa is speaking...';
      case 'idle':      return 'Talk to Diaa';
    }
  };

  const getStatusSubtext = () => {
    switch (agentState) {
      case 'ended':     return order?.status === 'confirmed' ? 'Your meal is being prepared with fresh ingredients' : 'Tap "Start Again" to resume';
      case 'paused':    return 'Tap Resume to continue ordering';
      case 'listening': return 'Go ahead, speak naturally with Diaa';
      case 'thinking':  return 'Personalizing your recommendation...';
      case 'speaking':  return 'Tap microphone to interrupt';
      case 'idle':      return 'Order naturally with your voice';
    }
  };

  const initials = customer?.name
    ? customer.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : customer?.phone_number?.slice(-2) || '?';

  const orderTotal = order?.total_amount ?? 0;
  const orbClass = agentState === 'ended' ? 'idle' : agentState;

  return (
    <div className="diaa-layout">

      {/* ═══════════════════════════════════════════════════════
          LEFT FLOATING COMPONENT — Personalized Picks (Max 5)
          ═══════════════════════════════════════════════════════ */}
      <aside className="menu-panel">
        
        {/* Clean, Modern Header */}
        <div className="menu-header">
          <div className="menu-header-titles">
            <h2 className="menu-title">{llmRecommendations ? 'Diaa Recommends' : 'Frequently Ordered'}</h2>
            <span className="menu-subtitle">
              {llmRecommendations ? 'Matched directly from Diaa’s suggestion' : 'Top picks & customer favorites'}
            </span>
          </div>
        </div>

        {/* Dynamic Taste Context Badge */}
        <div className="taste-pill-bar">
          <span className="taste-indicator-pill">
            <span className="pill-dot" /> {llmRecommendations ? 'DIAA PICKS' : `${activeMealPeriod.toUpperCase()} PICKS`}
          </span>
          {customer?.preferences?.spice_level && (
            <span className="taste-pref-pill">
              🌶️ {customer.preferences.spice_level}
            </span>
          )}
        </div>

        {/* Dynamic Recommended Dishes List (Compact & Relevant) */}
        <div className="menu-list">
          {allMenuItems.length === 0 ? (
            <div className="menu-loading">
              <div className="dark-spinner" />
              <span>Selecting dishes for your taste...</span>
            </div>
          ) : personalizedDishes.length === 0 ? (
            <div className="menu-empty-state">
              <p className="empty-title">No matching picks</p>
              <p className="empty-sub">Ask Diaa for recommendations or toggle vegetarian mode.</p>
            </div>
          ) : (
            personalizedDishes.slice(0, 5).map(item => {
              const imageUrl = getMenuItemImage(item);
              const isSelected = selectedDish?.id === item.id;
              const isFav = customer?.preferences?.favorite_dishes?.toLowerCase().includes(item.name.toLowerCase());

              return (
                <div
                  key={item.id}
                  className={`menu-card ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedDish(item)}
                >
                  <div className="menu-card-img-wrap">
                    <img
                      src={imageUrl}
                      alt={item.name}
                      className="menu-card-img"
                      loading="lazy"
                    />
                    <span
                      className={`diet-indicator ${item.is_vegetarian ? 'veg' : 'non-veg'}`}
                      title={item.is_vegetarian ? 'Vegetarian' : 'Non-Vegetarian'}
                    >
                      <span className="dot" />
                    </span>
                  </div>

                  <div className="menu-card-body">
                    <div className="menu-card-top">
                      <div className="menu-item-name-wrap">
                        <h3 className="menu-item-name">{item.name}</h3>
                        {isFav && <span className="fav-star-badge" title="Customer Favorite">★</span>}
                      </div>
                      <span className="menu-item-price">{formatPrice(item.price)}</span>
                    </div>

                    {item.description && (
                      <p className="menu-item-desc">{item.description}</p>
                    )}

                    <div className="menu-card-tags">
                      <span className="badge-cuisine">{item.cuisine}</span>
                      {item.spice_level && (
                        <span className={`badge-spice ${item.spice_level}`}>
                          {item.spice_level === 'mild' ? 'Mild' : item.spice_level === 'medium' ? 'Med' : 'Hot'}
                        </span>
                      )}
                      {item.pairs_with && (
                        <span className="pairs-with-tag" title={`Pairs with: ${item.pairs_with}`}>
                          Pair: {item.pairs_with.split(',')[0]}
                        </span>
                      )}
                    </div>
                  </div>

                  <button
                    className="add-to-cart-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleQuickAdd(item);
                    }}
                    title={`Add ${item.name} to order`}
                    aria-label={`Add ${item.name}`}
                  >
                    +
                  </button>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════
          CENTER PANEL — DIAA Voice Concierge (Voice Only)
          ═══════════════════════════════════════════════════════ */}
      <main className="diaa-center">

        {/* Lighter, clear ambiance overlay to keep culinary background vibrant */}
        <div className="center-overlay" />

        <div className="center-inner-flow">
          {/* Header */}
          <header className="diaa-header">
            <div className="diaa-header-brand">
              <span className="header-brand-crest">✦</span>
              <div className="header-brand-titles">
                <span className="header-brand-name">DIAA</span>
                <span className="header-brand-tag">Voice Restaurant Concierge</span>
              </div>
            </div>

            {customer && (
              <div className="customer-chip">
                <div className="customer-avatar">{initials}</div>
                <div className="customer-meta">
                  <span className="customer-greeting">Welcome,</span>
                  <span className="customer-name">{customer.name || customer.phone_number}</span>
                </div>
              </div>
            )}
          </header>

          {/* Voice-First Concierge Interaction Area */}
          <div className="orb-section">
            <div
              className="orb-wrapper"
              onClick={handleOrbClick}
              role="button"
              tabIndex={0}
              title={getStatusText()}
            >
              <div className={`voice-orb ${orbClass}`}>
                <div className="orb-mic-icon">
                  {recorderState === 'recording' ? (
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                      <rect x="6" y="6" width="12" height="12" rx="2" />
                    </svg>
                  ) : (
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                      <line x1="12" y1="19" x2="12" y2="23"/>
                      <line x1="8" y1="23" x2="16" y2="23"/>
                    </svg>
                  )}
                </div>
              </div>
              <div className="orb-ambient-glow" />
            </div>

            <div className="status-container">
              <h2 className="status-text">{getStatusText()}</h2>
              <p className="status-subtext">{getStatusSubtext()}</p>
            </div>

            {/* Understated capability chips */}
            <div className="feature-chips-row">
              <span className="feature-chip"><span className="chip-bullet">✦</span> Voice Ordering</span>
              <span className="feature-chip"><span className="chip-bullet">✦</span> Taste Learning</span>
              <span className="feature-chip"><span className="chip-bullet">✦</span> Natural Recommendations</span>
            </div>
          </div>

          {/* Understated Voice Controls */}
          <footer className="diaa-controls">
            {sessionEnded ? (
              <button
                id="start-again-btn"
                className="ctrl-btn ctrl-btn--start"
                onClick={handleStartAgain}
              >
                <span className="ctrl-icon">🎙</span>
                <span className="ctrl-label">Start Again</span>
              </button>
            ) : (
              <button
                id="mute-btn"
                className={`ctrl-btn ${isPaused ? 'ctrl-btn--active' : ''}`}
                onClick={handleTogglePause}
                title={isPaused ? 'Resume Conversation' : 'Mute Diaa'}
              >
                <span className="ctrl-icon">{isPaused ? '▶' : '⏸'}</span>
                <span className="ctrl-label">{isPaused ? 'Resume' : 'Mute'}</span>
              </button>
            )}

            <button
              id="end-session-btn"
              className="ctrl-btn ctrl-btn--end"
              onClick={handleEndConversation}
              title="Confirm Order and End Session"
            >
              <span className="ctrl-icon">⏹</span>
              <span className="ctrl-label">End Session</span>
            </button>
          </footer>
        </div>
      </main>

      {/* ═══════════════════════════════════════════════════════
          RIGHT FLOATING COMPONENT — Your Order
          ═══════════════════════════════════════════════════════ */}
      <aside className="order-panel">

        {/* Order Header */}
        <div className="order-header">
          <h2 className="order-title">Your Order</h2>
          <span className={`order-status-pill status-${order?.status || 'active'}`}>
            {(order?.status || 'ACTIVE').toUpperCase()}
          </span>
        </div>

        {/* Order Items List */}
        <div className="order-items-scroll">
          {!order || order.items.length === 0 ? (
            <div className="order-empty">
              <div className="empty-cloche-icon">
                <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 18h18"/>
                  <path d="M4 18a8 8 0 0 1 16 0"/>
                  <path d="M12 6a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"/>
                </svg>
              </div>
              <h3 className="empty-title">No items in order</h3>
              <p className="empty-sub">Speak naturally with Diaa or tap '+' on dishes to begin.</p>
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
                <button
                  className="order-item-del-btn"
                  onClick={() => handleQuickRemove(item.id)}
                  title="Remove item"
                  aria-label={`Remove ${item.menu_item_name}`}
                >
                  ✕
                </button>
              </div>
            ))
          )}
        </div>

        {/* Complementary Pairings Section */}
        {complementaryPairings.length > 0 && (
          <div className="pairings-section">
            <div className="pairings-header">
              <span className="pairings-accent">✦</span>
              <span className="pairings-title">Pairs Wonderfully With:</span>
            </div>
            <div className="pairings-list">
              {complementaryPairings.map(pair => (
                <div key={pair.id} className="pairing-card">
                  <img
                    src={getMenuItemImage(pair)}
                    alt={pair.name}
                    className="pairing-card-thumb"
                  />
                  <div className="pairing-card-info">
                    <span className="pairing-card-name">{pair.name}</span>
                    <span className="pairing-card-price">{formatPrice(pair.price)}</span>
                  </div>
                  <button
                    className="pairing-add-btn"
                    onClick={() => handleQuickAdd(pair)}
                    title={`Add ${pair.name}`}
                  >
                    + Add
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Order Footer & Total */}
        <div className="order-footer">
          <div className="order-total-row">
            <span className="order-total-label">Total</span>
            <span className="order-total-value">{formatPrice(orderTotal)}</span>
          </div>

          <button
            className="place-order-btn"
            onClick={handleEndConversation}
            disabled={!order || order.items.length === 0}
            title={order && order.items.length > 0 ? "Place and confirm your order" : "Add dishes to place order"}
          >
            Place Order
          </button>
        </div>
      </aside>
    </div>
  );
}
