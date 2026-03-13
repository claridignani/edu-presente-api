# app/models/password_reset_token.py
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_token"

    id: Optional[int] = Field(default=None, primary_key=True)
    idUsuario: int = Field(index=True)
    token: str = Field(index=True, max_length=64)
    expira_en: datetime
    usado: bool = Field(default=False)
    creado_en: datetime = Field(default_factory=datetime.utcnow)