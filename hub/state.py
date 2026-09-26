"""Stato locale: cosa e' installato, cosa l'utente ha gia' visto, impostazioni."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any

from . import paths

_LOCK = threading.Lock()

_DEFAULT: dict[str, Any] = {
    "version": 1,
    # repo -> {"tag": str, "installed_at": iso, "asset": str}
    "installed": {},
    # repo -> ultimo tag che l'utente ha visto nell'hub (serve per il badge NOVITA')
    "seen": {},
    # repo -> percorso di una copertina scelta a mano dall'utente
    "custom_covers": {},
    # numero della proposta -> id della reazione, per poter togliere il voto
    "voted": {},
    # dimensioni e posizione dell'ultima sessione
    "window": {},
    # gioco -> cartella trovata su disco, per non riscandire ogni volta
    "game_paths": {},
    # repo -> cartella del gioco scelta a mano, da passare all'installer
    # quando quella che trova da solo e' sbagliata
    "cartelle_scelte": {},
    # Notifiche di Windows: cosa e' gia' stato annunciato (repo -> tag, piu'
    # l'ultima versione dell'hub), per non ripeterlo a ogni controllo, e i
    # gettoni dei pulsanti "Aggiorna" (gettone -> repo e data).
    "notifiche": {"inviate": {}, "gettoni": {}},
    "settings": {
        "theme": "dark",
        "auto_refresh": True,
        "notify": True,
        "hidden_repos": [],
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    path = paths.state_file()
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("state.json non e' un oggetto")
        return _merge(json.loads(json.dumps(_DEFAULT)), data)
    except Exception:
        # Stato corrotto: si riparte puliti invece di far crashare l'hub.
        return json.loads(json.dumps(_DEFAULT))


def save(data: dict) -> None:
    """Scrittura atomica: niente state.json a meta' se manca la corrente."""
    path = paths.state_file()
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
