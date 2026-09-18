# JobApply

Application locale de collecte, classement et suivi d'offres d'emploi depuis
Indeed et Glassdoor. Le projet associe une API FastAPI, une interface React,
une base SQLite et des scrapers Playwright.

> Les plateformes peuvent interdire le scraping dans leurs conditions
> d'utilisation. Utilisez des volumes faibles, respectez leurs règles et ne
> contournez pas leurs mécanismes de protection.

## Prérequis

- Python 3.11 ou plus récent
- Node.js 20 ou plus récent

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m playwright install chromium
npm --prefix frontend ci
```

Créez ensuite les fichiers locaux de configuration :

```powershell
Copy-Item data\profil.example.json data\profil.json
Copy-Item data\recherches.example.json data\recherches.json
Copy-Item data\candidat.example.json data\candidat.json
```

Adaptez ces trois fichiers à votre profil. Ils contiennent des données
personnelles et sont volontairement ignorés par Git.

## Lancement local

Dans un premier terminal :

```powershell
Set-Location backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Dans un second terminal :

```powershell
npm --prefix frontend run dev
```

Le dashboard est disponible sur <http://127.0.0.1:5173> et la documentation
de l'API sur <http://127.0.0.1:8000/docs>.

Pour autoriser un frontend distant, ajoutez son origine HTTPS à la variable
`CORS_ORIGINS` du backend (plusieurs valeurs séparées par des virgules).

## Commandes utiles

```powershell
python backend\collect.py "développeur python" "Paris" 15 indeed
python backend\rank.py 20
python backend\daily_collect.py
python backend\apply.py
python -m unittest discover -s backend\tests
```

## Déploiement

Le dossier `frontend` est un projet Vercel autonome. Configurez
`VITE_API_URL` dans Vercel avec l'URL HTTPS d'un backend hébergé séparément.

Le backend ne doit pas être hébergé tel quel sur Vercel : Playwright avec un
profil navigateur persistant, les fenêtres interactives et SQLite nécessitent
une machine ou un conteneur persistant. Pour une mise en production complète,
utilisez par exemple un VPS/conteneur pour l'API et PostgreSQL pour les données.

### Backend avec Docker

Le dépôt fournit une image Playwright/FastAPI et un volume persistant :

```powershell
docker compose up --build -d
```

Le dashboard écoute alors sur `http://localhost:5173` et l'API sur
`http://localhost:8000`. Les fichiers de configuration d'exemple sont copiés
automatiquement dans le volume `jobapply_data` lors du premier démarrage.

Pour personnaliser les ports ou l'URL compilée dans le frontend, créez un
fichier `.env` à partir de `.env.example` avant la construction des images.

En production, déployez l'image racine sur un hôte acceptant les conteneurs et
les volumes persistants, exposez l'API derrière HTTPS, puis configurez :

- `CORS_ORIGINS=https://scrapping-version1.vercel.app` côté backend ;
- `VITE_API_URL=https://votre-api.example.com` dans Vercel.

Le mode conteneur utilise Chromium headless. Les challenges nécessitant une
intervention humaine ne peuvent pas être résolus sur un serveur sans interface.

## Données sensibles

Ne versionnez jamais `data/candidat.json`, `data/profil.json`, `data/jobs.db`,
les profils `data/browser_*` ou les fichiers `.env`. Si ces fichiers ont déjà
été poussés, révoquez les sessions concernées et nettoyez aussi l'historique
Git ; un simple nouveau commit ne les retire pas des anciens commits.
