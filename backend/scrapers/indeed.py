"""Scraper Indeed basé sur Playwright.

Indeed protège ses pages avec Cloudflare + détection comportementale.
Stratégies utilisées ici pour limiter les blocages :
  - vrai navigateur Chromium (pas de mode "headless" détectable par défaut)
  - contexte persistant (cookies gardés entre les runs -> moins de challenges)
  - user-agent et locale réalistes
  - délais aléatoires entre les actions

⚠️ Le scraping d'Indeed est contraire à ses CGU. À utiliser pour un usage
personnel/éducatif et avec parcimonie (rythme lent, volumes faibles).
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page

from .base import BaseScraper, JobOffer, chromium_args

# Domaine FR ; mets "www.indeed.com" pour les US, etc.
BASE_URL = "https://fr.indeed.com"

# Le contexte persistant stocke les cookies -> moins de captchas au 2e run.
DATA_DIR = Path(os.getenv(
    "JOBAPPLY_DATA_DIR",
    Path(__file__).resolve().parents[2] / "data",
)).resolve()
USER_DATA_DIR = DATA_DIR / "browser_indeed"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def _human_pause(a: float = 0.6, b: float = 1.8) -> None:
    await asyncio.sleep(random.uniform(a, b))


class IndeedScraper(BaseScraper):
    name = "indeed"

    def __init__(
        self, headless: bool = False, fetch_descriptions: bool = True
    ) -> None:
        # headless=False recommandé : Indeed bloque plus souvent le headless.
        self.headless = headless
        # Si True, visite chaque offre pour récupérer le texte complet
        # (meilleur scoring, mais plus lent et plus de risque de blocage).
        self.fetch_descriptions = fetch_descriptions

    def _search_url(self, query: str, location: str, start: int = 0) -> str:
        params = {"q": query, "l": location, "start": start, "sort": "date"}
        return f"{BASE_URL}/jobs?{urlencode(params)}"

    async def search(
        self,
        query: str,
        location: str = "",
        max_results: int = 25,
    ) -> list[JobOffer]:
        offers: list[JobOffer] = []
        seen: set[str] = set()

        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=self.headless,
                user_agent=USER_AGENT,
                locale="fr-FR",
                viewport={"width": 1366, "height": 768},
                args=chromium_args(),
            )
            # Masque le flag navigator.webdriver
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = await ctx.new_page()

            start = 0
            while len(offers) < max_results:
                url = self._search_url(query, location, start)
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await _human_pause()

                # Indeed force parfois une connexion après la 1re page.
                if "secure.indeed.com/auth" in page.url or "/auth?" in page.url:
                    print(
                        "ℹ️  Indeed demande une connexion pour aller plus loin.\n"
                        "    On garde les offres déjà récupérées et on s'arrête.\n"
                        "    (Astuce : connecte-toi une fois manuellement dans la "
                        "fenêtre ; les cookies seront réutilisés au prochain run.)"
                    )
                    break

                if await self._is_blocked(page):
                    print(
                        "⚠️  Indeed affiche un challenge/CAPTCHA.\n"
                        "    Résous-le manuellement dans la fenêtre du navigateur,\n"
                        "    puis reviens — le scraping reprendra."
                    )
                    # Laisse le temps de résoudre à la main (mode non-headless).
                    await self._wait_until_unblocked(page)

                # Les cartes sont rendues en JS : on attend leur apparition.
                try:
                    await page.wait_for_selector(
                        "div.job_seen_beacon", timeout=15_000
                    )
                except Exception:
                    pass

                cards = await page.query_selector_all("div.job_seen_beacon")
                if not cards:
                    # Plus de résultats (ou layout changé) -> on s'arrête.
                    break

                for card in cards:
                    offer = await self._parse_card(card)
                    if offer and offer.external_id not in seen:
                        seen.add(offer.external_id)
                        offers.append(offer)
                        if len(offers) >= max_results:
                            break

                start += 10
                await _human_pause(1.5, 3.5)

            offers = offers[:max_results]

            # Enrichissement : on visite chaque offre pour son texte complet.
            if self.fetch_descriptions and offers:
                print(f"📄 Récupération des descriptions ({len(offers)} offres)…")
                for i, off in enumerate(offers, 1):
                    desc = await self._fetch_description(page, off.external_id)
                    if desc:
                        off.description = desc
                    print(f"   {i}/{len(offers)} — {off.title[:50]}"
                          f" ({len(off.description)} car.)")
                    await _human_pause(1.0, 2.5)

            await ctx.close()

        return offers

    async def _fetch_description(self, page: Page, jk: str) -> str:
        """Ouvre la page détail d'une offre et extrait sa description."""
        try:
            url = f"{BASE_URL}/viewjob?jk={jk}"
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            if "/auth?" in page.url or await self._is_blocked(page):
                return ""
            try:
                await page.wait_for_selector("#jobDescriptionText", timeout=10_000)
            except Exception:
                return ""
            el = await page.query_selector("#jobDescriptionText")
            return (await el.inner_text()).strip() if el else ""
        except Exception as exc:  # noqa: BLE001
            print(f"   (description ignorée pour {jk} : {exc})")
            return ""

    async def _parse_card(self, card) -> JobOffer | None:
        try:
            # L'ancre du titre porte la classe jcs-JobTitle (h2 ou h3 autour).
            link_el = await card.query_selector("a.jcs-JobTitle")
            if not link_el:
                return None

            href = await link_el.get_attribute("href") or ""
            jk = await link_el.get_attribute("data-jk") or ""
            if not jk and href:
                m = re.search(r"jk=([0-9a-f]+)", href)
                jk = m.group(1) if m else ""

            # Titre : le <span> interne, sinon son attribut title.
            title_el = await link_el.query_selector("span")
            title = ""
            if title_el:
                title = (await title_el.inner_text()).strip()
                if not title:
                    title = (await title_el.get_attribute("title") or "").strip()

            company_el = await card.query_selector('[data-testid="company-name"]')
            company = (await company_el.inner_text()).strip() if company_el else ""

            loc_el = await card.query_selector('[data-testid="text-location"]')
            location = (await loc_el.inner_text()).strip() if loc_el else ""

            salary_el = await card.query_selector(
                '[data-testid="attribute_snippet_testid"], .salary-snippet-container'
            )
            salary = (await salary_el.inner_text()).strip() if salary_el else ""

            full_url = ""
            if href:
                full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

            if not title or not jk:
                return None

            return JobOffer(
                source=self.name,
                external_id=jk,
                title=title,
                company=company,
                location=location,
                url=full_url,
                salary=salary,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"   (carte ignorée : {exc})")
            return None

    async def _is_blocked(self, page: Page) -> bool:
        content = (await page.content()).lower()
        markers = ["just a moment", "cf-challenge", "verify you are human",
                   "vérifiez que vous êtes humain"]
        return any(m in content for m in markers)

    async def _wait_until_unblocked(self, page: Page, timeout: int = 180) -> None:
        for _ in range(timeout):
            if not await self._is_blocked(page):
                return
            await asyncio.sleep(1)
