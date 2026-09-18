"""Interface commune à tous les scrapers de jobboards."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from abc import ABC, abstractmethod


@dataclass
class JobOffer:
    """Une offre normalisée, commune à toutes les sources."""
    source: str                 # "indeed", "wttj", ...
    external_id: str            # id de l'offre côté site (pour dédupliquer)
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    salary: str = ""
    contract_type: str = ""
    posted_at: str = ""
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


class BaseScraper(ABC):
    """Chaque scraper concret implémente search()."""

    name: str = "base"

    @abstractmethod
    async def search(
        self,
        query: str,
        location: str = "",
        max_results: int = 25,
    ) -> list[JobOffer]:
        """Retourne une liste d'offres normalisées."""
        raise NotImplementedError
