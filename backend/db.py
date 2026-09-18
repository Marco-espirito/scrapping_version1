"""Connexion à la base + helpers de stockage avec déduplication."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from models import Base, Job, JobStatus
from scrapers.base import JobOffer

DATA_DIR = Path(os.getenv(
    "JOBAPPLY_DATA_DIR",
    Path(__file__).resolve().parents[1] / "data",
)).resolve()
DB_PATH = DATA_DIR / "jobs.db"

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Crée les tables si elles n'existent pas."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()


def upsert_offers(offers: list[JobOffer]) -> dict[str, int]:
    """Insère les nouvelles offres, met à jour les existantes.

    Déduplication sur (source, external_id). Le statut et les notes d'une
    offre déjà connue ne sont JAMAIS écrasés (on ne perd pas le suivi).

    Retourne {"inserted": x, "updated": y}.
    """
    inserted = updated = 0
    with get_session() as s:
        for off in offers:
            existing = s.scalar(
                select(Job).where(
                    Job.source == off.source,
                    Job.external_id == off.external_id,
                )
            )
            if existing is None:
                s.add(Job(
                    source=off.source,
                    external_id=off.external_id,
                    title=off.title,
                    company=off.company,
                    location=off.location,
                    url=off.url,
                    description=off.description,
                    salary=off.salary,
                    contract_type=off.contract_type,
                    posted_at=off.posted_at,
                    status=JobStatus.NEW,
                ))
                inserted += 1
            else:
                # Rafraîchit les champs descriptifs, garde le suivi humain.
                existing.title = off.title or existing.title
                existing.company = off.company or existing.company
                existing.location = off.location or existing.location
                existing.url = off.url or existing.url
                existing.salary = off.salary or existing.salary
                existing.contract_type = off.contract_type or existing.contract_type
                existing.posted_at = off.posted_at or existing.posted_at
                if off.description:
                    existing.description = off.description
                existing.scraped_at = datetime.now(timezone.utc)
                updated += 1
        s.commit()
    return {"inserted": inserted, "updated": updated}
