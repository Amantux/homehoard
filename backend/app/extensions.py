"""Shared extension instances."""
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)

# Rate limiter — keyed on the client IP (see PROXY_HOPS for X-Forwarded-For
# handling). Sensitive endpoints opt in via @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address, default_limits=[])
