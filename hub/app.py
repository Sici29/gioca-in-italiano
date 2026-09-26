"""Avvio della finestra dell'hub."""

from __future__ import annotations

import ctypes
import sys
import traceback
from datetime import datetime

from . import APP_TITLE, __version__, auth, journal, paths, singleton, state
from .api import Api

WIDTH = 1300
HEIGHT = 860
MIN_SIZE = (940, 640)

# Lo stesso colore del fondo della UI: evita il lampo bianco all'apertura.
BACKGROUND = "#0B1015"


def _screen_size() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 0, 0


def _restore_geometry(local: dict) -> dict:
    """Riprende dimensioni e posizione dell'ultima volta, se hanno ancora senso.

    Il controllo non e' pignoleria: chi stacca un monitor si ritroverebbe la
    finestra aperta fuori dallo schermo, senza modo di riportarla indietro.
    """
    saved = local.get("window") or {}
    geometry = {"width": WIDTH, "height": HEIGHT}

    sw, sh = _screen_size()
    width = int(saved.get("width") or 0)
    height = int(saved.get("height") or 0)
    if width >= MIN_SIZE[0] and height >= MIN_SIZE[1]:
        geometry["width"] = min(width, sw) if sw else width
        geometry["height"] = min(height, sh) if sh else height

    x, y = saved.get("x"), saved.get("y")
    if x is not None and y is not None and sw and sh:
        # Basta che un angolo resti visibile perche' la finestra sia recuperabile.
        if -50 <= int(x) <= sw - 200 and -10 <= int(y) <= sh - 120:
            geometry["x"] = int(x)
            geometry["y"] = int(y)

    return geometry


def run(debug: bool = False) -> int:
    log = journal.setup(debug)
    log.info("avvio hub %s (frozen=%s)", __version__, getattr(sys, "frozen", False))

    # Una riga sola, ma e' la prima cosa da guardare quando qualcuno scrive
    # "non riesco ad accedere": dice se questa copia dell'hub ha le credenziali
    # dell'applicazione e da dove le prende. Nessun valore, solo lo stato.
    log.info(
        "accesso in-app: %s (credenziali: %s)",
        "un clic" if auth.one_click() else ("solo codice" if auth.configured() else "no"),
        auth.credentials_source() or "nessuna",
    )

    if not singleton.acquire():
        log.info("istanza gia' aperta: porto in primo piano e chiudo")
        singleton.focus_existing()
        return 0

    try:
        import webview
    except ImportError:
        print(
            "Manca pywebview. Installalo con:\n\n    pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        log.error("pywebview non installato")
        return 1

    index = paths.resource_path("web", "index.html")
    if not index.exists():
        log.error("interfaccia non trovata: %s", index)
        print(f"Interfaccia non trovata: {index}", file=sys.stderr)
        return 1

    local = state.load()
    geometry = _restore_geometry(local)

    api = Api()
    window = webview.create_window(
        APP_TITLE,
        url=str(index),
        js_api=api,
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        text_select=False,
        **geometry,
    )
    api._window = window
    api.start_auto_refresh()

    # Dimensione e posizione si aggiornano in memoria mentre si usa la
    # finestra, e finiscono su disco una volta sola alla chiusura.
    corrente = dict(geometry)

    def on_resized(width, height):
        corrente["width"], corrente["height"] = int(width), int(height)

    def on_moved(x, y):
        corrente["x"], corrente["y"] = int(x), int(y)

    def on_closing():
        try:
            saved = state.load()
            saved["window"] = corrente
            state.save(saved)
            log.info("chiusura, geometria salvata %s", corrente)
        except Exception:
            log.exception("non sono riuscito a salvare la geometria")

    try:
        window.events.resized += on_resized
        window.events.moved += on_moved
        window.events.closing += on_closing
    except Exception:
        # Versioni di pywebview senza questi eventi: si perde solo il ripristino.
        log.debug("eventi finestra non disponibili")

    try:
        # edgechromium e' WebView2, presente su Windows 10 21H2 e Windows 11.
        webview.start(debug=debug, gui="edgechromium" if sys.platform == "win32" else None)
    finally:
        api.shutdown()
        singleton.release()
        log.info("hub chiuso")
    return 0


def log_crash(message: str) -> None:
    """Scrive un errore di avvio su hub.log.

    Nell'eseguibile compilato non c'e' una console: senza questo file un avvio
    fallito sarebbe completamente muto, sia per te che per chi lo usa.
    """
    try:
        with open(paths.log_file(), "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{message}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    """Ingresso unico, usato sia da `python -m hub` sia dall'eseguibile."""
    args = argv if argv is not None else sys.argv
    try:
        return run(debug="--debug" in args)
    except BaseException:
        log_crash(
            f"Avvio fallito.\n"
            f"eseguibile: {sys.executable}\n"
            f"frozen: {getattr(sys, 'frozen', False)}\n"
            f"_MEIPASS: {getattr(sys, '_MEIPASS', '-')}\n\n"
            + traceback.format_exc()
        )
        raise
