from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


class AppSetting(db.Model):
    """Instance-global key→value overrides for add-on/env config, editable from the
    UI (e.g. the Ollama AI settings). A stored value takes precedence over the
    add-on configuration; a blank/absent one falls back to it."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
