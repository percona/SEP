"""
Tasks API
"""
import logging
from os import getenv
from secrets import token_hex
from typing import List

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .models import (
    Task,
    TaskBaseModel,
    tasks,
)
from sep.authz.casdoor import SESSION_TOKEN_LENGTH
import sep.core.db
from sep.core.utils import get_logger

DEFAULT_DATABASE_DSN = f"{sep.core.db.DEFAULT_DATABASE_DSN}/tasks.db"
DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"

DATABASE_URL = getenv("REPORTS_DATABASE_URL", DEFAULT_DATABASE_DSN)
ORIGINS = getenv("REPORTS_ORIGINS", DEFAULT_ORIGINS).split(",")

database = sep.core.db.get_database(DATABASE_URL)
database.metadata = sep.core.db.get_metadata()
database.engine = sep.core.db.get_engine(DATABASE_URL,
                                         connect_args=sep.core.db.DEFAULT_DATABASE_CONNECT_ARGS)

app = FastAPI()
app.log = get_logger("tasks-api", level=logging.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=token_hex(SESSION_TOKEN_LENGTH),
    session_cookie="fastapi-session",
)


@app.on_event("startup")
async def startup():
    """Prepare the database and application"""
    tasks.to_metadata(database.metadata)
    await sep.core.db.startup(database)


@app.on_event("shutdown")
async def shutdown():
    """Perform a clean shutdown"""
    await database.disconnect()


@app.get(path="/", response_model=List[Task])
async def list_reports():
    """

    :return:
    """
    app.log.debug("Listing reports")
    query = tasks.select()
    return await database.fetch_all(query)
