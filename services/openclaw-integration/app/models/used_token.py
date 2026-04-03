"""UsedExecutionToken table — replay protection."""
from datetime import datetime

from sqlmodel import Field, SQLModel


class UsedExecutionToken(SQLModel, table=True):
    __tablename__ = "used_execution_tokens"

    token_hash: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    used_at: datetime = Field(default_factory=datetime.utcnow)
