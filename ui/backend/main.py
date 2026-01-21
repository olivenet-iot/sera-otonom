"""
Sera Otonom - AI Brain API
FastAPI backend for AI Brain Monitoring Panel
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import logging

from .schemas import HealthResponse, InfoResponse, BrainMode
from .routes import brain, control
from .dependencies import get_brain_instance, get_current_mode

__version__ = "0.1.0"
logger = logging.getLogger(__name__)

_start_time: datetime = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    global _start_time
    _start_time = datetime.utcnow()
    logger.info("AI Brain API starting...")
    yield
    logger.info("AI Brain API shutting down...")


app = FastAPI(
    title="Sera Otonom - AI Brain API",
    description="AI-Powered Greenhouse Automation Brain Monitoring API",
    version=__version__,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(brain.router, prefix="/api/brain", tags=["brain"])
app.include_router(control.router, prefix="/api/control", tags=["control"])


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """API health check"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat() + "Z",
        version=__version__
    )


@app.get("/api/info", response_model=InfoResponse, tags=["info"])
async def get_info():
    """Get system information"""
    brain = get_brain_instance()
    uptime = int((datetime.utcnow() - _start_time).total_seconds()) if _start_time else 0

    return InfoResponse(
        version=__version__,
        uptime_seconds=uptime,
        brain_status="running" if brain and brain.is_running else "stopped",
        mode=BrainMode(get_current_mode())
    )
