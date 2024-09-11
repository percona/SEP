"""Define the main API routes."""

from fastapi import APIRouter

from app.api.routes import oauth
from app.api.routes import users

api_router = APIRouter()
api_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
