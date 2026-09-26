"""Controllo della versione dell'hub stesso.

Un'applicazione che si scarica da GitHub deve sapere quando e' vecchia,
altrimenti la gente resta per mesi su una versione con bug gia' corretti.

L'hub non si sostituisce da solo l'eseguibile mentre e' in esecuzione: scarica
la versione nuova, la mostra in Esplora risorse e si chiude. E' meno appariscente
di un aggiornamento automatico, ma non lascia mai l'utente con un eseguibile a
meta' se qualcosa va storto.

Il controllo non costa nulla quando il catalogo pre-generato e' disponibile:
la Action ci mette dentro anche l'ultima release dell'hub.
"""

from __future__ import annotations

import re

from . import __version__, config
from .ghclient import API, GitHubClient

# Estensioni considerate "l'eseguibile dell'hub" fra gli allegati della release.
BINARY_EXT = (".exe",)


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" -> (1, 2, 3). Le parti non numeriche valgono 0."""
    numbers = re.findall(r"\d+", str(text or ""))
    if not numbers:
        return (0,)
    return tuple(int(n) for n in numbers[:4])


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    # Confronto a parita' di lunghezza: (1, 1) deve battere (1, 0, 5).
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def _shape(release: dict) -> dict:
    assets = release.get("assets") or []
    binary = None
    for asset in assets:
        name = str(asset.get("name", ""))
        if name.lower().endswith(BINARY_EXT):
            binary = {
                "name": name,
                "url": asset.get("browser_download_url") or asset.get("url") or "",
                "size": asset.get("size") or 0,
            }
            break

    tag = release.get("tag_name") or release.get("tag") or ""
    return {
        "version": tag,
        "name": release.get("name") or tag,
        "notes": release.get("body") or "",
        "url": release.get("html_url") or "",
        "date": release.get("published_at") or release.get("date") or "",
        "asset": binary,
    }


def latest_from_feed(feed_data: dict | None) -> dict | None:
    """L'ultima release dell'hub cosi' come la scrive la Action nel catalogo."""
    if not feed_data:
        return None
    release = feed_data.get("hub_release")
    return _shape(release) if isinstance(release, dict) and release else None


def latest_from_api(client: GitHubClient) -> dict | None:
    """Ripiego: una richiesta all'API se il catalogo non c'e'."""
    url = f"{API}/repos/{client.user}/{config.FEED_REPO}/releases/latest"
    try:
        data = client.get_json(url)
    except Exception:
        return None
    return _shape(data) if isinstance(data, dict) and data.get("tag_name") else None


def check(client: GitHubClient, feed_data: dict | None = None) -> dict:
    """Dice se c'e' una versione piu' recente dell'hub."""
    release = latest_from_feed(feed_data)
    if release is None:
        release = latest_from_api(client)

    if not release or not release.get("version"):
        return {"available": False, "current": __version__}

    return {
        "available": is_newer(release["version"]),
        "current": __version__,
        **release,
    }
