"""Collecte planifiée : lance toutes les recherches de recherches.json,
stocke en base (dédup), recalcule les scores, et journalise le tout.

Conçu pour être exécuté sans surveillance (Planificateur de tâches Windows).
Par défaut en mode headless (invisible). Si Indeed bloque trop, repasse
en fenêtre visible avec  --show.

Usage :
    python daily_collect.py
    python daily_collect.py --show     # navigateur visible
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func

from db import init_db, upsert_offers, get_session
from models import Job, JobStatus
from matching import load_profil, score_offer
from scrapers import IndeedScraper, GlassdoorScraper

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "data" / "recherches.json"
LOG = ROOT / "data" / "collecte.log"

SCRAPERS = {"indeed": IndeedScraper, "glassdoor": GlassdoorScraper}


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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


async def main() -> None:
    headless = "--show" not in sys.argv
    init_db()
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    recherches = conf.get("recherches", [])

    log(f"=== Début collecte planifiée ({len(recherches)} recherches, "
        f"headless={headless}) ===")
    total_new = total_upd = 0

    for r in recherches:
        source = r.get("source", "indeed").lower()
        cls = SCRAPERS.get(source)
        if not cls:
            log(f"  ! source inconnue ignorée : {source}")
            continue
        try:
            scraper = cls(headless=headless)
            offers = await scraper.search(
                r["query"], r.get("location", ""), max_results=r.get("limit", 15))
            stats = upsert_offers(offers)
            total_new += stats["inserted"]
            total_upd += stats["updated"]
            log(f"  [{source}] '{r['query']}' @ {r.get('location','')} : "
                f"{len(offers)} trouvées, {stats['inserted']} nouvelles")
        except Exception as exc:  # noqa: BLE001
            log(f"  ! erreur sur '{r.get('query')}' ({source}) : {exc}")

    n = _rescore()
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(Job)) or 0
        new_count = s.scalar(
            select(func.count()).select_from(Job)
            .where(Job.status == JobStatus.NEW)) or 0

    log(f"=== Fin : {total_new} nouvelle(s), {total_upd} maj, "
        f"{n} offres scorées. Base : {total} total, {new_count} à traiter. ===")


if __name__ == "__main__":
    asyncio.run(main())
