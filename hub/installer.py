"""Scaricamento e avvio degli installer delle traduzioni."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from . import paths
from .ghclient import UA

CHUNK = 64 * 1024
TIMEOUT = 30

ProgressCb = Callable[[dict], None]


class DownloadError(Exception):
    pass


class Cancelled(DownloadError):
    """Il download e' stato interrotto dall'utente, non da un errore."""


def _safe_name(name: str) -> str:
    keep = "-_. ()[]"
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned or "installer.exe"


def gia_scaricato(filename: str, tag: str, size: int = 0) -> Path | None:
    """L'installer di quel rilascio, se e' gia' sul disco.

    Il nome del file e' lo stesso a ogni versione (Aniimo-Italian-
    Translation.exe), quindi non basta che esista: accanto ci sta un file
    col tag del rilascio da cui viene, e anche la dimensione deve tornare.
    Serve alle voci del menu - controllo, ripristino - che altrimenti
    riscaricherebbero 40 MB per leggere due righe.
    """
    dest = paths.downloads_dir() / _safe_name(filename)
    try:
        if not dest.is_file():
            return None
        if dest.with_suffix(dest.suffix + ".tag").read_text(encoding="utf-8").strip() != tag:
            return None
        if size and dest.stat().st_size != size:
            return None
    except OSError:
        return None
    return dest


def download(
    url: str,
    filename: str,
    on_progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    tag: str = "",
) -> Path:
    """Scarica un allegato mostrando l'avanzamento.

    Il file viene scritto con estensione .part e rinominato solo a fine
    scaricamento: un download interrotto non lascia mai un .exe monco che
    qualcuno potrebbe poi lanciare.

    `should_stop` viene interrogata a ogni blocco: e' cosi' che il pulsante
    di annullamento interrompe un file da 30 MB senza aspettarne la fine.
    """
    dest = paths.downloads_dir() / _safe_name(filename)
    part = dest.with_suffix(dest.suffix + ".part")

    try:
        with requests.get(
            url, stream=True, timeout=TIMEOUT, headers={"User-Agent": UA}
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            last = 0.0

            with open(part, "wb") as fh:
                for chunk in resp.iter_content(CHUNK):
                    if should_stop and should_stop():
                        raise Cancelled("Scaricamento annullato.")
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)

                    # Non inondiamo la UI: al massimo un aggiornamento ogni 100ms.
                    now = time.monotonic()
                    if on_progress and (now - last > 0.1 or done == total):
                        last = now
                        on_progress(
                            {
                                "done": done,
                                "total": total,
                                "percent": (done / total * 100) if total else 0,
                            }
                        )
    except Cancelled:
        part.unlink(missing_ok=True)
        raise
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(
            "Scaricamento non riuscito: controlla la connessione e riprova."
        ) from exc

    if total and done < total:
        part.unlink(missing_ok=True)
        raise DownloadError("Il file scaricato e' incompleto.")

    dest.unlink(missing_ok=True)
    part.rename(dest)
    if tag:
        try:
            dest.with_suffix(dest.suffix + ".tag").write_text(tag, encoding="utf-8")
        except OSError:
            pass
    return dest


def _avvio_negato(exc: OSError) -> DownloadError:
    # Il caso piu' frequente e' l'antivirus che mette in quarantena un
    # installer non firmato: dirlo risparmia una segnalazione di bug.
    return DownloadError(
        "Non riesco ad avviare l'installer. Se l'antivirus l'ha bloccato, "
        "controlla la quarantena."
    )


def run(path: Path) -> int:
    """Lancia l'installer nella sua finestra, col suo menu, e aspetta.

    E' la via d'uscita per quello che l'hub non sa fare da se': da "Apri
    l'installer completo" si arriva a tutte le opzioni del menu originale.
    """
    try:
        proc = subprocess.Popen([str(path)], cwd=str(path.parent))
    except OSError as exc:
        raise _avvio_negato(exc) from exc
    return proc.wait()


# --- esecuzione senza finestra -----------------------------------------------
#
# Gli installer delle traduzioni hanno tutti, oltre al menu, una modalita' a
# comandi (`install`, `restore`, `check`...) che non fa domande e non aspetta
# "Premi Invio". L'hub li guida da li', senza finestra, e mostra quello che
# scrivono dentro la propria interfaccia.
#
# Un limite da sapere: sono programmi Python impacchettati con PyInstaller, e
# quando scrivono su una pipe invece che su una console tengono l'output in un
# buffer fino alla fine. Le righe arrivano tutte insieme, a lavoro finito. La
# variabile PYTHONUNBUFFERED non serve: gli eseguibili PyInstaller la ignorano
# (verificato). Il rimedio sta negli installer, una riga:
#
#     sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
#
# Da quando c'e' quella riga le fasi arrivano in diretta, senza toccare l'hub.

# Colori e movimenti del cursore. Gli installer li spengono da soli quando
# l'output non va a una console, ma un'altra versione potrebbe non farlo.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Un'installazione vera dura secondi. Oltre questo tempo l'installer e' fermo
# su qualcosa - un file bloccato, una domanda che non doveva fare - e non si
# sblocchera' da solo.
TEMPO_MASSIMO = 15 * 60


def _testo(grezzo: bytes) -> str:
    """Una riga d'uscita dell'installer, qualunque codifica abbia usato.

    Gli installer attuali scrivono in UTF-8; uno che non lo facesse
    scriverebbe nella codifica di Windows, e "gia'" arriverebbe spezzato.
    """
    try:
        return grezzo.decode("utf-8")
    except UnicodeDecodeError:
        return grezzo.decode("cp1252", "replace")


def esegui(
    percorso: Path,
    argomenti: list[str],
    on_riga: Callable[[str], None] | None = None,
    tempo_massimo: float = TEMPO_MASSIMO,
) -> dict:
    """Esegue l'installer senza finestra e ne raccoglie l'output.

    L'ingresso e' chiuso: se l'installer facesse una domanda, riceverebbe
    "fine dell'input" e uscirebbe con un errore, invece di restare appeso per
    sempre ad aspettare una risposta che nessuno puo' dare.

    Torna {"codice", "righe", "scaduto"}.
    """
    try:
        proc = subprocess.Popen(
            [str(percorso), *argomenti],
            cwd=str(percorso.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise _avvio_negato(exc) from exc

    scaduto = threading.Event()

    def ferma() -> None:
        scaduto.set()
        proc.kill()

    orologio = threading.Timer(tempo_massimo, ferma)
    orologio.daemon = True
    orologio.start()

    righe: list[str] = []
    try:
        for grezzo in iter(proc.stdout.readline, b""):
            # Prima via il fine riga, POI le barre di avanzamento. Su Windows
            # ogni riga finisce con \r\n: tenendo "l'ultimo pezzo dopo \r"
            # senza togliere prima il fine riga restava solo "\n", e ogni
            # riga spariva. Successo davvero, e l'ha scoperto solo la prova
            # con l'installer vero. Le barre si riscrivono sulla stessa riga
            # con \r in mezzo: di quelle conta solo l'ultimo stato.
            riga = _ANSI.sub("", _testo(grezzo)).rstrip("\r\n").split("\r")[-1].rstrip()
            if not riga.strip():
                continue
            righe.append(riga)
            if on_riga:
                on_riga(riga)
        codice = proc.wait()
    finally:
        orologio.cancel()
        # Senza, ogni operazione lascerebbe aperto un handle di Windows.
        proc.stdout.close()

    return {"codice": codice, "righe": righe, "scaduto": scaduto.is_set()}


# Righe che l'installer scrive per chi lo sviluppa: all'utente non dicono
# niente, e nel riepilogo farebbero solo rumore.
_DIAGNOSTICA = re.compile(
    r"^(Statistiche|Digest[^:]*|Risorse Lua|Build gi.? testate|Stringhe)\s*:"
    r"|\(diagnostic[oa]\)"
    r"|^[=!\-_*]{8,}$",
    re.IGNORECASE,
)
_GIOCO_APERTO = re.compile(r"chiudi.*(gioco|launcher)|gioco.*aperto|is running", re.IGNORECASE)
_PARZIALE = re.compile(r"fallback|non saranno tradott|attenzione", re.IGNORECASE)
_CONSIGLIO = re.compile(r"^lingua da selezionare in gioco", re.IGNORECASE)


def riassumi(esito: dict) -> dict:
    """Da quello che ha scritto l'installer, quello che serve a una persona.

    Torna {"ok", "parziale", "messaggio", "consiglio", "righe"}: il messaggio
    va nella notifica, il consiglio (la lingua da scegliere in gioco) in
    evidenza, le righe nel dettaglio per chi vuole leggere tutto.
    """
    righe = esito.get("righe") or []
    utili = [r for r in righe if not _DIAGNOSTICA.search(r.strip())]
    ok = esito.get("codice") == 0 and not esito.get("scaduto")

    consiglio = next((r.strip() for r in utili if _CONSIGLIO.search(r.strip())), "")

    if esito.get("scaduto"):
        messaggio = "L'installer non ha finito entro 15 minuti ed è stato fermato."
    elif not ok and any(_GIOCO_APERTO.search(r) for r in righe):
        messaggio = "Chiudi il gioco e il suo launcher, poi riprova."
    elif not ok and any(r.lower().startswith("usage:") for r in righe):
        # Opzioni che l'installer non conosce: e' un problema di
        # configurazione dell'hub, non qualcosa che l'utente puo' sistemare.
        messaggio = (
            "Questo installer non accetta i comandi dell'hub: aprilo dal menu "
            "“Altro” con “Apri l'installer completo”."
        )
    elif not ok:
        errori = [r for r in utili if r.lower().startswith(("errore", "error"))]
        messaggio = (errori or utili or ["L'installer si è chiuso con un errore."])[-1]
        messaggio = re.sub(r"^errore\s*:\s*", "", messaggio, flags=re.IGNORECASE)
    else:
        spunta = next((r for r in utili if "✓" in r), "")
        messaggio = (spunta or (utili[-1] if utili else "Fatto.")).replace("✓", "").strip()

    return {
        "ok": ok,
        "parziale": ok and any(_PARZIALE.search(r) for r in righe),
        "messaggio": messaggio,
        "consiglio": consiglio,
        "righe": utili,
    }


def reveal(path: Path | str) -> None:
    """Apre Esplora risorse sul file o sulla cartella indicata."""
    target = Path(path)
    try:
        if target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)])
        elif target.exists():
            subprocess.Popen(["explorer", str(target)])
    except OSError:
        pass
