"""Genera catalog.json, il catalogo pre-generato che l'hub scarica.

Gira dentro GitHub Actions, dove il GITHUB_TOKEN alza il limite a 5.000
richieste all'ora: qui le richieste si possono spendere senza problemi, e
l'hub degli utenti finisce per non farne nessuna.

Riusa gli stessi moduli dell'hub, quindi le regole di riconoscimento dei repo
restano scritte in un posto solo (hub/config.py).

    python tools/build_catalog.py [percorso/catalog.json] [--fresco dati-per-il-sito.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import catalog, config, feed, steam  # noqa: E402
from hub.ghclient import GitHubClient  # noqa: E402

# Quante release tenere per traduzione: le note di rilascio sono testo lungo e
# il file lo scaricano tutti gli utenti, quindi non serve la storia completa.
MAX_RELEASES = 12

# Campi del repo che servono davvero al client.
REPO_FIELDS = (
    "name",
    "description",
    "html_url",
    "stargazers_count",
    "topics",
    "pushed_at",
)


def build() -> dict:
    client = GitHubClient()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        client.session.headers["Authorization"] = f"Bearer {token}"
        print("autenticato: limite 5.000 richieste/ora")
    else:
        print("ATTENZIONE: nessun token, limite 60 richieste/ora")

    # Nessuna preferenza locale qui: il catalogo e' uguale per tutti.
    neutral = {"settings": {"hidden_repos": []}}
    entries = catalog.discover(client, neutral)
    print(f"traduzioni trovate: {len(entries)}")

    out = []
    for entry in entries:
        repo = entry["repo"]
        name = repo["name"]
        marker = dict(entry["marker"])

        releases = [catalog._clean_release(r) for r in client.list_releases(name)]
        releases = releases[:MAX_RELEASES]

        # L'AppID si risolve qui una volta per tutte: cosi' nessun utente deve
        # interrogare la ricerca di Steam, e tutti vedono lo stesso
        # abbinamento (niente sorprese se l'indice di Steam risponde male).
        title = marker.get("nome_gioco") or config.pretty_game_name(name)

        declared = marker.get("steam_appid")
        if declared and not marker.get("non_su_steam"):
            # Un AppID scritto a mano puo' essere sbagliato: se sullo store ha
            # un altro nome, meglio scartarlo che pubblicare in catalogo la
            # copertina di un gioco diverso per tutti gli utenti.
            try:
                declared = int(declared)
            except (TypeError, ValueError):
                declared = None
            if declared and steam.verify_appid(declared, title) is False:
                print(f"  {name}: AppID {declared} non corrisponde a {title}, scartato")
                marker.pop("steam_appid", None)
                declared = None
            elif declared:
                marker["steam_appid"] = declared

        if not marker.get("steam_appid") and not marker.get("non_su_steam"):
            appid = steam.search_appid(title)
            if appid:
                marker["steam_appid"] = appid
                print(f"  {name}: AppID risolto -> {appid}")

        out.append(
            {
                "repo": {k: repo.get(k) for k in REPO_FIELDS},
                "marker": marker,
                "releases": releases,
            }
        )
        print(f"  {name}: {len(releases)} release")

    proposals = catalog.fetch_proposals(client)
    print(f"proposte della comunita': {len(proposals)}")

    # L'ultima release dell'hub stesso: cosi' il controllo aggiornamenti lato
    # client non costa nemmeno una richiesta.
    hub_release = {}
    try:
        data = client.get_json(
            f"https://api.github.com/repos/{config.GITHUB_USER}/{config.FEED_REPO}/releases/latest"
        )
        if isinstance(data, dict) and data.get("tag_name"):
            hub_release = {
                "tag_name": data.get("tag_name"),
                "name": data.get("name"),
                "body": data.get("body"),
                "html_url": data.get("html_url"),
                "published_at": data.get("published_at"),
                "assets": [
                    {
                        "name": a.get("name"),
                        "browser_download_url": a.get("browser_download_url"),
                        "size": a.get("size"),
                    }
                    for a in (data.get("assets") or [])
                ],
            }
            print(f"ultima release dell'hub: {hub_release['tag_name']}")
    except Exception as exc:
        print(f"release dell'hub non leggibile ({exc}): il client ripieghera' sull'API")

    return {
        "version": feed.FORMAT_VERSION,
        "generated_at": feed.stamp(),
        "user": config.GITHUB_USER,
        "entries": out,
        "proposals": proposals,
        "hub_release": hub_release,
    }


def _significativo(data: dict) -> dict:
    """Il catalogo senza la data e senza i contatori di download.

    Sono le due cose che cambiano a ogni giro anche quando non e' successo
    niente: la data per definizione, i download perche' qualcuno scarica
    sempre qualcosa.
    """
    copia = json.loads(json.dumps(data))
    copia.pop("generated_at", None)
    for voce in copia.get("entries") or []:
        for rel in voce.get("releases") or []:
            rel.pop("downloads", None)
            if isinstance(rel.get("download"), dict):
                rel["download"].pop("downloads", None)
            for asset in rel.get("assets") or []:
                asset.pop("downloads", None)
    return copia


# L'hub scarta i cataloghi piu' vecchi di 36 ore, quindi anche senza novita'
# il file va rinfrescato: una volta al giorno lascia un buon margine.
RINFRESCO_ORE = 24


def da_riscrivere(vecchio: dict | None, nuovo: dict) -> bool:
    """Se il catalogo nel repo va sostituito.

    Riscriverlo a ogni giro vorrebbe dire un commit ogni tre ore anche senza
    novita'. Cosi' si riscrive quando cambia qualcosa che conta (una release,
    un hub.json, una proposta) e comunque una volta al giorno, che tiene
    fresca la data e aggiorna i download.
    """
    if not isinstance(vecchio, dict):
        return True
    if _significativo(vecchio) != _significativo(nuovo):
        return True
    return feed._age_hours(str(vecchio.get("generated_at", ""))) >= RINFRESCO_ORE


def _scrivi(dest: Path, data: dict) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"scritto {dest} ({dest.stat().st_size / 1024:.0f} KB)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest", nargs="?", default=config.FEED_PATH)
    # Il sito vuole i dati di adesso, compresi i download, anche quando
    # catalog.json resta com'era perche' non e' cambiato niente di importante.
    ap.add_argument("--fresco", help="dove scrivere comunque i dati appena letti")
    args = ap.parse_args(argv)

    dest = Path(args.dest)
    data = build()
    print()
    if args.fresco:
        _scrivi(Path(args.fresco), data)
    try:
        vecchio = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        vecchio = None
    if not da_riscrivere(vecchio, data):
        print(f"{dest}: niente di nuovo, resta quello di prima")
        return 0
    _scrivi(dest, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
