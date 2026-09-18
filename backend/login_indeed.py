"""Connexion manuelle à Indeed (session mémorisée pour les scrapes).

Ouvre une fenêtre Chromium sur la page de connexion Indeed. TU saisis
tes identifiants toi-même, directement sur le vrai site (rien n'est
stocké côté projet — seuls les cookies de session sont gardés dans le
profil navigateur persistant `data/browser_indeed`, comme un vrai Chrome).

Usage :
    python login_indeed.py
"""
import asyncio

from playwright.async_api import async_playwright

from scrapers.indeed import USER_DATA_DIR, USER_AGENT, BASE_URL


async def main() -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("🔐 Ouverture d'Indeed pour connexion…")
    print("   Connecte-toi dans la fenêtre, puis reviens ici.")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR), headless=False,
            user_agent=USER_AGENT, locale="fr-FR",
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(f"{BASE_URL}/account/login",
                        wait_until="domcontentloaded", timeout=60_000)

        # Attend que tu confirmes la connexion dans la console.
        await asyncio.get_event_loop().run_in_executor(
            None, input,
            "\n👉 Une fois CONNECTÉ dans la fenêtre, appuie sur Entrée ici… ")

        # Vérifie l'état de connexion (best-effort).
        try:
            await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded",
                            timeout=30_000)
            await asyncio.sleep(2)
            content = (await page.content()).lower()
            connected = any(k in content for k in
                            ["mon compte", "déconnexion", "se déconnecter",
                             "my account", "sign out"])
            print("✅ Session enregistrée — tu sembles connecté."
                  if connected else
                  "⚠️ Session enregistrée, mais connexion non confirmée. "
                  "Relance si besoin.")
        except Exception:
            print("✅ Session enregistrée (vérification ignorée).")

        await ctx.close()
        print("   Les prochains scrapes réutiliseront cette session.")


if __name__ == "__main__":
    asyncio.run(main())
