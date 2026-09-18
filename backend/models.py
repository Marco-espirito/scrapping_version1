"""Modèle de données SQLAlchemy : offres + suivi des candidatures."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, DateTime, Integer, Enum, UniqueConstraint, Float,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    """Cycle de vie d'une offre dans le pipeline de candidature."""
    NEW = "nouvelle"          # vient d'être scrapée
    TO_APPLY = "a_postuler"   # validée pour candidature
    APPLIED = "postulee"      # candidature envoyée
    REJECTED = "refusee"      # refus / non retenue
    IGNORED = "ignoree"       # écartée manuellement


class Job(Base):
    __tablename__ = "jobs"
    # Une même offre = (source, external_id) -> déduplication.
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_extid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)

    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    contract_type: Mapped[str] = mapped_column(String(100), default="")
    posted_at: Mapped[str] = mapped_column(String(100), default="")

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.NEW, index=True
    )
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")

    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.source}:{self.external_id} {self.title!r}>"


class CollectionTask(Base):
    """Demande de collecte exécutée par l'agent installé sur le PC."""

    __tablename__ = "collection_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True
    )
    query: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200), default="")
    limit: Mapped[int] = mapped_column(Integer, default=15)
    source: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    scraped: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
