"""Registro degli eventi dell'hub.

Serve soprattutto a te: quando qualcuno scrive "non mi funziona", questo file
dice cosa ha fatto l'hub e dove si e' fermato. Nell'eseguibile non c'e' una
console, quindi senza registro non resterebbe traccia di nulla.

Ruota a 256 KB tenendo due file: abbastanza per ricostruire una sessione,
poco abbastanza da non gonfiare la cartella dati.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import paths

MAX_BYTES = 256 * 1024
BACKUPS = 2

log = logging.getLogger("hub")
_ready = False


def setup(debug: bool = False) -> logging.Logger:
    global _ready
    if _ready:
        return log

    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False

    try:
        handler = RotatingFileHandler(
            paths.log_file(), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        log.addHandler(handler)
    except OSError:
        # Cartella non scrivibile: l'hub deve funzionare lo stesso.
        log.addHandler(logging.NullHandler())

    _ready = True
    return log
