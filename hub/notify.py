"""Notifiche di Windows: aggiornamenti, traduzioni nuove, nuove versioni dell'hub.

Tre cose rendevano le notifiche di prima poco presentabili:

- comparivano a nome di "Windows PowerShell", con la sua icona. Per mostrare
  una notifica Windows vuole l'identita' di un'app registrata (un
  AppUserModelID), e si prendeva in prestito quella di PowerShell. Ora l'hub
  registra la sua sotto HKEY_CURRENT_USER: niente permessi di amministratore,
  niente collegamenti nel menu Start. E' lo stesso meccanismo che usa la
  libreria di Microsoft per le app desktop non impacchettate;
- erano due righe di testo nudo. Ora hanno la copertina del gioco, la
  versione, cosa cambia e un pulsante che porta dritto all'aggiornamento;
- tornavano a ogni controllo, cioe' ogni mezz'ora, finche' l'aggiornamento
  restava da fare. Ora ogni versione si annuncia una volta sola.

I pulsanti funzionano con un link giocainitaliano:, registrato insieme al
nome. Chiunque puo' scrivere un link cosi' in una pagina web, quindi un link
da solo apre al massimo una scheda: per far partire un'installazione serve un
gettone che l'hub ha messo lui nella notifica, e che vale una volta sola.

Le notifiche restano un di piu': se Windows non collabora (Non disturbare,
criteri aziendali) l'avviso vero e' dentro l'hub, e qualsiasi errore qui viene
ignorato.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, quote, unquote

from . import APP_TITLE, paths

AUMID = "Sici29.GiocaInItaliano"
PROTOCOLLO = "giocainitaliano"

# Il ripiego se la registrazione non riesce: questo AppID esiste sempre, e una
# notifica a nome di PowerShell e' meglio di nessuna notifica.
AUMID_POWERSHELL = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

# Chiave speciale fra le notifiche gia' inviate: l'ultima versione dell'hub
# annunciata. I nomi dei repo non cominciano con "_".
CHIAVE_HUB = "__hub__"

# Piu' di cosi' in un colpo solo e' rumore: il resto lo dice l'hub.
MAX_PER_CONTROLLO = 3

# Quanto vale il gettone di un pulsante "Aggiorna", e quanti se ne tengono.
DURATA_GETTONE = 14 * 86400
MAX_GETTONI = 50

_registrata = False


# --- registrazione -----------------------------------------------------------


def _icona() -> Path | None:
    """L'icona in un posto fisso.

    Windows la rilegge dal percorso registrato quando vuole, e la cartella
    temporanea in cui si scompatta l'eseguibile cambia a ogni avvio.
    """
    sorgente = paths.resource_path("web", "icona.png")
    dest = paths.data_dir() / "icona.png"
    try:
        if sorgente.exists() and (
            not dest.exists() or dest.stat().st_size != sorgente.stat().st_size
        ):
            shutil.copyfile(sorgente, dest)
        return dest if dest.exists() else None
    except OSError:
        return None


def registra(eseguibile: str | None = None, reg=None) -> bool:
    """Registra nome e icona dell'hub, e il link giocainitaliano: se c'e' l'exe.

    Il link si registra solo per l'eseguibile compilato: dai sorgenti non c'e'
    un programma sensato da far partire. Si riscrive a ogni avvio, cosi' se
    l'exe viene spostato il link segue.
    """
    global _registrata
    if reg is None:
        try:
            import winreg as reg
        except ImportError:
            return False
    try:
        with reg.CreateKey(reg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{AUMID}") as k:
            reg.SetValueEx(k, "DisplayName", 0, reg.REG_SZ, APP_TITLE)
            icona = _icona()
            if icona:
                reg.SetValueEx(k, "IconUri", 0, reg.REG_SZ, str(icona))
        if eseguibile:
            base = rf"Software\Classes\{PROTOCOLLO}"
            with reg.CreateKey(reg.HKEY_CURRENT_USER, base) as k:
                reg.SetValueEx(k, "", 0, reg.REG_SZ, f"URL:{APP_TITLE}")
                reg.SetValueEx(k, "URL Protocol", 0, reg.REG_SZ, "")
            with reg.CreateKey(reg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as k:
                reg.SetValueEx(k, "", 0, reg.REG_SZ, f'"{eseguibile}",0')
            with reg.CreateKey(reg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
                reg.SetValueEx(k, "", 0, reg.REG_SZ, f'"{eseguibile}" "%1"')
        _registrata = True
    except OSError:
        _registrata = False
    return _registrata


# --- i link giocainitaliano: -------------------------------------------------

_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def link_apri() -> str:
    return f"{PROTOCOLLO}:apri"


def link_mostra(repo: str) -> str:
    return f"{PROTOCOLLO}:mostra/{quote(repo)}"


def link_aggiorna(repo: str, gettone: str) -> str:
    return f"{PROTOCOLLO}:aggiorna/{quote(repo)}?t={quote(gettone)}"


def leggi_link(link: str) -> dict | None:
    """Cosa chiede un link giocainitaliano:, o None se non e' uno dei nostri."""
    testo = str(link or "").strip()
    if not testo.lower().startswith(PROTOCOLLO + ":"):
        return None
    resto = testo[len(PROTOCOLLO) + 1:].strip("/")
    percorso, _, domanda = resto.partition("?")
    azione, _, repo = percorso.partition("/")
    azione = azione.lower()
    repo = unquote(repo).strip("/")
    if azione == "apri":
        return {"azione": "apri"}
    if azione in ("mostra", "aggiorna") and _REPO.match(repo):
        gettone = dict(parse_qsl(domanda)).get("t", "")
        return {"azione": azione, "repo": repo, "gettone": gettone}
    return None


def usa_gettone(gettoni: dict, gettone: str, repo: str, ora: float | None = None) -> bool:
    """Il gettone e' valido per quel repo? Se si', lo consuma."""
    ora = time.time() if ora is None else ora
    voce = gettoni.get(gettone) if gettone else None
    if not isinstance(voce, dict) or voce.get("repo") != repo:
        return False
    del gettoni[gettone]
    return ora - float(voce.get("ts", 0)) <= DURATA_GETTONE


def pota_gettoni(gettoni: dict, ora: float | None = None) -> dict:
    """Via quelli scaduti, e comunque solo gli ultimi MAX_GETTONI."""
    ora = time.time() if ora is None else ora
    validi = [
        (k, v) for k, v in gettoni.items()
        if isinstance(v, dict) and ora - float(v.get("ts", 0)) <= DURATA_GETTONE
    ]
    validi.sort(key=lambda kv: kv[1].get("ts", 0))
    return dict(validi[-MAX_GETTONI:])


# --- passaggio di una richiesta all'hub gia' aperto --------------------------
#
# Il clic su una notifica fa partire un secondo hub, che trova il primo gia'
# aperto e deve chiudersi (una finestra sola). Prima di chiudersi lascia il link
# in un file, e il primo lo raccoglie: niente pipe ne' porte da aprire.

RICHIESTA = "richiesta.txt"
ETA_MASSIMA_RICHIESTA = 120


def lascia_richiesta(link: str) -> None:
    dest = paths.data_dir() / RICHIESTA
    tmp = dest.with_suffix(".tmp")
    try:
        tmp.write_text(str(link), encoding="utf-8")
        os.replace(tmp, dest)
    except OSError:
        pass


def prendi_richiesta(ora: float | None = None) -> str | None:
    """Il link lasciato da un secondo avvio, se c'e' ed e' recente."""
    percorso = paths.data_dir() / RICHIESTA
    try:
        eta = (time.time() if ora is None else ora) - percorso.stat().st_mtime
        link = percorso.read_text(encoding="utf-8").strip()
        percorso.unlink()
    except OSError:
        return None
    # Una richiesta dimenticata li' da un avvio andato storto non deve
    # aprire schede a caso ore dopo.
    return link if eta <= ETA_MASSIMA_RICHIESTA and link else None


# --- cosa annunciare ---------------------------------------------------------


@dataclass
class Notifica:
    titolo: str
    testo: str = ""
    immagine: str = ""
    apri: str = ""
    # (etichetta, link); il link "chiudi" e' il pulsante che la fa sparire.
    pulsanti: list[tuple[str, str]] = field(default_factory=list)
    # gettone -> repo, da salvare prima di mostrarla.
    gettoni: dict[str, str] = field(default_factory=dict)


def cosa_cambia(note: str, limite: int = 90) -> str:
    """La prima cosa detta nelle note di rilascio, in una riga.

    I titoli si saltano (di solito ripetono il nome della release) e si
    preferisce il primo punto elenco, che e' quasi sempre la novita' vera.
    """
    righe = [r.strip() for r in str(note or "").splitlines() if r.strip()]
    utili = [r for r in righe if not r.startswith("#") and not r.startswith("<")]
    punto = next((r for r in utili if re.match(r"^[-*+]\s+", r)), None)
    riga = punto or (utili[0] if utili else "")
    riga = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", riga)
    riga = re.sub(r"\*\*|__|`|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", riga)
    riga = riga.rstrip(":").strip()
    if len(riga) > limite:
        riga = riga[: limite - 1].rstrip(" ,.;:") + "…"
    return riga


def _elenco(nomi: list[str]) -> str:
    if len(nomi) <= 1:
        return "".join(nomi)
    return ", ".join(nomi[:-1]) + " e " + nomi[-1]


def da_notificare(
    progetti: list[dict],
    hub_update: dict | None,
    inviate: dict,
    copertina: Callable[[str], Path | None] = lambda repo: None,
    nuovo_gettone: Callable[[], str] = lambda: secrets.token_urlsafe(9),
) -> tuple[list[Notifica], dict]:
    """Le notifiche da mostrare adesso, e il registro aggiornato di cosa e' stato detto.

    `inviate` dice, per ogni repo, l'ultima versione gia' annunciata: e' cio'
    che impedisce di ripetere la stessa notifica a ogni controllo.
    """
    inviate = dict(inviate or {})
    notifiche: list[Notifica] = []

    def ultima(p: dict) -> str:
        return (p.get("latest") or {}).get("tag") or ""

    def immagine(p: dict) -> str:
        percorso = copertina(p.get("repo", ""))
        return str(percorso) if percorso and Path(percorso).exists() else ""

    da_aggiornare = [
        p for p in progetti
        if p.get("status") == "aggiornamento" and ultima(p) and inviate.get(p.get("repo")) != ultima(p)
    ]
    nuove = [
        p for p in progetti
        if p.get("novita") == "nuova" and p.get("status") != "aggiornamento"
        and ultima(p) and inviate.get(p.get("repo")) is None
    ]

    if len(da_aggiornare) == 1:
        p = da_aggiornare[0]
        gettone = nuovo_gettone()
        testo = f"Versione {ultima(p)}"
        novita = cosa_cambia((p.get("latest") or {}).get("body", ""))
        if novita:
            testo += f" · {novita}"
        notifiche.append(
            Notifica(
                titolo=f"{p.get('title', '')}: nuova versione della traduzione",
                testo=testo,
                immagine=immagine(p),
                apri=link_mostra(p["repo"]),
                pulsanti=[("Aggiorna", link_aggiorna(p["repo"], gettone)), ("Più tardi", "chiudi")],
                gettoni={gettone: p["repo"]},
            )
        )
    elif da_aggiornare:
        nomi = [p.get("title", "") for p in da_aggiornare]
        notifiche.append(
            Notifica(
                titolo=f"{len(nomi)} traduzioni da aggiornare",
                testo=_elenco(nomi[:4]) + (f" e altre {len(nomi) - 4}" if len(nomi) > 4 else ""),
                apri=link_apri(),
                pulsanti=[("Apri Gioca in Italiano", link_apri()), ("Più tardi", "chiudi")],
            )
        )
    for p in da_aggiornare:
        inviate[p["repo"]] = ultima(p)

    for p in nuove[:2] if len(nuove) <= 2 else []:
        notifiche.append(
            Notifica(
                titolo=f"Nuova traduzione: {p.get('title', '')}",
                testo=f"È arrivata la traduzione italiana di {p.get('title', '')}. Si installa con un clic.",
                immagine=immagine(p),
                apri=link_mostra(p["repo"]),
                pulsanti=[("Vedi", link_mostra(p["repo"])), ("Più tardi", "chiudi")],
            )
        )
    if len(nuove) > 2:
        notifiche.append(
            Notifica(
                titolo=f"{len(nuove)} traduzioni nuove",
                testo=_elenco([p.get("title", "") for p in nuove[:4]]),
                apri=link_apri(),
                pulsanti=[("Apri Gioca in Italiano", link_apri())],
            )
        )
    for p in nuove:
        inviate[p["repo"]] = ultima(p)

    versione = (hub_update or {}).get("version") if (hub_update or {}).get("available") else None
    if versione and inviate.get(CHIAVE_HUB) != versione:
        notifiche.append(
            Notifica(
                titolo=f"{APP_TITLE} {versione} è pronta",
                testo="È uscita una nuova versione dell'app: la scarichi dalle impostazioni, in un attimo.",
                apri=link_apri(),
                pulsanti=[("Apri", link_apri())],
            )
        )
        inviate[CHIAVE_HUB] = versione

    return notifiche[:MAX_PER_CONTROLLO], inviate


# --- come si mostra ----------------------------------------------------------


def _xml_testo(testo: str) -> str:
    return (
        str(testo)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def xml(n: Notifica) -> str:
    """Il contenuto della notifica nel formato di Windows (ToastGeneric)."""
    e = _xml_testo
    apertura = f'<toast launch="{e(n.apri)}" activationType="protocol">' if n.apri else "<toast>"
    corpo = [f"<text>{e(n.titolo)}</text>"]
    if n.testo:
        corpo.append(f"<text>{e(n.testo)}</text>")
    immagine = Path(n.immagine) if n.immagine else None
    if immagine and immagine.is_absolute():
        # La copertina in grande, in cima: e' quella che fa capire di che gioco
        # si parla prima ancora di leggere. Windows la vuole come file:///, e
        # un percorso relativo non si puo' scrivere cosi': meglio senza.
        corpo.append(f'<image placement="hero" src="{e(immagine.as_uri())}"/>')
    azioni = []
    for etichetta, link in n.pulsanti:
        if link == "chiudi":
            azioni.append(f'<action content="{e(etichetta)}" activationType="system" arguments="dismiss"/>')
        else:
            azioni.append(f'<action content="{e(etichetta)}" activationType="protocol" arguments="{e(link)}"/>')
    return (
        apertura
        + '<visual><binding template="ToastGeneric">'
        + "".join(corpo)
        + "</binding></visual>"
        + (f"<actions>{''.join(azioni)}</actions>" if azioni else "")
        + "</toast>"
    )


# Il contenuto arriva da variabili d'ambiente, non incollato nello script: un
# titolo con un apice o un dollaro non puo' cosi' rompere niente.
_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:GII_TOAST_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:GII_TOAST_APP).Show($toast)
"""


def _invia(n: Notifica) -> None:
    ambiente = dict(
        os.environ,
        GII_TOAST_XML=xml(n),
        GII_TOAST_APP=AUMID if _registrata else AUMID_POWERSHELL,
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _SCRIPT],
            env=ambiente,
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass


def mostra(n: Notifica) -> None:
    """Mostra una notifica senza bloccare l'hub."""
    threading.Thread(target=_invia, args=(n,), daemon=True).start()


def prova(progetti: list[dict], copertina: Callable[[str], Path | None] = lambda repo: None) -> Notifica:
    """La notifica del pulsante "Prova" nelle impostazioni."""
    immagine = ""
    for p in sorted(progetti, key=lambda p: 0 if p.get("installed_tag") else 1):
        percorso = copertina(p.get("repo", ""))
        if percorso and Path(percorso).exists():
            immagine = str(percorso)
            break
    return Notifica(
        titolo="Le notifiche funzionano",
        testo="Così ti avviso quando esce una nuova versione di una traduzione.",
        immagine=immagine,
        apri=link_apri(),
    )
