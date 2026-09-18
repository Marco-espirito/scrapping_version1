"""Agent local : exécute les collectes cloud avec le navigateur du PC."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from scrapers import GlassdoorScraper, IndeedScraper

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.agent")

API_URL = os.getenv("JOBAPPLY_API_URL", "").rstrip("/")
AGENT_TOKEN = os.getenv("JOBAPPLY_AGENT_TOKEN", "")
POLL_SECONDS = max(2, int(os.getenv("JOBAPPLY_AGENT_POLL_SECONDS", "5")))
SCRAPERS = {"indeed": IndeedScraper, "glassdoor": GlassdoorScraper}


def api_request(method: str, path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        API_URL + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {AGENT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "JobApply-Local-Agent/1.0",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            if response.status == 204:
                return None
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc


async def execute(task: dict) -> None:
    task_id = task["task_id"]
    source = task["source"]
    print(
        f"\n🔎 Collecte {source}: {task['query']} — "
        f"{task['location']} ({task['limit']} max)"
    )
    try:
        scraper = SCRAPERS[source](headless=False)
        offers = await scraper.search(
            task["query"], task["location"], max_results=task["limit"]
        )
        if not offers:
            raise RuntimeError(
                "Aucune offre détectée. La source affiche peut-être un "
                "CAPTCHA ou une fenêtre de connexion dans Chromium."
            )
        result = await asyncio.to_thread(
            api_request,
            "POST",
            f"/api/agent/tasks/{task_id}/complete",
            {"offers": [offer.to_dict() for offer in offers]},
        )
        print(
            f"✅ {result['scraped']} offre(s), "
            f"{result['inserted']} nouvelle(s), {result['updated']} mise(s) à jour"
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"❌ {message}")
        try:
            await asyncio.to_thread(
                api_request,
                "POST",
                f"/api/agent/tasks/{task_id}/fail",
                {"error": message[:2000]},
            )
        except Exception as report_exc:  # noqa: BLE001
            print(f"Impossible de signaler l'échec: {report_exc}")


async def run() -> None:
    if not API_URL or not AGENT_TOKEN:
        print(
            "Configuration manquante. Copie .env.agent.example vers "
            ".env.agent puis renseigne JOBAPPLY_AGENT_TOKEN."
        )
        sys.exit(1)

    print(f"🟢 Agent JobApply connecté à {API_URL}")
    print("Laisse cette fenêtre ouverte. Ctrl+C pour arrêter.")
    while True:
        try:
            task = await asyncio.to_thread(
                api_request, "GET", "/api/agent/tasks/next"
            )
            if task:
                await execute(task)
            else:
                await asyncio.sleep(POLL_SECONDS)
        except (URLError, TimeoutError, RuntimeError) as exc:
            print(f"⚠️ Connexion impossible: {exc}. Nouvel essai dans 15 s.")
            await asyncio.sleep(15)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nAgent arrêté.")
