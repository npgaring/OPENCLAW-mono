"""UsedExecutionToken table — replay protection."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlmodel import Field, SQLModel


class UsedExecutionToken(SQLModel, table=True):
    __tablename__ = "used_execution_tokens"

    token_hash: str = Field(primary_key=True)
    task_id: UUID = Field(sa_column=Column(PgUUID(as_uuid=True), index=True, nullable=False))
    used_at: datetime = Field(default_factory=datetime.utcnow)
