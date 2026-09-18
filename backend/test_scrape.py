"""Test du scraper Indeed en autonome.

Usage :
    python test_scrape.py "développeur python" "Paris" 15
"""
import asyncio
import json
import sys
from pathlib import Path

from scrapers import IndeedScraper

OUT = Path(__file__).resolve().parents[1] / "data" / "offres_indeed.json"


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "développeur python"
    location = sys.argv[2] if len(sys.argv) > 2 else "Paris"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 15

    print(f"🔍 Recherche : '{query}' à '{location}' (max {limit})")
    scraper = IndeedScraper(headless=False)
    offers = await scraper.search(query, location, max_results=limit)

    data = [o.to_dict() for o in offers]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ {len(offers)} offres récupérées -> {OUT}")
    for o in offers[:10]:
        print(f"  • {o.title} — {o.company} ({o.location}) {o.salary}")


if __name__ == "__main__":
    asyncio.run(main())
