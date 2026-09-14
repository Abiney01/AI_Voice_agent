# AI Voice Restaurant Concierge

A fully local, voice-driven restaurant ordering assistant powered by a fine-tuned LLM, on-device speech recognition, and on-device text-to-speech. Customers speak naturally to place orders, get personalised recommendations, and have their preferences remembered across sessions — all without any cloud voice services.

---

## What It Does

- **Speak to order** — microphone input is transcribed locally with Faster-Whisper
- **Aria responds by voice** — GPT-4o-mini generates the reply; Kokoro ONNX speaks it back
- **Handles ordering end-to-end** — add items, remove items, modify quantities, confirm or cancel the order, all through natural conversation
- **Remembers you** — after each session, the conversation is summarised and stored as a vector-searchable memory; next visit Aria recalls your preferences
- **Personalised recommendations** — 4-tier engine using personal favourites, order history, frequently-bought-together, and similar-customer signals
- **Guardrail layer** — fast regex pre-filter blocks prompt injection and off-domain abuse before any LLM call is made
- **No cloud voice** — Whisper and Kokoro run entirely on the server CPU; no Twilio, no Google TTS, no AWS Polly

---

## Tech Stack

### Frontend

| Technology | Version | Role |
|---|---|---|
| React | 19 | UI framework |
| TypeScript | 6 | Type safety |
| Vite | 8 | Dev server & bundler |
| React Router DOM | 7 | Client-side routing |
| Web Audio API | browser built-in | Gapless TTS playback, sentence-level scheduling |
| MediaRecorder API | browser built-in | Microphone capture |
| Vanilla CSS | — | All styling (no Tailwind) |

### Backend

| Technology | Version | Role |
|---|---|---|
| Python | 3.13 | Runtime |
| FastAPI | latest | Async REST API |
| Uvicorn | latest | ASGI server |
| Prisma (Python) | latest | Type-safe ORM / query builder |
| pydantic-settings | latest | Config from `.env` |

### AI / ML

| Technology | Model | Role |
|---|---|---|
| OpenAI API | `gpt-4o-mini` | Conversation generation, order extraction, preference extraction, memory summarisation |
| Google Gemini API | `gemini-embedding-001` | 768-dimensional text embeddings for semantic memory search |
| Faster-Whisper | `base` (int8, CPU) | On-device speech-to-text |
| Kokoro ONNX | `kokoro-v0_19.onnx` | On-device text-to-speech |

### Database

| Technology | Role |
|---|---|
| PostgreSQL 16 | Primary data store |
| pgvector extension | Vector similarity search for semantic memory and similar-customer recommendations |
| Docker / docker-compose | Database container |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│                                                         │
│  WelcomePage          ChatPage                          │
│  - phone login        - orb voice UI                   │
│  - name capture       - MediaRecorder → WAV blob        │
│                       - Web Audio API (gapless TTS)     │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS / fetch
┌──────────────────────────▼──────────────────────────────┐
│                    FastAPI Backend                        │
│                                                         │
│  POST /customers/identify      ← phone login            │
│  GET  /customers/:id           ← profile refresh        │
│  GET  /menu                    ← full menu              │
│  POST /conversations/chat      ← main chat loop         │
│  POST /conversations/end-session ← save memory         │
│  POST /voice/transcribe        ← Whisper STT            │
│  POST /voice/synthesize        ← Kokoro TTS             │
│  GET  /recommendations/:id     ← 4-tier recs            │
│  POST /orders                  ← create/get order       │
│  POST /orders/:id/confirm      ← confirm order          │
└──┬─────────┬────────┬──────────┬───────────────────────┘
   │         │        │          │
   ▼         ▼        ▼          ▼
OpenAI   Gemini   Whisper    Kokoro
GPT-4o   Embed.   (local)    (local)
  mini    API                ONNX
   │         │
   └────┬────┘
        ▼
   PostgreSQL + pgvector
   ┌──────────────────────┐
   │ customers            │
   │ customer_preferences │
   │ menu_items           │
   │ orders               │
   │ order_items          │
   │ conversation_summaries│
   │   (+ vector column)  │
   └──────────────────────┘
```

---

## Request Pipeline — One Full Voice Turn

```
1. Mic capture (MediaRecorder)
        │
        ▼
2. POST /voice/transcribe  →  Faster-Whisper (beam_size=1, VAD filter)
        │                     returns: transcript text
        ▼
3. Guardrail check (regex, no LLM cost)
   - Prompt injection → reject immediately
   - Off-domain → reject immediately
   - Restaurant query → pass through
        │
        ▼
4. Parallel prefetch (asyncio.gather)
   ├── PostgreSQL: customer + preferences
   ├── PostgreSQL: active order
   ├── Menu cache (10-min TTL)
   └── Gemini embedding → pgvector search → relevant memories
       (skipped on short mid-conversation turns)
        │
        ▼
5. Intent detection (regex, no LLM cost)
   - Order intent detected → run steps 6a + 6b concurrently
   - No order intent      → run step 6a only
        │
        ├── 6a. POST OpenAI /chat/completions  (gpt-4o-mini, timeout=15s)
        │       System prompt: identity + menu + customer context + memories
        │       Returns: Aria's conversational reply
        │
        └── 6b. POST OpenAI /chat/completions  (gpt-4o-mini, timeout=15s)
                Extraction prompt: structured JSON order actions
                Returns: [{action, menu_item_name, quantity, notes}]
        │
        ▼
7. Apply order actions (parallel DB lookups for menu items)
   - add / remove / modify → order_items table
   - confirm → order status = 'confirmed'
   - cancel  → order status = 'cancelled'
        │
        ▼
8. Return ChatResponse to frontend
   {message, order_actions, updated_order}
        │
        ▼ (BackgroundTask — does NOT delay the response)
9. Memory update
   - Summarise conversation (GPT-4o-mini)
   - Embed summary (Gemini)
   - Save to conversation_summaries + pgvector
   - Extract preferences → upsert customer_preferences
        │
        ▼
10. POST /voice/synthesize
    - sanitize_for_tts() strips markdown, emoji, ₹ → "rupees"
    - Kokoro ONNX → WAV bytes
        │
        ▼
11. Sentence-level TTS playback (Web Audio API)
    - Response split into sentences
    - Sentence 1 synthesised → played immediately
    - Sentences 2, 3… synthesised and gaplessly scheduled
    - User hears first audio in ~1 sentence time, not full response time
        │
        ▼
12. Auto-restart microphone → back to step 1
```

---

## Recommendation Engine

The `/recommendations/:customer_id` endpoint returns a prioritised list using four independent signals:

| Priority | Signal | Source |
|---|---|---|
| 1 | Personal favourites | `customer_preferences.favorite_dishes` |
| 2 | Most frequently ordered | `order_items` aggregate query |
| 3 | Frequently bought together | Co-occurrence in confirmed orders |
| 4 | Similar customers | pgvector similarity on preference embeddings |

Duplicate items are excluded across priorities. Each tier returns up to 3 items.

---

## Memory System

After each session ends (`POST /conversations/end-session`), a background task:

1. Sends the full conversation to GPT-4o-mini for summarisation (2-3 sentences)
2. Embeds the summary with `gemini-embedding-001` (768 dimensions)
3. Stores the summary + vector in `conversation_summaries`
4. Extracts structured preferences (spice level, dietary, favourites, dislikes)
5. Upserts `customer_preferences`

On the next visit, a vector search retrieves the 3 most semantically relevant memories from past sessions and injects them into Aria's context. Falls back to the 5 most recent if the embedding API is unavailable.

---

## Database Schema

### `customers`
| Column | Type |
|---|---|
| id | serial PK |
| phone_number | varchar unique |
| name | varchar nullable |
| created_at | timestamptz |
| updated_at | timestamptz |

### `customer_preferences`
| Column | Type |
|---|---|
| id | serial PK |
| customer_id | FK → customers |
| spice_level | varchar nullable |
| allergies | text nullable |
| dietary_preferences | text nullable |
| favorite_dishes | text nullable |
| disliked_dishes | text nullable |

### `menu_items`
| Column | Type |
|---|---|
| id | serial PK |
| name | varchar |
| category | varchar |
| cuisine | varchar |
| description | text nullable |
| price | decimal |
| is_vegetarian | boolean |
| is_vegan | boolean |
| spice_level | varchar nullable |
| allergens | text nullable |
| is_available | boolean |

### `orders`
| Column | Type |
|---|---|
| id | serial PK |
| customer_id | FK → customers |
| status | enum: active / confirmed / cancelled |
| total_amount | decimal |
| created_at | timestamptz |
| updated_at | timestamptz |

### `order_items`
| Column | Type |
|---|---|
| id | serial PK |
| order_id | FK → orders |
| menu_item_id | FK → menu_items |
| menu_item_name | varchar (denormalised) |
| quantity | integer |
| unit_price | decimal |
| customization_notes | text nullable |

### `conversation_summaries`
| Column | Type |
|---|---|
| id | serial PK |
| customer_id | FK → customers |
| summary | text |
| embedding | vector(768) — pgvector |
| created_at | timestamptz |

---

## Project Structure

```
Hackathon Project/
├── docker-compose.yml          ← PostgreSQL + pgvector container
│
├── backend/
│   ├── app/
│   │   ├── main.py             ← FastAPI app, lifespan, CORS, router mounts
│   │   ├── core/
│   │   │   ├── config.py       ← pydantic-settings (.env reader)
│   │   │   └── prisma.py       ← Prisma client singleton
│   │   ├── api/
│   │   │   ├── customers/      ← identify, get profile
│   │   │   ├── menu/           ← list, search
│   │   │   ├── orders/         ← create, get, add item, remove item, confirm
│   │   │   ├── conversations/
│   │   │   │   ├── router.py   ← /chat, /end-session (main pipeline)
│   │   │   │   └── voice_router.py ← /transcribe, /synthesize
│   │   │   └── recommendations/ ← 4-tier recommendation endpoint
│   │   ├── services/
│   │   │   ├── openai/
│   │   │   │   ├── conversation_service.py  ← chat, extraction, summarise, prefs
│   │   │   │   └── prompts.py               ← SYSTEM_PROMPT, all prompt templates
│   │   │   ├── gemini/
│   │   │   │   └── client.py                ← google-generativeai client init
│   │   │   ├── memory/
│   │   │   │   ├── embedding_service.py     ← Gemini embeddings (768-dim)
│   │   │   │   └── memory_service.py        ← store, search, preference update
│   │   │   ├── whisper/
│   │   │   │   └── stt_service.py           ← Faster-Whisper transcription
│   │   │   ├── kokoro/
│   │   │   │   └── tts_service.py           ← Kokoro ONNX synthesis + sanitizer
│   │   │   ├── guardrails/
│   │   │   │   └── domain_guard.py          ← injection + off-domain regex filter
│   │   │   ├── recommendations/
│   │   │   │   └── recommendation_service.py ← 4-priority engine
│   │   │   ├── menu_service.py
│   │   │   ├── order_service.py
│   │   │   └── customer_service.py
│   │   ├── repositories/
│   │   │   ├── customer_repository.py
│   │   │   ├── menu_repository.py
│   │   │   ├── order_repository.py
│   │   │   └── memory_repository.py
│   │   └── schemas/
│   │       ├── conversation.py
│   │       ├── customer.py
│   │       ├── menu.py
│   │       └── order.py
│   ├── seed_menu.py            ← Seeds menu_items on first startup
│   └── prisma/
│       └── schema.prisma       ← DB schema + pgvector
│
└── frontend/
    └── src/
        ├── main.tsx
        ├── App.tsx             ← Router setup
        ├── index.css           ← All styles (dark theme, glassmorphism)
        ├── pages/
        │   ├── WelcomePage.tsx ← Phone login / name capture
        │   └── ChatPage.tsx    ← Orb UI, voice loop, chat, order panel
        ├── services/
        │   └── api.ts          ← All fetch wrappers + TypeScript types
        ├── context/
        │   ├── AppContext.tsx  ← Global state provider
        │   ├── contextTypes.ts
        │   └── useApp.ts
        └── hooks/
            └── useVoiceRecorder.ts ← MediaRecorder lifecycle
```

---

## Local Setup

### Prerequisites

- **Python 3.11+**
- **Node.js 20+**
- **Docker** (for PostgreSQL + pgvector)

---

### 1. Start the Database

Run Docker Compose from the project root:

```bash
docker compose up -d
```

> [!NOTE]
> The database container automatically initializes the `vector` extension on first boot via [init.sql](file:///d:/Voice-Agent/init.sql). If you ever reset your database (`prisma migrate reset`), re-enable it manually:
> ```bash
> docker exec avrc-postgres psql -U postgres -d avrc -c "CREATE EXTENSION IF NOT EXISTS vector;"
> ```

---

### 2. Backend Setup

From the [backend](file:///d:/Voice-Agent/backend) directory:

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

#### Configure Environment Variables
Create your `backend/.env` (based on [backend/.env.example](file:///d:/Voice-Agent/backend/.env.example)):
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/avrc
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
WHISPER_MODEL_SIZE=base
KOKORO_VOICE=af_heart
```

#### Generate Prisma Client & Push Database Schema
Prisma generated client code (`backend/app/prisma_client`) is git-ignored and must be compiled locally:
```bash
prisma generate
prisma db push
```

#### Kokoro TTS Voice Models (Speech Output)
Model files (`*.onnx` and `*.bin`) are excluded from Git due to file size limits. 

> [!TIP]
> **What if you don't download Kokoro files right away?**
> The backend will still boot and operate smoothly! Text chat, menu queries, ordering logic, and recommendations will function normally. The TTS endpoint (`/voice/synthesize`) will safely return a short silence and log a warning until the model files are placed in `backend/`.

To enable on-device voice synthesis, place the model files in `backend/`:

* **Option A: Kokoro v1.0 (Latest & Recommended — 54 voices, natural prosody)**
  * **PowerShell (Windows)**:
    ```powershell
    Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -OutFile "kokoro-v1.0.onnx"
    Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -OutFile "voices-v1.0.bin"
    ```
  * **cURL / Wget (macOS / Linux)**:
    ```bash
    curl -L -o kokoro-v1.0.onnx "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    curl -L -o voices-v1.0.bin "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    ```

* **Option B: Kokoro v0.19 (Legacy)**
  * **PowerShell (Windows)**:
    ```powershell
    Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx" -OutFile "kokoro-v0_19.onnx"
    Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin" -OutFile "voices.bin"
    ```

#### Faster-Whisper STT (Speech Input)
No manual download is required for Faster-Whisper. On the first server startup, it will automatically download the `base` model (~140 MB) from Hugging Face and cache it locally in your user cache (`~/.cache/huggingface/hub/`).

#### Start the Backend Server:
```bash
python -m uvicorn app.main:app --reload --port 8000
```
*(The menu is automatically seeded with 41 Indian and American dishes on first startup).*

---

### 3. Frontend Setup

From the [frontend](file:///d:/Voice-Agent/frontend) directory:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `OPENAI_API_KEY` | ✅ | — | GPT-4o-mini (chat + extraction) |
| `GEMINI_API_KEY` | ✅ | — | Gemini embeddings for memory search |
| `OPENAI_MODEL` | ❌ | `gpt-4o-mini` | Override chat model |
| `WHISPER_MODEL_SIZE` | ❌ | `base` | Whisper model size |
| `WHISPER_DEVICE` | ❌ | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | ❌ | `int8` | `int8`, `float16`, `float32` |
| `KOKORO_VOICE` | ❌ | `af_heart` | Kokoro voice ID |
| `KOKORO_LANG` | ❌ | `en-us` | TTS language |
| `CORS_ORIGINS` | ❌ | `http://localhost:5173` | Comma-separated allowed origins |

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/customers/identify` | Login or register by phone number |
| `GET` | `/customers/:id` | Get customer profile + preferences |
| `GET` | `/menu` | Get full available menu |
| `GET` | `/menu/search?q=...` | Search menu by name/category/description |
| `POST` | `/orders` | Get or create active order |
| `GET` | `/orders/:id` | Get specific order |
| `POST` | `/orders/:id/items` | Add item to order |
| `DELETE` | `/orders/:id/items/:itemId` | Remove item from order |
| `PUT` | `/orders/:id/confirm` | Confirm order |
| `GET` | `/orders/customer/:id` | Get customer order history |
| `POST` | `/conversations/chat` | Send message, receive Aria's reply + order actions |
| `POST` | `/conversations/end-session` | Save session memory (background) |
| `POST` | `/voice/transcribe` | Transcribe audio blob → text (Faster-Whisper) |
| `POST` | `/voice/synthesize` | Convert text → WAV audio (Kokoro) |
| `GET` | `/recommendations/:id` | Get 4-tier personalised recommendations |
| `GET` | `/health` | Health check |

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Performance Characteristics

| Optimisation | Effect |
|---|---|
| Whisper `beam_size=1` (greedy) | ~40% faster STT vs beam_size=5 |
| Intent detection before extraction | Extraction LLM call skipped on ~50% of turns |
| Conditional memory retrieval | Gemini embedding skipped for short mid-conversation turns |
| asyncio.gather for prefetch | Customer + menu + order + memories fetched in parallel |
| Menu cache (10-min TTL) | Zero DB reads on repeated menu lookups |
| Parallel item pre-fetch | N+1 menu DB queries collapsed into a single gather |
| Skip order reload | No extra DB round-trip when no actions were applied |
| Sentence-splitting TTS | First audio plays after ~1 sentence synthesis instead of full response |
| Memory updates as BackgroundTask | Session end never blocks the API response |
| Embedding timeout (5s) | Slow Gemini calls gracefully fall back to recent memories |
| LLM timeout (15s) | Hung OpenAI calls never block indefinitely |

---

## Guardrail System

All messages pass through `domain_guard.py` **before** any LLM or DB call:

1. **Length check** — messages over 500 characters are rejected
2. **Control character strip** — removes null bytes and other non-printable characters
3. **Prompt injection detection** — 20+ regex patterns block "ignore previous instructions", "act as", "jailbreak", etc.
4. **Restaurant fast-pass** — 50+ patterns covering food terms, ordering verbs, recommendation phrases, and common questions short-circuit the off-domain check
5. **Off-domain check** — coding, maths, essay writing, general knowledge, medical, and financial queries are rejected with a soft redirect

True restaurant questions (`"what do you recommend?"`, `"do you have anything spicy?"`, `"what's popular?"`) always fast-pass through to the LLM.

---

## What Is Not Included

- Payment processing
- POS / kitchen integrations
- Delivery tracking
- Real-time inventory management
- Multi-restaurant support
- Authentication / JWT (phone number is the only identity)
- Admin dashboard
