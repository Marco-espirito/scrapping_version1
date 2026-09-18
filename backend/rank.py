"""Calcule le match_score de toutes les offres en base et affiche le top.

Usage :
    python rank.py          # score tout + affiche le top 15
    python rank.py 30       # affiche le top 30
"""
import sys

from sqlalchemy import select

from db import init_db, get_session
from models import Job, JobStatus
from matching import load_profil, score_offer


def main() -> None:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    init_db()
    profil = load_profil()

    with get_session() as s:
        jobs = s.scalars(select(Job)).all()
        for j in jobs:
            score, detail = score_offer({
                "title": j.title, "company": j.company,
                "location": j.location, "description": j.description,
                "salary": j.salary,
            }, profil)
            j.match_score = score
        s.commit()

        ranked = s.scalars(
            select(Job)
            .where(Job.status != JobStatus.IGNORED)
            .order_by(Job.match_score.desc())
            .limit(top_n)
        ).all()

        print(f"🏆 Top {len(ranked)} offres par score :\n")
        for j in ranked:
            bar = "█" * int(j.match_score / 10)
            print(f"  {j.match_score:5.1f}  {bar:<10} [{j.id}] {j.title}")
            print(f"          {j.company} — {j.location}  {j.salary}")

        # Petit récap des offres écartées par exclusion (score 0).
        zeros = s.scalars(
            select(Job).where(Job.match_score == 0.0)
        ).all()
        if zeros:
            print(f"\n⚠️  {len(zeros)} offre(s) à score 0 "
                  f"(souvent un mot d'exclusion). À vérifier dans le profil.")


if __name__ == "__main__":
    main()
