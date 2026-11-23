"""SQLAlchemy models (doc 07). Enums are stored as strings (portable; validated in code)."""
import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text,
                        UniqueConstraint, Uuid, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JsonType, TimestampMixin, utcnow

FINDING_STATUSES = ("IDLE", "OVER_PROVISIONED", "UNDER_PROVISIONED", "NEEDS_REVIEW", "ACTIVE", "STOPPED",
                    "INSUFFICIENT_DATA", "ERROR")
ACTION_CODES = ("STOP_INSTANCE", "TERMINATE_INSTANCE", "RESIZE", "ENABLE_UNLIMITED_CREDITS",
                "UNDO_STOP", "UNDO_RESIZE", "UNDO_CREDITS")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connections: Mapped[list["AwsConnection"]] = relationship(back_populates="user", cascade="all, delete-orphan",
                                                              passive_deletes=True)


class AwsConnection(TimestampMixin, Base):
    __tablename__ = "aws_connections"
    __table_args__ = (
        Index("uq_conn_user_account", "user_id", "aws_account_id", unique=True,
              postgresql_where=text("aws_account_id IS NOT NULL"),
              sqlite_where=text("aws_account_id IS NOT NULL")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100), default="AWS account")
    external_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role_arn: Mapped[str | None] = mapped_column(String(2048))
    aws_account_id: Mapped[str | None] = mapped_column(String(12))
    enable_actions: Mapped[bool] = mapped_column(Boolean, default=False)
    actions_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|connected|broken|disconnected
    last_error: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regions: Mapped[list] = mapped_column(JsonType, default=list)
    scan_schedule: Mapped[str] = mapped_column(String(10), default="daily")  # off|daily|weekly

    user: Mapped[User] = relationship(back_populates="connections")


class Scan(TimestampMixin, Base):
    __tablename__ = "scans"
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aws_connections.id", ondelete="CASCADE"),
                                                     index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed|partial
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    regions: Mapped[list] = mapped_column(JsonType, default=list)
    total_instances: Mapped[int] = mapped_column(Integer, default=0)
    processed_instances: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_latest", "connection_id", "is_latest"),)
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aws_connections.id", ondelete="CASCADE"))
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    instance_id: Mapped[str] = mapped_column(String(32), index=True)
    region: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256), default="")
    instance_type: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(24))
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 1), default=0)
    confidence_band: Mapped[str] = mapped_column(String(8), default="NONE")
    reason: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[dict | None] = mapped_column(JsonType)
    monthly_saving_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    monthly_delta_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    metrics: Mapped[dict | None] = mapped_column(JsonType)
    idle: Mapped[dict | None] = mapped_column(JsonType)
    underprovisioned: Mapped[dict | None] = mapped_column(JsonType)
    overprovisioned: Mapped[dict | None] = mapped_column(JsonType)
    evidence_steps: Mapped[list | None] = mapped_column(JsonType)
    hourly_series: Mapped[list | None] = mapped_column(JsonType)
    mem_hourly: Mapped[list | None] = mapped_column(JsonType)
    data_quality: Mapped[float | None] = mapped_column(Float)
    hours_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    memory_checked: Mapped[bool | None] = mapped_column(Boolean)
    has_memory_metric: Mapped[bool] = mapped_column(Boolean, default=False)
    action_state: Mapped[str] = mapped_column(String(20), default="none")  # none|in_progress|applied|undone|failed
    dismissed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_forever: Mapped[bool] = mapped_column(Boolean, default=False)
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RemediationAction(TimestampMixin, Base):
    __tablename__ = "remediation_actions"
    __table_args__ = (
        Index("uq_one_active_action_per_instance", "connection_id", "instance_id", unique=True,
              postgresql_where=text("status IN ('pending', 'running')"),
              sqlite_where=text("status IN ('pending', 'running')")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aws_connections.id", ondelete="CASCADE"),
                                                     index=True)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    instance_id: Mapped[str] = mapped_column(String(32))
    instance_name: Mapped[str] = mapped_column(String(256), default="")
    region: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    parent_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|succeeded|failed|rolled_back
    before: Mapped[dict] = mapped_column(JsonType, default=dict)
    after: Mapped[dict] = mapped_column(JsonType, default=dict)
    options: Mapped[dict] = mapped_column(JsonType, default=dict)
    steps_log: Mapped[list] = mapped_column(JsonType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    hourly_saving_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    savings_active: Mapped[bool] = mapped_column(Boolean, default=False)
    savings_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    savings_end_reason: Mapped[str | None] = mapped_column(Text)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    celery_task_id: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()


class SavingsLedger(TimestampMixin, Base):
    __tablename__ = "savings_ledger"
    __table_args__ = (UniqueConstraint("action_id", "date", name="uq_ledger_action_date"),)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aws_connections.id", ondelete="CASCADE"),
                                                     index=True)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("remediation_actions.id", ondelete="CASCADE"))
    instance_id: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(32))
    date: Mapped[date] = mapped_column(Date)
    hours_in_effect: Mapped[float] = mapped_column(Numeric(8, 4))
    hourly_saving_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 4))
    kind: Mapped[str] = mapped_column(String(16))  # STOP|TERMINATE|RESIZE_DOWN|RESIZE_UP


class PriceCache(Base):
    __tablename__ = "price_cache"
    instance_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    region: Mapped[str] = mapped_column(String(32), primary_key=True)
    hourly_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("aws_connections.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JsonType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))



__all__ = ["User", "AwsConnection", "Scan", "Finding", "RemediationAction", "SavingsLedger", "PriceCache",
           "AuditLog", "FINDING_STATUSES", "ACTION_CODES"]
