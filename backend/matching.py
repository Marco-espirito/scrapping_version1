"""Moteur de scoring : note chaque offre (0-100) selon le profil utilisateur.

Le score combine plusieurs critères pondérés (voir profil.json) :
  - compétences trouvées dans le titre/description
  - correspondance de l'intitulé recherché
  - mots-clés bonus (télétravail, CDI...)
  - localisation préférée
  - salaire au-dessus du minimum

Une offre contenant un terme d'EXCLUSION est fortement pénalisée.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(os.getenv(
    "JOBAPPLY_DATA_DIR",
    Path(__file__).resolve().parents[1] / "data",
)).resolve()
PROFIL_PATH = DATA_DIR / "profil.json"


def _normalize(text: str) -> str:
    """Minuscule + sans accents -> comparaison robuste."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def load_profil(path: Path = PROFIL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_hits(terms: list[str], haystack: str) -> tuple[int, list[str]]:
    found = []
    for term in terms:
        normalized = _normalize(term).strip()
        if not normalized:
            continue
        pattern = rf"(?<!\w){re.escape(normalized)}(?!\w)"
        if re.search(pattern, haystack):
            found.append(term)
    return len(found), found


def _extract_salary(text: str) -> int | None:
    """Tente d'extraire un salaire annuel en euros depuis un texte libre."""
    normalized = _normalize(text).replace("\u202f", " ")
    values = []
    pattern = r"(\d+(?:[\s.,]\d+)?)\s*(k|€|eur)(?:\s*/?\s*(an|mois|heure|h))?"
    for number, unit, period in re.findall(pattern, normalized):
        value = float(number.replace(" ", "").replace(",", "."))
        if unit == "k":
            value *= 1000
        if period == "mois":
            value *= 12
        elif period in {"heure", "h"}:
            value *= 35 * 52
        if value >= 1000:
            values.append(int(value))
    return max(values) if values else None


def score_offer(offer: dict, profil: dict) -> tuple[float, dict]:
    """Retourne (score 0-100, détail des contributions)."""
    text = _normalize(
        " ".join([
            offer.get("title", ""),
            offer.get("company", ""),
            offer.get("location", ""),
            offer.get("description", ""),
            offer.get("salary", ""),
        ])
    )
    w = profil.get("ponderation", {})
    detail: dict = {}
    raw = 0.0
    max_raw = 0.0

    # --- Exclusions : pénalité immédiate ---
    n_excl, excl_found = _count_hits(profil.get("exclusions", []), text)
    if n_excl:
        detail["exclusions"] = excl_found
        # On renvoie un score très bas mais on garde le détail.
        return 0.0, detail

    # --- Compétences ---
    skills = profil.get("competences", [])
    if skills:
        n, found = _count_hits(skills, text)
        contrib = (n / len(skills)) * w.get("competences", 5)
        raw += contrib
        max_raw += w.get("competences", 5)
        detail["competences"] = found

    # --- Intitulé recherché ---
    titles = profil.get("intitule_recherche", [])
    if titles:
        n, found = _count_hits(titles, text)
        contrib = min(n, 1) * w.get("intitule", 4)  # présence suffit
        raw += contrib
        max_raw += w.get("intitule", 4)
        detail["intitule"] = found

    # --- Mots-clés bonus ---
    bonus = profil.get("mots_cles_bonus", [])
    if bonus:
        n, found = _count_hits(bonus, text)
        contrib = min(n / len(bonus), 1) * w.get("mots_cles_bonus", 2)
        raw += contrib
        max_raw += w.get("mots_cles_bonus", 2)
        detail["mots_cles_bonus"] = found

    # --- Localisation ---
    locs = profil.get("localisations_preferees", [])
    if locs:
        n, found = _count_hits(locs, text)
        contrib = min(n, 1) * w.get("localisation", 3)
        raw += contrib
        max_raw += w.get("localisation", 3)
        detail["localisation"] = found

    # --- Salaire ---
    sal_min = profil.get("salaire_min_annuel")
    if sal_min:
        max_raw += w.get("salaire", 2)
        sal = _extract_salary(offer.get("salary", "") or offer.get("description", ""))
        if sal is not None:
            detail["salaire_detecte"] = sal
            if sal >= sal_min:
                raw += w.get("salaire", 2)

    score = round((raw / max_raw) * 100, 1) if max_raw else 0.0
    return score, detail
