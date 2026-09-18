"""Auto-apply ASSISTÉ pour les offres marquées « à postuler ».

Principe (semi-automatique, jamais d'envoi sans toi) :
  1. lit les offres au statut « a_postuler » en base
  2. pour chacune : ouvre la page Indeed, lance la candidature
  3. choisit le bon CV selon le titre/description de l'offre
  4. pré-remplit les champs détectés (nom, email, téléphone, ville)
  5. te laisse VÉRIFIER et CLIQUER « Envoyer » toi-même
  6. tu confirmes dans la console -> l'offre passe « postulée »

Usage :
    python apply.py            # traite toutes les offres « à postuler »
    python apply.py 22         # traite uniquement l'offre d'id 22

⚠️ Connecte-toi à ton compte Indeed une fois dans la fenêtre : les cookies
   sont réutilisés (contexte persistant partagé avec le scraper).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Page
from sqlalchemy import select

from db import init_db, get_session
from models import Job, JobStatus
from scrapers.indeed import USER_DATA_DIR, USER_AGENT, BASE_URL

DATA_DIR = Path(os.getenv(
    "JOBAPPLY_DATA_DIR",
    Path(__file__).resolve().parents[1] / "data",
)).resolve()
CANDIDAT_PATH = DATA_DIR / "candidat.json"


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def load_candidat() -> dict:
    return json.loads(CANDIDAT_PATH.read_text(encoding="utf-8"))


def choose_cv(job: Job, cand: dict) -> Path:
    """Sélectionne le CV le plus pertinent selon le titre + description."""
    text = _norm(f"{job.title} {job.description}")
    best, best_hits = cand["cv_par_defaut"], 0
    for cv, keywords in cand["cv_disponibles"].items():
        hits = sum(1 for k in keywords if _norm(k) in text)
        if hits > best_hits:
            best, best_hits = cv, hits
    return Path(cand["dossier_cv"]) / best


async def smart_fill(page: Page, cand: dict) -> int:
    """Remplit au mieux les champs visibles (page + iframes) selon l'intitulé.

    On associe chaque champ à une donnée candidat via son type / name /
    placeholder / label. Best-effort : ne casse jamais si un champ manque.
    """
    mapping = [
        (["email", "e-mail", "courriel"], cand["email"]),
        (["tel", "phone", "téléphone", "telephone", "portable"], cand["telephone"]),
        (["prenom", "prénom", "first", "firstname", "first-name"], cand["prenom"]),
        (["nom", "last", "lastname", "last-name", "surname"], cand["nom"]),
        (["full name", "full_name", "fullname", "nom complet", "nom_complet"],
         cand["nom_complet"]),
        (["ville", "city", "localit"], cand["ville"]),
        (["linkedin"], cand.get("linkedin", "")),
    ]
    filled = 0
    frames = [page] + page.frames  # formulaire parfois dans une iframe

    for frame in frames:
        try:
            inputs = await frame.query_selector_all(
                "input[type=text], input[type=email], input[type=tel], "
                "input:not([type]), textarea"
            )
        except Exception:
            continue
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                if (await inp.input_value()):
                    continue  # déjà rempli
                attrs = " ".join([
                    (await inp.get_attribute("name") or ""),
                    (await inp.get_attribute("id") or ""),
                    (await inp.get_attribute("placeholder") or ""),
                    (await inp.get_attribute("aria-label") or ""),
                    (await inp.get_attribute("autocomplete") or ""),
                ]).lower()
                for keys, value in mapping:
                    if value and any(k in attrs for k in keys):
                        await inp.fill(value)
                        filled += 1
                        break
            except Exception:
                continue
    return filled


async def apply_one(page: Page, job: Job, cand: dict) -> bool:
    """Ouvre la candidature d'une offre et pré-remplit. Retourne True si envoyée."""
    print("\n" + "=" * 64)
    print(f"📌 [{job.id}] {job.title} — {job.company} ({job.location})")
    cv = choose_cv(job, cand)
    print(f"   CV choisi : {cv.name}  {'✅' if cv.exists() else '❌ INTROUVABLE'}")

    url = job.url or f"{BASE_URL}/viewjob?jk={job.external_id}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(2)

    # Bouton de candidature (Indeed Apply). Sélecteurs courants.
    btn = None
    for sel in [
        "#indeedApplyButton", "button:has-text('Candidature simplifiée')",
        "button:has-text('Postuler')", "a:has-text('Postuler')",
        ".ia-IndeedApplyButton",
    ]:
        btn = await page.query_selector(sel)
        if btn and await btn.is_visible():
            break
        btn = None

    if btn:
        await btn.click()
        await asyncio.sleep(3)
    else:
        print("   ⚠️ Pas de bouton « Candidature simplifiée » : l'offre redirige")
        print("      sans doute vers le site de l'entreprise. À faire à la main.")

    # Pré-remplissage best-effort.
    n = await smart_fill(page, cand)
    print(f"   ✍️  {n} champ(s) pré-rempli(s).")

    # Upload CV si un champ fichier est présent.
    if cv.exists():
        for frame in [page] + page.frames:
            try:
                file_inp = await frame.query_selector("input[type=file]")
                if file_inp:
                    await file_inp.set_input_files(str(cv))
                    print("   📎 CV téléversé.")
                    break
            except Exception:
                continue

    print("\n   👉 VÉRIFIE la candidature dans le navigateur, complète ce qui")
    print("      manque, puis ENVOIE-la toi-même.")
    ans = input("   L'as-tu envoyée ? [o/n/q pour quitter] ").strip().lower()
    if ans == "q":
        raise KeyboardInterrupt
    return ans == "o"


async def main() -> None:
    init_db()
    cand = load_candidat()
    only_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    with get_session() as s:
        stmt = select(Job)
        if only_id:
            stmt = stmt.where(Job.id == only_id)
        else:
            stmt = stmt.where(Job.status == JobStatus.TO_APPLY)
        jobs = list(s.scalars(stmt.order_by(Job.match_score.desc())).all())

        if not jobs:
            print("Aucune offre à traiter. Marque des offres « ⭐ À postuler » "
                  "dans le dashboard d'abord.")
            return

        print(f"🚀 {len(jobs)} candidature(s) à traiter.")
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR), headless=False,
                user_agent=USER_AGENT, locale="fr-FR",
                viewport={"width": 1366, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = await ctx.new_page()
            try:
                for job in jobs:
                    sent = await apply_one(page, job, cand)
                    if sent:
                        job.status = JobStatus.APPLIED
                        job.applied_at = datetime.now(timezone.utc)
                        s.commit()
                        print("   ✅ Marquée « postulée ».")
                    else:
                        print("   ⏭️  Laissée en l'état.")
            except KeyboardInterrupt:
                print("\n⏹️  Arrêt demandé.")
            finally:
                await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
