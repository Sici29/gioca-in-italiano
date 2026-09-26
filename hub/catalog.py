"""Costruzione del catalogo: scoperta dei repo, release, stato aggiornamenti.

E' il cuore dell'hub. Fa tre cose:
  - trova da solo quali repo dell'account sono traduzioni (regole in config.py)
  - per ognuno legge le release da GitHub e la copertina da Steam
  - confronta con lo stato locale per capire cosa e' nuovo o da aggiornare
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import compat, config, covers, feed, links, paths, scan, selfupdate, state
from .ghclient import GitHubClient, RateLimited

log = logging.getLogger("hub")

# Estensioni che l'hub considera "l'installer da lanciare".
INSTALLER_EXT = (".exe", ".msi")

STATUS_NOT_INSTALLED = "non_installato"
STATUS_UP_TO_DATE = "aggiornato"
STATUS_UPDATE = "aggiornamento"


def _pick_asset(assets: list[dict]) -> dict | None:
    """Sceglie l'allegato da scaricare: prima un installer, poi il resto."""
    if not assets:
        return None
    for asset in assets:
        if str(asset.get("name", "")).lower().endswith(INSTALLER_EXT):
            return asset
    return assets[0]


def _clean_assets(assets: list[dict]) -> list[dict]:
    out = []
    for a in assets or []:
        out.append(
            {
                "name": a.get("name") or "",
                "size": a.get("size") or 0,
                "downloads": a.get("download_count") or 0,
                "url": a.get("browser_download_url") or "",
            }
        )
    return out


def _clean_release(rel: dict) -> dict:
    assets = _clean_assets(rel.get("assets") or [])
    chosen = _pick_asset(assets)
    return {
        "tag": rel.get("tag_name") or "",
        "name": rel.get("name") or rel.get("tag_name") or "",
        "date": rel.get("published_at") or rel.get("created_at") or "",
        "body": rel.get("body") or "",
        "url": rel.get("html_url") or "",
        "prerelease": bool(rel.get("prerelease")),
        "assets": assets,
        "download": chosen,
        "downloads": sum(a["downloads"] for a in assets),
    }


def discover(client: GitHubClient, local: dict) -> list[dict]:
    """Elenca i repo dell'account e tiene solo le traduzioni.

    hub.json viene letto da raw.githubusercontent, che non consuma il rate
    limit dell'API: possiamo provarci su tutti i repo senza costi.
    """
    repos = client.list_repos()
    hidden = {r.lower() for r in local["settings"].get("hidden_repos", [])}

    # Scarta subito cio' che non puo' mai essere una traduzione, cosi' non
    # sprechiamo una richiesta hub.json per ogni fork o repo archiviato.
    candidates = [
        r
        for r in repos
        if not (r.get("fork") or r.get("archived") or r.get("private") or r.get("disabled"))
        and (r.get("name") or "").lower() not in config.ALWAYS_EXCLUDE
    ]

    def probe(repo: dict) -> tuple[dict, dict | None]:
        try:
            return repo, client.fetch_marker(repo.get("name") or "")
        except Exception:
            # Un marcatore illeggibile non deve far sparire il repo: si
            # ricade sugli altri criteri di riconoscimento.
            log.warning("hub.json non leggibile per %s", repo.get("name"))
            return repo, None

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for repo, marker in pool.map(probe, candidates):
            if not config.looks_like_translation(repo, marker is not None):
                continue
            name = repo.get("name") or ""
            if name.lower() in hidden:
                continue
            if marker and marker.get("nascondi"):
                continue
            found.append({"repo": repo, "marker": marker or {}})
    return found


def _build_project(
    client: GitHubClient,
    entry: dict,
    local: dict,
    fetch_cover: bool = True,
    library: dict | None = None,
) -> dict:
    repo = entry["repo"]
    marker = entry["marker"]
    name = repo.get("name") or ""

    # Dal catalogo pre-generato le release arrivano gia' normalizzate e non
    # costano una richiesta; dall'API vanno ripulite qui.
    if "releases" in entry:
        releases = entry["releases"]
    else:
        releases = [_clean_release(r) for r in client.list_releases(name)]
    stable = [r for r in releases if not r["prerelease"]] or releases
    latest = stable[0] if stable else None

    title = (
        marker.get("nome_gioco")
        or marker.get("game")
        or config.pretty_game_name(name)
    )
    appid = marker.get("steam_appid") or marker.get("appid")
    try:
        appid = int(appid) if appid else None
    except (TypeError, ValueError):
        appid = None

    # Solo "non_su_steam": true impedisce la ricerca per nome. Un semplice
    # "steam_appid": null vale come "non lo so", e conviene cercare comunque:
    # NTE era dichiarato null ma su Steam c'e' eccome. Il rischio di agganciare
    # il gioco sbagliato lo copre gia' il punteggio di somiglianza in steam.py,
    # che su "Star Citizen" scarta da solo tutti i risultati.
    declares_no_steam = bool(marker.get("non_su_steam"))

    installed = local["installed"].get(name) or {}
    installed_tag = installed.get("tag")
    latest_tag = latest["tag"] if latest else None

    if not installed_tag:
        status = STATUS_NOT_INSTALLED
    elif latest_tag and installed_tag != latest_tag:
        status = STATUS_UPDATE
    else:
        status = STATUS_UP_TO_DATE

    # Segnalazione "novita'": confronta con l'ultimo tag che l'utente ha visto.
    seen_tag = local["seen"].get(name)
    if latest_tag and seen_tag is None:
        novita = "nuova"
    elif latest_tag and seen_tag != latest_tag:
        novita = "aggiornamento"
    else:
        novita = None

    project: dict[str, Any] = {
        "repo": name,
        "title": title,
        "description": marker.get("descrizione") or repo.get("description") or "",
        "url": repo.get("html_url") or "",
        "stars": repo.get("stargazers_count") or 0,
        "topics": repo.get("topics") or [],
        "pushed_at": repo.get("pushed_at") or "",
        "steam_appid": appid,
        "store_url": marker.get("sito")
        or (f"https://store.steampowered.com/app/{appid}/" if appid else ""),
        "engine": marker.get("motore_installazione") or "",
        "latest": latest,
        "releases": releases,
        "release_count": len(releases),
        "total_downloads": sum(r["downloads"] for r in releases),
        "installed_tag": installed_tag,
        "installed_at": installed.get("installed_at"),
        "status": status,
        "novita": novita,
        "cover": "",
        "cover_source": "",
        "tinta": "",
        "warning": "",
        # Riempiti piu' sotto: il gioco risulta installato su questo PC?
        "installed_game": False,
        "game_path": "",
        "game_source": "",
        "game_version": "",
        "game_build": 0,
        "compat": {},
        "avvio": "",
        "installer": {},
        "releases_url": links.releases(name),
        "bug_url": "",
    }

    if fetch_cover:
        path, info = covers.ensure_cover(
            repo=name,
            game_name=title,
            appid=appid,
            cover_url=marker.get("cover_url"),
            custom_path=local["custom_covers"].get(name),
            allow_search=not declares_no_steam,
        )
        project["cover"] = covers.data_uri(path)
        project["cover_source"] = info.get("source", "")
        # Il colore dominante viaggia col progetto: la card e il pannello dei
        # dettagli si tingono di quello, cosi' ogni gioco porta il suo.
        project["tinta"] = covers.tinta(path)
        avvisi = []
        if info.get("appid_mismatch"):
            avvisi.append(
                f"Il hub.json dichiara steam_appid {appid}, che su Steam e' un "
                f"altro gioco: ignorato."
            )
        if info.get("cover_url_morto"):
            avvisi.append(
                "Il cover_url dichiarato nel hub.json non risponde: "
                "la copertina arriva da un'altra fonte."
            )
        # Sono avvisi per chi pubblica, non per chi installa: un utente non
        # puo' farci niente, e leggere "il cover_url del hub.json non
        # risponde" gli fa solo pensare che qualcosa sia rotto. Vanno nel
        # registro, dove l'autore li trova.
        for avviso in avvisi:
            log.info("%s: %s", name, avviso)
        project["warning"] = " ".join(avvisi)
        resolved_appid = info.get("appid")
        if resolved_appid and resolved_appid != project["steam_appid"]:
            project["steam_appid"] = resolved_appid
            project["store_url"] = (
                f"https://store.steampowered.com/app/{resolved_appid}/"
            )

    # Abbinamento con la libreria locale, dopo la copertina perche' e' li' che
    # si scopre l'AppID dei giochi senza hub.json: averlo rende il confronto
    # esatto invece che basato sul nome.
    if library:
        found = scan.match(library, title, project["steam_appid"])
        if found:
            project["installed_game"] = True
            project["game_path"] = found.get("path", "")
            project["game_source"] = found.get("source", "")
            project["game_version"] = found.get("version") or found.get("branch") or ""
            # Mostrato nei dettagli: e' il numero da copiare in `game_build`
            # dentro il hub.json per avere il confronto esatto.
            project["game_build"] = found.get("build") or 0
            # La domanda che decide se la traduzione funzionera' davvero:
            # copre la versione del gioco che hai, o una precedente?
            project["compat"] = compat.valuta(marker, latest, found)
            project["avvio"] = come_si_avvia(found, title)

    # Come guidare l'installer di questa traduzione senza la sua finestra.
    project["installer"] = config.installer_profilo(name, marker.get("installer"))

    project["bug_url"] = links.bug_report(project)
    return project


# --- l'ultimo catalogo buono -------------------------------------------------
#
# L'avviso diceva "vedi i dati salvati dall'ultima volta", ma dati salvati non
# ce n'erano: se GitHub non rispondeva all'avvio, la griglia restava vuota.
# Adesso l'ultimo catalogo riuscito sta su disco e serve a due cose:
#
#   - all'avvio si mostra subito, mentre il controllo vero parte dietro: la
#     finestra e' piena da subito invece di aspettare la rete;
#   - quando un controllo fallisce, resta quello che c'era, e cambia solo
#     l'avviso in cima.

ULTIMO = "ultimo_catalogo.json"


def salva_ultimo(result: dict, checked_at: str = "") -> None:
    """Mette da parte un catalogo riuscito. Le copertine restano fuori: sono
    gia' su disco come immagini, e dentro il JSON peserebbero dieci volte."""
    import os
    import tempfile

    progetti = [
        {k: v for k, v in p.items() if k != "cover"} for p in result.get("projects") or []
    ]
    if not progetti:
        return
    dati = {
        "projects": progetti,
        "library": result.get("library") or {},
        "proposals": result.get("proposals") or [],
        "source": result.get("source") or "",
        "checked_at": checked_at,
    }
    destinazione = paths.cache_dir() / ULTIMO
    try:
        fd, provvisorio = tempfile.mkstemp(dir=str(destinazione.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dati, fh, ensure_ascii=False)
        os.replace(provvisorio, destinazione)
    except (OSError, TypeError, ValueError) as exc:
        log.warning("ultimo catalogo non salvato: %s", exc)


def carica_ultimo() -> dict | None:
    """L'ultimo catalogo riuscito, con copertine e stato locale rimessi a posto."""
    try:
        with open(paths.cache_dir() / ULTIMO, "r", encoding="utf-8") as fh:
            dati = json.load(fh)
    except (OSError, ValueError):
        return None
    progetti = dati.get("projects") if isinstance(dati, dict) else None
    if not isinstance(progetti, list) or not progetti:
        return None

    for progetto in progetti:
        immagine = covers.percorso(progetto.get("repo", ""))
        progetto["cover"] = covers.data_uri(immagine) if immagine.exists() else ""
    # Quello che e' installato puo' essere cambiato dall'ultima volta.
    ricalcola_stato(progetti)
    dati["projects"] = progetti
    dati["error"] = ""
    return dati


def unisci_mancanti(nuovo: dict, vecchio: dict | None) -> dict:
    """Rimette nel catalogo nuovo le traduzioni che non si sono potute
    ricontrollare, prendendole da quello precedente."""
    mancanti = set(nuovo.get("mancanti") or [])
    if not mancanti or not vecchio:
        return nuovo
    presenti = {p["repo"] for p in nuovo.get("projects") or []}
    recuperati = [
        p for p in vecchio.get("projects") or []
        if p.get("repo") in mancanti and p.get("repo") not in presenti
    ]
    if recuperati:
        nuovo["projects"] = (nuovo.get("projects") or []) + recuperati
        nuovo["projects"].sort(
            key=lambda p: (p.get("latest") or {}).get("date", ""), reverse=True
        )
    return nuovo


def come_si_avvia(gioco: dict | None, titolo: str = "") -> str:
    """Da dove si fa partire il gioco, se si puo'.

    Steam lo sa fare da se' - overlay, salvataggi nel cloud, controllo degli
    aggiornamenti - e va lasciato fare a lui: l'hub gli chiede solo di
    avviare quel gioco. Star Citizen passa dal suo launcher, perche' chiede
    l'accesso all'account RSI. Per il resto l'hub non tira a indovinare
    quale eseguibile sia quello giusto.
    """
    if not gioco:
        return ""
    if gioco.get("source") == scan.SOURCE_STEAM and gioco.get("appid"):
        return f"steam:{gioco['appid']}"
    if (titolo or gioco.get("name", "")).strip().lower() == "star citizen":
        return "rsi" if scan.launcher_rsi(gioco.get("path")) else ""
    return ""


def ricalcola_stato(projects: list[dict], local: dict | None = None) -> list[dict]:
    """Rifa' "installata / da aggiornare / non installata" senza toccare la rete.

    Dopo un'installazione l'unica cosa cambiata e' sul disco di chi usa l'hub:
    il catalogo di GitHub e' identico a un minuto prima. Ricostruirlo daccapo
    sarebbe sbagliato due volte - costa richieste e viene rimandato dal freno
    dei dieci minuti, che e' esattamente il motivo per cui la card restava
    indietro dopo un'installazione riuscita.
    """
    local = local if local is not None else state.load()
    installati = local.get("installed") or {}
    visti = local.get("seen") or {}

    for progetto in projects:
        nome = progetto.get("repo")
        installato = installati.get(nome) or {}
        tag_installato = installato.get("tag")
        ultima = (progetto.get("latest") or {}).get("tag")

        progetto["installed_tag"] = tag_installato
        progetto["installed_at"] = installato.get("installed_at")
        if not tag_installato:
            progetto["status"] = STATUS_NOT_INSTALLED
        elif ultima and tag_installato != ultima:
            progetto["status"] = STATUS_UPDATE
        else:
            progetto["status"] = STATUS_UP_TO_DATE

        visto = visti.get(nome)
        if ultima and visto is None:
            progetto["novita"] = "nuova"
        elif ultima and visto != ultima:
            progetto["novita"] = "aggiornamento"
        else:
            progetto["novita"] = None

    return projects


def clean_proposal(issue: dict) -> dict:
    """Una proposta di traduzione, con i suoi voti.

    I voti sono le reazioni di GitHub: niente server, niente database, e la
    moderazione e' quella che hai gia' sulle issue. Il pollice in su e' il voto
    a favore, il pollice in giu' si sottrae.
    """
    reactions = issue.get("reactions") or {}
    up = int(reactions.get("+1") or 0)
    down = int(reactions.get("-1") or 0)
    labels = [
        l.get("name", "") if isinstance(l, dict) else str(l)
        for l in (issue.get("labels") or [])
    ]
    return {
        "number": issue.get("number") or 0,
        "title": (issue.get("title") or "").strip(),
        "url": issue.get("html_url") or "",
        "votes": up - down,
        "up": up,
        "comments": issue.get("comments") or 0,
        "created": issue.get("created_at") or "",
        "labels": labels,
        "in_lavorazione": any(
            l.lower() in ("in lavorazione", "in corso", "wip") for l in labels
        ),
    }


def e_una_proposta(issue: dict) -> bool:
    """Un'issue e' una proposta se ha il titolo delle proposte o l'etichetta.

    Il titolo e' il criterio che conta. La prima versione filtrava per
    etichetta, ma GitHub toglie in silenzio le etichette alle issue aperte da
    chi non ha i permessi di scrittura sul repo: le proposte della comunita'
    arrivavano senza, e la bacheca le ignorava tutte. Restava visibile solo
    quello che apriva l'autore. L'etichetta vale ancora, per le proposte che
    l'autore apre o sistema a mano.
    """
    titolo = (issue.get("title") or "").strip().lower()
    if titolo.startswith(config.PROPOSAL_PREFIX.lower()):
        return True
    etichette = [
        (l.get("name", "") if isinstance(l, dict) else str(l)).lower()
        for l in (issue.get("labels") or [])
    ]
    return config.PROPOSAL_LABEL.lower() in etichette


def fetch_proposals(client: GitHubClient) -> list[dict]:
    """Bacheca delle proposte, ordinata per voti."""
    try:
        issues = client.list_issues(config.SUGGESTIONS_REPO)
    except Exception:
        return []
    out = [clean_proposal(i) for i in issues if e_una_proposta(i)]
    out.sort(key=lambda p: (p["votes"], p["comments"]), reverse=True)
    return out


def _drop_hidden(entries: list[dict], local: dict) -> list[dict]:
    """Toglie le voci nascoste dalle impostazioni o dal loro hub.json."""
    hidden = {r.lower() for r in local["settings"].get("hidden_repos", [])}
    out = []
    for entry in entries:
        name = (entry["repo"].get("name") or "").lower()
        if name in hidden or name in config.ALWAYS_EXCLUDE:
            continue
        if (entry.get("marker") or {}).get("nascondi"):
            continue
        out.append(entry)
    return out


def build(
    client: GitHubClient | None = None,
    fetch_covers: bool = True,
    scan_library: bool = True,
    use_feed: bool = True,
    check_update: bool = False,
) -> dict:
    """Catalogo completo, pronto da mandare alla UI."""
    client = client or GitHubClient()
    local = state.load()

    # La scansione e' locale e velocissima (centesimi di secondo), quindi si
    # fa una volta sola qui e si passa a tutti i progetti.
    installed: dict | None = None
    if scan_library:
        try:
            # I percorsi gia' noti evitano di riscandire i dischi: la ricerca
            # dei giochi fuori dagli store costa un paio di secondi, e va
            # pagata solo la prima volta o se il gioco viene spostato.
            installed = scan.scan(known_paths=local.get("game_paths"))
        except Exception:
            installed = None

    result: dict[str, Any] = {
        "projects": [],
        "error": "",
        "rate_remaining": None,
        "rate_reset": 0,
        "library": {
            "count": installed["count"] if installed else 0,
            "sources": installed["sources"] if installed else [],
        },
        "known_paths": (installed or {}).get("known_paths", {}),
        "suggest_url": links.suggest_translation(),
        "source": "",
        "generated_at": "",
        "proposals": [],
        "hub_update": None,
    }

    # Prima si prova il catalogo pre-generato: una richiesta fuori dall'API,
    # che non intacca il limite orario. L'API resta la riserva.
    entries: list[dict] | None = None
    feed_data: dict | None = None
    if use_feed:
        feed_data = feed.fetch()
        if feed_data:
            entries = _drop_hidden(feed.entries_from(feed_data), local)
            result["source"] = "feed"
            result["generated_at"] = feed_data.get("generated_at", "")
            result["proposals"] = feed_data.get("proposals") or []

    if entries is None:
        try:
            entries = discover(client, local)
            result["source"] = "api"
        except RateLimited as exc:
            result["error"] = "rate_limit"
            result["rate_reset"] = exc.reset_ts
            return result
        except Exception as exc:  # rete assente, DNS, GitHub giu', ecc.
            # Alla finestra va un codice, non il testo dell'eccezione: prima
            # arrivava "401 Client Error: Unauthorized for url: https://..."
            # dritto in faccia a chi voleva solo vedere le sue traduzioni.
            # Il dettaglio tecnico resta nel registro, dove serve.
            log.warning("catalogo non aggiornato: %s", exc)
            result["error"] = "rete"
            return result

    limitato = []

    def work(entry: dict) -> dict | None:
        try:
            return _build_project(
                client, entry, local, fetch_cover=fetch_covers, library=installed
            )
        except RateLimited:
            # Non e' un guasto della traduzione: GitHub ha chiuso il rubinetto
            # a meta' giro. Si segna, e chi chiama tiene la versione di prima.
            limitato.append(True)
            log.info("traduzione rimandata per il limite di GitHub: %s",
                     (entry.get("repo") or {}).get("name", "?"))
            return None
        except Exception:
            # Senza questa riga una traduzione che fallisce sparisce dalla
            # griglia senza lasciare traccia da nessuna parte: e' successo con
            # Star Citizen e non c'era modo di capire perche'.
            log.exception(
                "traduzione saltata: %s", (entry.get("repo") or {}).get("name", "?")
            )
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        projects = [p for p in pool.map(work, entries) if p]

    if len(projects) < len(entries):
        mancanti = {e["repo"].get("name") for e in entries} - {p["repo"] for p in projects}
        log.warning("traduzioni non costruite: %s", ", ".join(sorted(mancanti)))
        # Chi chiama le rimette dal catalogo precedente: una traduzione che
        # non si e' riusciti a ricontrollare non deve sparire dalla griglia.
        result["mancanti"] = sorted(mancanti)
        if limitato and not result.get("error"):
            result["error"] = "rate_limit"

    # Prima le novita', poi per data dell'ultima release.
    def sort_key(p: dict):
        return (
            0 if p["novita"] else 1,
            p["latest"]["date"] if p.get("latest") else "",
        )

    projects.sort(key=sort_key, reverse=False)
    projects.sort(
        key=lambda p: p["latest"]["date"] if p.get("latest") else "", reverse=True
    )

    # Le proposte costano una richiesta sola, e col feed nemmeno quella.
    if result["source"] != "feed":
        result["proposals"] = fetch_proposals(client)

    # Il controllo della versione dell'hub e' gratis quando c'e' il catalogo
    # (la Action ci mette dentro anche l'ultima release); altrimenti costa una
    # richiesta, e per questo si fa una volta sola per sessione.
    if check_update or feed_data:
        try:
            result["hub_update"] = selfupdate.check(client, feed_data)
        except Exception:
            result["hub_update"] = None

    result["projects"] = projects
    result["rate_remaining"] = client.rate_remaining
    result["rate_reset"] = client.rate_reset
    return result


def summary(projects: list[dict]) -> dict:
    """Numeri della barra di stato."""
    updates = [p for p in projects if p["status"] == STATUS_UPDATE]
    novita = [p for p in projects if p["novita"]]
    latest_date = ""
    for p in projects:
        if p.get("latest") and p["latest"]["date"] > latest_date:
            latest_date = p["latest"]["date"]
    return {
        "count": len(projects),
        "downloads": sum(p["total_downloads"] for p in projects),
        "releases": sum(p["release_count"] for p in projects),
        "updates": len(updates),
        "novita": len(novita),
        "installed": len([p for p in projects if p["installed_tag"]]),
        "owned": len([p for p in projects if p["installed_game"]]),
        "last_release": latest_date,
    }
