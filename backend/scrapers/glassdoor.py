"""Scraper Glassdoor basé sur Playwright.

Glassdoor protège ses pages (Cloudflare + mur de connexion fréquent).
On s'appuie sur les attributs `data-test` (plus stables que les classes
à hash) et un contexte persistant pour limiter les blocages.

⚠️ Contraire aux CGU de Glassdoor. Usage personnel/éducatif, rythme lent.

Note : Glassdoor ramène souvent les résultats au niveau « France » même
avec une ville en paramètre (le filtrage fin nécessite un identifiant de
localisation interne). On récupère donc large, et le scoring/localisation
côté matching fait le tri par ville ensuite.
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin

from playwright.async_api import async_playwright, Page

from .base import BaseScraper, JobOffer, chromium_args

BASE_URL = "https://www.glassdoor.fr"
DATA_DIR = Path(os.getenv(
    "JOBAPPLY_DATA_DIR",
    Path(__file__).resolve().parents[2] / "data",
)).resolve()
USER_DATA_DIR = DATA_DIR / "browser_glassdoor"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def _human_pause(a: float = 0.6, b: float = 1.8) -> None:
    await asyncio.sleep(random.uniform(a, b))


class GlassdoorScraper(BaseScraper):
    name = "glassdoor"

    def __init__(
        self, headless: bool = False, fetch_descriptions: bool = False
    ) -> None:
        # Par défaut on se contente de l'extrait présent sur chaque carte
        # (la description complète est floutée sans connexion Glassdoor).
        # Passe fetch_descriptions=True si tu es connecté pour le texte entier.
        self.headless = headless
        self.fetch_descriptions = fetch_descriptions

    def _search_url(self, query: str, location: str) -> str:
        params = {"sc.keyword": query}
        if location:
            params["locKeyword"] = location
        return f"{BASE_URL}/Job/jobs.htm?{urlencode(params)}"

    async def search(
        self, query: str, location: str = "", max_results: int = 25,
    ) -> list[JobOffer]:
        offers: list[JobOffer] = []
        seen: set[str] = set()
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR), headless=self.headless,
                user_agent=USER_AGENT, locale="fr-FR",
                viewport={"width": 1366, "height": 768},
                args=chromium_args(),
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = await ctx.new_page()

            await page.goto(self._search_url(query, location),
                            wait_until="domcontentloaded", timeout=60_000)
            await _human_pause(2, 4)
            await self._dismiss_modal(page)

            try:
                await page.wait_for_selector(
                    'li[data-test="jobListing"]', timeout=15_000)
            except Exception:
                print("⚠️ Glassdoor : aucune offre visible (blocage/login ?).")
                await ctx.close()
                return []

            # Charge plus d'offres via le bouton « Voir plus d'emplois ».
            while True:
                cards = await page.query_selector_all('li[data-test="jobListing"]')
                if len(cards) >= max_results:
                    break
                more = await page.query_selector(
                    'button[data-test="load-more"]')
                if not more or not await more.is_visible():
                    break
                await self._dismiss_modal(page)
                try:
                    await more.click()
                except Exception:
                    break
                await _human_pause(1.5, 3.0)

            cards = await page.query_selector_all('li[data-test="jobListing"]')
            for card in cards:
                offer = await self._parse_card(card)
                if offer and offer.external_id not in seen:
                    seen.add(offer.external_id)
                    offers.append(offer)
                    if len(offers) >= max_results:
                        break

            offers = offers[:max_results]

            if self.fetch_descriptions and offers:
                print(f"📄 Descriptions Glassdoor ({len(offers)} offres)…")
                for i, off in enumerate(offers, 1):
                    desc = await self._fetch_description(page, off)
                    if desc:
                        off.description = desc
                    print(f"   {i}/{len(offers)} — {off.title[:45]}"
                          f" ({len(off.description)} car.)")
                    await _human_pause(1.0, 2.0)

            await ctx.close()

        return offers

    async def _dismiss_modal(self, page: Page) -> None:
        """Ferme la modale de connexion/inscription si elle apparaît."""
        for sel in ['button[data-test="job-alert-modal-close"]',
                    '.CloseButton', 'button[aria-label="Fermer"]',
                    'button[alt="Close"]', '[data-test="modal-close"]']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                continue

    async def _parse_card(self, card) -> JobOffer | None:
        try:
            jobid = await card.get_attribute("data-jobid") or ""
            link = await card.query_selector('a[data-test="job-title"]')
            if not link:
                return None
            title = (await link.inner_text()).strip()
            href = await link.get_attribute("href") or ""
            if not jobid and href:
                m = re.search(r"jl=(\d+)", href)
                jobid = m.group(1) if m else href

            comp_el = await card.query_selector('[class*="EmployerName"]')
            company = (await comp_el.inner_text()).strip() if comp_el else ""

            loc_el = await card.query_selector('[data-test="emp-location"]')
            location = (await loc_el.inner_text()).strip() if loc_el else ""

            sal_el = await card.query_selector('[data-test="detailSalary"]')
            salary = (await sal_el.inner_text()).strip() if sal_el else ""

            # Extrait de description dispo sans connexion (la version complète
            # est floutée par Glassdoor tant qu'on n'est pas connecté).
            snip_el = await card.query_selector(
                '[class*="jobDescriptionSnippet"]')
            snippet = (await snip_el.inner_text()).strip() if snip_el else ""

            if not title or not jobid:
                return None

            return JobOffer(
                source=self.name, external_id=jobid, title=title,
                company=company, location=location,
                url=urljoin(BASE_URL, href), salary=salary,
                description=snippet,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"   (carte ignorée : {exc})")
            return None

    async def _fetch_description(self, page: Page, off: JobOffer) -> str:
        """Ouvre l'offre dans le volet de droite et lit la description."""
        try:
            link = await page.query_selector(
                f'a[data-test="job-title"][href*="{off.external_id}"]')
            if not link:
                return ""
            await link.click()
            await asyncio.sleep(1.5)
            await self._dismiss_modal(page)
            el = await page.query_selector('[class*="JobDetails_jobDescription"]')
            if not el:
                return ""
            cls = await el.get_attribute("class") or ""
            if "blur" in cls.lower():
                return ""  # floutée (non connecté) -> on garde l'extrait
            text = (await el.inner_text()).strip()
            return text if len(text) > 80 else ""
        except Exception:
            return ""
