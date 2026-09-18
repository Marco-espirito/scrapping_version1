"""API FastAPI : expose les offres, le suivi de statut et la collecte."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_

from db import init_db, get_session, upsert_offers
from models import CollectionTask, Job, JobStatus
from matching import load_profil, score_offer, PROFIL_PATH
from scrapers import IndeedScraper, GlassdoorScraper
from scrapers.base import JobOffer

SCRAPERS = {"indeed": IndeedScraper, "glassdoor": GlassdoorScraper}
COLLECT_LOCK = asyncio.Lock()
SCRAPER_HEADLESS = os.getenv("SCRAPER_HEADLESS", "false").lower() in {
    "1", "true", "yes", "on",
}
COLLECTOR_MODE = os.getenv("COLLECTOR_MODE", "direct").strip().lower()
AGENT_TOKEN = os.getenv("JOBAPPLY_AGENT_TOKEN", "")

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


class OfferIn(BaseModel):
    source: Literal["indeed", "glassdoor"]
    external_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=4000)
    description: str = Field(default="", max_length=100_000)
    salary: str = Field(default="", max_length=200)
    contract_type: str = Field(default="", max_length=100)
    posted_at: str = Field(default="", max_length=100)


class AgentResultIn(BaseModel):
    offers: list[OfferIn] = Field(max_length=100)


class AgentFailureIn(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


def _task_payload(task: CollectionTask) -> dict:
    return {
        "task_id": task.public_id,
        "status": task.status,
        "query": task.query,
        "location": task.location,
        "limit": task.limit,
        "source": task.source,
        "scraped": task.scraped,
        "inserted": task.inserted,
        "updated": task.updated,
        "error": task.error,
    }


def _require_agent(request: Request) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(503, "Agent local non configuré")
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied, AGENT_TOKEN
    ):
        raise HTTPException(401, "Jeton agent invalide")


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
    """Lance localement ou met la collecte en attente pour l'agent PC."""
    if COLLECTOR_MODE == "agent":
        if not AGENT_TOKEN:
            raise HTTPException(503, "Agent local non configuré")
        task = CollectionTask(
            public_id=str(uuid.uuid4()),
            query=payload.query.strip(),
            location=payload.location.strip(),
            limit=payload.limit,
            source=payload.source,
        )
        with get_session() as s:
            s.add(task)
            s.commit()
            s.refresh(task)
            result = _task_payload(task)
        result["mode"] = "agent"
        return JSONResponse(result, status_code=202)

    if COLLECT_LOCK.locked():
        raise HTTPException(409, "Une collecte est déjà en cours")
    async with COLLECT_LOCK:
        cls = SCRAPERS[payload.source]
        scraper = cls(headless=SCRAPER_HEADLESS)
        offers = await scraper.search(
            payload.query.strip(), payload.location.strip(),
            max_results=payload.limit,
        )
        stats_ = upsert_offers(offers)
        _rescore()
        return {"scraped": len(offers), **stats_}


@app.get("/api/collect/{task_id}")
def collection_status(task_id: str):
    with get_session() as s:
        task = s.scalar(
            select(CollectionTask).where(CollectionTask.public_id == task_id)
        )
        if not task:
            raise HTTPException(404, "Collecte introuvable")
        return _task_payload(task)


@app.get("/api/agent/tasks/next")
def agent_next_task(request: Request):
    _require_agent(request)
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=30)
    with get_session() as s:
        task = s.scalar(
            select(CollectionTask)
            .where(or_(
                CollectionTask.status == "pending",
                (CollectionTask.status == "running")
                & (CollectionTask.started_at < stale_before),
            ))
            .order_by(CollectionTask.created_at.asc())
            .limit(1)
        )
        if not task:
            return JSONResponse(status_code=204, content=None)
        task.status = "running"
        task.started_at = now
        task.error = ""
        s.commit()
        s.refresh(task)
        return _task_payload(task)


@app.post("/api/agent/tasks/{task_id}/complete")
def agent_complete_task(
    task_id: str, payload: AgentResultIn, request: Request
):
    _require_agent(request)
    with get_session() as s:
        task = s.scalar(
            select(CollectionTask).where(CollectionTask.public_id == task_id)
        )
        if not task:
            raise HTTPException(404, "Collecte introuvable")
        if task.status == "completed":
            return _task_payload(task)
        if any(offer.source != task.source for offer in payload.offers):
            raise HTTPException(400, "La source d'une offre ne correspond pas")

        offers = [JobOffer(**offer.model_dump()) for offer in payload.offers]
        stats_ = upsert_offers(offers)
        _rescore()
        task.status = "completed"
        task.scraped = len(offers)
        task.inserted = stats_["inserted"]
        task.updated = stats_["updated"]
        task.finished_at = datetime.now(timezone.utc)
        s.commit()
        s.refresh(task)
        return _task_payload(task)


@app.post("/api/agent/tasks/{task_id}/fail")
def agent_fail_task(
    task_id: str, payload: AgentFailureIn, request: Request
):
    _require_agent(request)
    with get_session() as s:
        task = s.scalar(
            select(CollectionTask).where(CollectionTask.public_id == task_id)
        )
        if not task:
            raise HTTPException(404, "Collecte introuvable")
        task.status = "failed"
        task.error = payload.error
        task.finished_at = datetime.now(timezone.utc)
        s.commit()
        s.refresh(task)
        return _task_payload(task)


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
