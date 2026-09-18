"""Collecte : scrape une source puis stocke en base (avec déduplication).

Usage :
    python collect.py "développeur python" "Paris" 15
    python collect.py "data analyst" "Lyon" 15 glassdoor
"""
import asyncio
import sys

from sqlalchemy import select, func

from db import init_db, upsert_offers, get_session
from models import Job, JobStatus
from scrapers import IndeedScraper, GlassdoorScraper

SCRAPERS = {"indeed": IndeedScraper, "glassdoor": GlassdoorScraper}


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "développeur python"
    location = sys.argv[2] if len(sys.argv) > 2 else "Paris"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    source = sys.argv[4].lower() if len(sys.argv) > 4 else "indeed"

    if source not in SCRAPERS:
        print(f"Source inconnue : {source}. Choix : {', '.join(SCRAPERS)}")
        return

    init_db()

    print(f"🔍 [{source}] Recherche : '{query}' à '{location}' (max {limit})")
    scraper = SCRAPERS[source](headless=False)
    offers = await scraper.search(query, location, max_results=limit)

    stats = upsert_offers(offers)
    print(f"\n💾 Base mise à jour : "
          f"{stats['inserted']} nouvelle(s), {stats['updated']} déjà connue(s).")

    # Récap global du pipeline.
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(Job))
        print(f"\n📊 Total en base : {total} offre(s)")
        rows = s.execute(
            select(Job.status, func.count())
            .group_by(Job.status)
        ).all()
        for status, count in rows:
            print(f"   • {status.value:<12} : {count}")

        print("\n🆕 Dernières offres NOUVELLES :")
        news = s.scalars(
            select(Job).where(Job.status == JobStatus.NEW)
            .order_by(Job.scraped_at.desc()).limit(8)
        ).all()
        for j in news:
            print(f"   • [{j.id}] {j.title} — {j.company} ({j.location})")


if __name__ == "__main__":
    asyncio.run(main())
