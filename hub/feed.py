"""Catalogo pre-generato: la via per non consumare il limite di GitHub.

Senza autenticazione l'API concede 60 richieste all'ora per IP e un controllo
completo ne usa 6. Il limite e' per indirizzo, quindi ogni utente ha la sua
quota e mille utenti non se la dividono: il problema serio non e' il numero di
utenti, ma chi sta dietro a un IP condiviso (CGNAT, reti aziendali) e chi
ricontrolla spesso.

Qui si toglie di mezzo il problema alla radice. Una GitHub Action rigenera
`catalog.json` con dentro tutto il necessario e l'hub lo scarica da
raw.githubusercontent, che **non** passa dall'API e non ha quel tetto: una
richiesta sola, e il contatore resta a 60.

Se il file non c'e' o e' troppo vecchio, il chiamante torna all'API: il feed e'
un'ottimizzazione, non una dipendenza.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from . import __version__, config

TIMEOUT = 20
UA = f"Sici29-Hub/{__version__}"

FORMAT_VERSION = 1


def _age_hours(stamp: str) -> float:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return float("inf")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600


def fetch(url: str | None = None, max_age_hours: float | None = None) -> dict | None:
    """Scarica il catalogo pre-generato, o None se non e' utilizzabile."""
    url = url or config.FEED_URL
    max_age = config.FEED_MAX_AGE_HOURS if max_age_hours is None else max_age_hours

    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    # Un formato piu' recente di quello che sappiamo leggere va ignorato,
    # altrimenti un hub vecchio interpreterebbe male i campi nuovi.
    if int(data.get("version", 0)) != FORMAT_VERSION:
        return None
    if not isinstance(data.get("entries"), list) or not data["entries"]:
        return None
    if _age_hours(data.get("generated_at", "")) > max_age:
        return None

    return data


def entries_from(data: dict) -> list[dict]:
    """Voci nella stessa forma che produce catalog.discover()."""
    out = []
    for item in data.get("entries", []):
        if not isinstance(item, dict):
            continue
        repo = item.get("repo")
        if not isinstance(repo, dict) or not repo.get("name"):
            continue
        out.append(
            {
                "repo": repo,
                "marker": item.get("marker") or {},
                "releases": item.get("releases") or [],
            }
        )
    return out


def stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
