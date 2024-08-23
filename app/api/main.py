"""Define the main API routes."""

from fastapi import APIRouter

from app.api.routes import oauth

api_router = APIRouter()
api_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
