"""
FastAPI Application Entrypoint
"""

import os
from dotenv import load_dotenv

# Pre-load environment variables before importing langchain
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core.config import settings
from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router

app = FastAPI(
    title="Yamaha Energy AI Assistant API",
    description="Backend AI Assistant for Yamaha EMS querying, diagnostics, and root-cause analysis",
    version="1.0.0"
)

# Enable CORS for frontend integration (React, Streamlit, Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(chat_router, prefix="/api")

@app.get("/")
def root():
    return {
        "message": "Welcome to Yamaha Energy AI Assistant API",
        "docs": "/docs",
        "health": "/api/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
