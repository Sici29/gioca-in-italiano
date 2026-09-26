"""Genera hub/web/_preview.html: l'interfaccia con dati veri, aperta nel browser.

Serve a guardare la UI senza compilare ne' aprire la finestra nativa. Il file
e' escluso dalla compilazione e dal repository.

    python tools/preview.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import __version__, catalog, config, links  # noqa: E402
from hub.ghclient import GitHubClient  # noqa: E402

PROPOSTE = [
    {"number": 12, "title": "[Proposta] Kingdom Come: Deliverance II", "url": "#",
     "votes": 1284, "up": 1284, "comments": 37, "created": "2026-08-02T10:00:00Z",
     "labels": ["proposta"], "in_lavorazione": False},
    {"number": 9, "title": "[Proposta] Dune: Awakening", "url": "#",
     "votes": 417, "up": 417, "comments": 12, "created": "2026-08-20T10:00:00Z",
     "labels": ["proposta", "in lavorazione"], "in_lavorazione": True},
    {"number": 21, "title": "[Proposta] The Alters", "url": "#",
     "votes": 63, "up": 63, "comments": 4, "created": "2026-09-14T10:00:00Z",
     "labels": ["proposta"], "in_lavorazione": False},
]


# Volutamente lo stato di un UTENTE qualunque: accesso non attivo e, appunto,
# nessuna traccia della procedura di attivazione (`autore` falso). Per vedere
# quella che vede l'autore, dalla console del browser:
#   S.setupSbloccato = true; renderOauth()
# oppure cinque clic sul numero di versione, come nell'hub vero.
AUTH = {
    "configured": False,
    "one_click": False,
    "source": "",
    "client_id": "",
    "autore": False,
    "logged_in": False,
    "login": "",
    "starred": ["Aniimo-Italian-Translation"],
    "following": False,
}


def main() -> int:
    res = catalog.build(GitHubClient())
    progetti = res["projects"]

    # Si finge una traduzione installata a una versione indietro, altrimenti
    # non si vedrebbero gli stati "da aggiornare" e "non ancora installata".
    for p in progetti:
        if len(p.get("releases") or []) > 2:
            p["installed_tag"] = p["releases"][2]["tag"]
            p["installed_at"] = "2026-09-01T10:00:00Z"
            p["status"] = "aggiornamento"
            p["novita"] = "aggiornamento"
            if not (p.get("latest") or {}).get("body"):
                p["latest"]["body"] = "\n".join(
                    (
                        "## Novita'",
                        "- Ritradotti i dialoghi del capitolo 3 e i nomi degli oggetti",
                        "- Corretti 120 errori di battitura segnalati dalla comunita'",
                    )
                )
            break

    # E una installata e in pari, per vedere il pulsante "Gioca".
    for p in progetti:
        if p.get("avvio") and p.get("status") != "aggiornamento" and p.get("latest"):
            p["installed_tag"] = p["latest"]["tag"]
            p["status"] = "aggiornato"
            break

    payload = {
        "projects": progetti,
        "summary": catalog.summary(progetti),
        "library": res.get("library", {}),
        "error": "",
        "rate_remaining": res.get("rate_remaining"),
        "checked_at": "2026-09-24T20:40:00Z",
        "proposals": PROPOSTE,
        "source": "feed",
        "auth": dict(AUTH),
        "hub_update": {
            "available": True, "current": __version__, "version": "v1.1.0", "url": "#",
            "asset": {"name": "GiocaInItaliano.exe", "url": "#", "size": 25_900_000},
        },
    }
    boot = {
        "version": __version__, "user": config.GITHUB_USER, "bmc_url": config.BMC_URL,
        "profile_url": config.PROFILE_URL, "suggest_url": links.suggest_translation(),
        "settings": {"auto_refresh": True, "notify": True},
        "auth": dict(AUTH),
        "voted": [9],
    }

    SETUP = {
        "register_url": config.oauth_register_url(),
        "app_name": config.OAUTH_APP_NAME,
        "homepage": config.PROFILE_URL,
        "callback": config.OAUTH_CALLBACK_URL,
        "source": "",
        "one_click": False,
        "client_id": "",
    }

    web = Path(__file__).resolve().parents[1] / "hub" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")

    finto = f"""
<script>
window.pywebview = {{ api: {{
  bootstrap: async () => ({json.dumps(boot, ensure_ascii=False)}),
  refresh: async () => true, install: async () => true, cancel_install: async () => true,
  mark_seen: async () => true, set_setting: async () => true, open_external: async () => true,
  pick_cover: async () => true, open_game_folder: async () => true, open_data_folder: async () => true,
  clear_cover_cache: async () => true, hidden_repos: async () => ["Vecchia-Italian-Translation"],
  toggle_star: async () => ({{ok: true, starred: true}}), toggle_follow: async () => ({{ok: true, following: true}}),
  unhide_repo: async () => true, download_hub_update: async () => true,
  login_start: async () => ({{ok: true, user_code: "WDJB-MJHT", url: "https://github.com/login/device"}}),
  login_cancel: async () => true, logout: async () => true,
  create_proposal: async () => ({{ok: true}}), toggle_vote: async () => ({{ok: true, voted: true}}),
  oauth_setup: async () => ({json.dumps(SETUP, ensure_ascii=False)}),
  oauth_register: async () => true,
  oauth_save: async () => ({{ok: true, one_click: true}}),
  oauth_forget: async () => ({{ok: true, source: ""}}),
  oauth_config_snippet: async () => ({{ok: false}}),
  avvia_gioco: async () => ({{ok: true}}),
  scegli_cartella_gioco: async () => ({{ok: false}}),
  dimentica_cartella_gioco: async () => true,
  // Un installer finto che scrive le sue righe una alla volta, come fara'
  // quello vero quando avra' line_buffering.
  azione_installer: async (repo, azione) => {{
    const e = (p) => window.hubEvent({{event: 'installer', payload: Object.assign({{repo, azione}}, p)}});
    const righe = azione === 'restore'
      ? ['Cartella gioco: D:/SteamLibrary/steamapps/common/Aniimo', 'Backup ripristinato: 20260926-102856']
      : ['Cartella gioco: D:/SteamLibrary/steamapps/common/Aniimo', 'Versione gioco rilevata: 3603741',
         'Controllo contenuti: Traduzione 100% compatibile (testi italiani correnti)',
         'Testi nuovi o modificati: 0 (100% compatibile)', 'Strutture tecniche: compatibili',
         'Versione supportata: sì'];
    e({{fase: 'inizio'}});
    righe.forEach((r, i) => setTimeout(() => e({{riga: r}}), 350 * (i + 1)));
    setTimeout(() => e({{fase: 'fine', esito: {{ok: true, parziale: false,
      messaggio: righe[righe.length - 1], consiglio: '', righe}}}}), 350 * (righe.length + 1));
    return true;
  }}
}}}};
window.__preview = ({json.dumps(payload, ensure_ascii=False)});
</script>
"""
    avvio = """
<script>
window.dispatchEvent(new Event('pywebviewready'));
setTimeout(() => window.hubEvent({event: 'catalog', payload: window.__preview}), 60);
</script>
"""
    # Il browser tiene in cache app.js e app.css fra un giro e l'altro, e si
    # finisce per guardare la versione di prima credendo che una modifica non
    # abbia funzionato. La marca temporale glielo impedisce.
    marca = int(time.time())
    html = html.replace('href="app.css"', f'href="app.css?v={marca}"')
    html = html.replace(
        '<script src="app.js"></script>',
        finto + f'<script src="app.js?v={marca}"></script>' + avvio,
    )
    (web / "_preview.html").write_text(html, encoding="utf-8")
    print(f"anteprima pronta: {len(progetti)} traduzioni, {len(PROPOSTE)} proposte")
    print("apri http://127.0.0.1:8731/_preview.html dopo aver avviato:")
    print("  python -m http.server 8731 --directory hub/web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
