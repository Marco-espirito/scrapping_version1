"""API FastAPI : expose les offres, le suivi de statut et la collecte."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from db import init_db, get_session, upsert_offers
from models import Job, JobStatus
from matching import load_profil, score_offer, PROFIL_PATH
from scrapers import IndeedScraper, GlassdoorScraper

SCRAPERS = {"indeed": IndeedScraper, "glassdoor": GlassdoorScraper}
COLLECT_LOCK = asyncio.Lock()

app = FastAPI(title="JobApply API")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Autorise le dashboard React (Vite) en dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------- Schémas ----------
class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: str
    url: str
    salary: str
    status: str
    match_score: float
    notes: str

    @classmethod
    def from_orm_job(cls, j: Job) -> "JobOut":
        return cls(
            id=j.id, source=j.source, title=j.title, company=j.company,
            location=j.location, url=j.url, salary=j.salary,
            status=j.status.value, match_score=j.match_score, notes=j.notes,
        )


class JobUpdate(BaseModel):
    status: JobStatus | None = None
    notes: str | None = None


class CollectIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    limit: int = Field(default=15, ge=1, le=100)
    source: Literal["indeed", "glassdoor"] = "indeed"


# ---------- Endpoints ----------
@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    min_score: float = Query(default=0.0, ge=0.0, le=100.0),
    sort: Literal["score", "date"] = "score",
):
    with get_session() as s:
        stmt = select(Job).where(Job.match_score >= min_score)
        if status:
            stmt = stmt.where(Job.status == status)
        stmt = stmt.order_by(
            Job.scraped_at.desc() if sort == "date" else Job.match_score.desc()
        )
        return [JobOut.from_orm_job(j) for j in s.scalars(stmt).all()]


@app.get("/api/stats")
def stats():
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(Job)) or 0
        rows = s.execute(
            select(Job.status, func.count()).group_by(Job.status)
        ).all()
        by_status = {st.value: c for st, c in rows}
        return {"total": total, "by_status": by_status}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.patch("/api/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: int, payload: JobUpdate):
    with get_session() as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Offre introuvable")
        if payload.status is not None:
            job.status = payload.status
            if payload.status == JobStatus.APPLIED and job.applied_at is None:
                job.applied_at = datetime.now(timezone.utc)
        if payload.notes is not None:
            job.notes = payload.notes
        s.commit()
        return JobOut.from_orm_job(job)


@app.post("/api/collect")
async def collect(payload: CollectIn):
    """Scrape la source choisie et stocke. (Ouvre une fenêtre Chromium.)"""
    if COLLECT_LOCK.locked():
        raise HTTPException(409, "Une collecte est déjà en cours")
    async with COLLECT_LOCK:
        cls = SCRAPERS[payload.source]
        scraper = cls(headless=False)
        offers = await scraper.search(
            payload.query.strip(), payload.location.strip(),
            max_results=payload.limit,
        )
        stats_ = upsert_offers(offers)
        _rescore()
        return {"scraped": len(offers), **stats_}


@app.post("/api/rank")
def rank():
    return {"updated": _rescore()}


def _rescore() -> int:
    profil = load_profil()
    with get_session() as s:
        jobs = s.scalars(select(Job)).all()
        for j in jobs:
            score, _ = score_offer({
                "title": j.title, "company": j.company,
                "location": j.location, "description": j.description,
                "salary": j.salary,
            }, profil)
            j.match_score = score
        s.commit()
        return len(jobs)


@app.get("/api/profil")
def get_profil():
    return load_profil()


@app.put("/api/profil")
def put_profil(profil: dict):
    PROFIL_PATH.write_text(
        json.dumps(profil, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _rescore()
    return {"ok": True}
