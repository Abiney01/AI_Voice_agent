import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.prisma import prisma
from app.api.customers.router import router as customers_router
from app.api.menu.router import router as menu_router
from app.api.orders.router import router as orders_router
from app.api.conversations.router import router as conversations_router
from app.api.conversations.voice_router import router as voice_router
from app.api.recommendations.router import router as recommendations_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    # ── Database ──────────────────────────────────────────────────────────────
    logger.info("Connecting to database...")
    await prisma.connect()
    logger.info("Database connection established.")

    # ── Seed menu if empty ────────────────────────────────────────────────────
    from app.services.menu_service import MenuService
    svc = MenuService()
    if not await svc.is_seeded():
        logger.info("Seeding menu...")
        from seed_menu import seed_menu
        await seed_menu()
        logger.info("Menu seeded successfully.")

    # ── Preload ML models ─────────────────────────────────────────────────────
    # Load Whisper and Kokoro in thread-pool executors so model weight loading
    # (which can take 3-10 seconds) happens at startup, not on the first request.
    from app.services.whisper.stt_service import get_whisper_model
    from app.services.kokoro.tts_service import get_kokoro_model

    logger.info("Preloading ML models (Whisper + Kokoro)...")
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        loop.run_in_executor(None, get_whisper_model),
        loop.run_in_executor(None, get_kokoro_model),
    )
    logger.info("ML models ready.")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Disconnecting database...")
    await prisma.disconnect()
    logger.info("Shutting down AI Voice Restaurant Concierge backend.")


app = FastAPI(
    title="AI Voice Restaurant Concierge",
    description="Conversational AI system for voice-based restaurant ordering with personalization.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    logger.error(f"Validation error for path: {request.url.path}")
    logger.error(f"Body: {body.decode()}")
    logger.error(f"Errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body.decode()},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# Routers
app.include_router(customers_router)
app.include_router(menu_router)
app.include_router(orders_router)
app.include_router(conversations_router)
app.include_router(voice_router)
app.include_router(recommendations_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "AI Voice Restaurant Concierge"}


@app.get("/", tags=["health"])
async def root():
    return {
        "message": "AI Voice Restaurant Concierge API",
        "docs": "/docs",
        "redoc": "/redoc",
    }
