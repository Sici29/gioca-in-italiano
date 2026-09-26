"""Genera il sito di Gioca in Italiano: una pagina per ogni traduzione.

Il sito sta su GitHub Pages e serve a una cosa sola: farsi trovare. Chi cerca
"Aniimo traduzione italiana" su Google deve arrivare su una pagina che dice
subito cosa scaricare, come si installa e come si torna indietro.

Pagine statiche e senza JavaScript: si aprono al volo anche dal telefono,
Google le legge per intero e non c'e' niente da tenere in piedi. I dati sono
quelli del catalogo dell'hub (tools/build_catalog.py) e le copertine passano
dalla stessa pipeline dell'hub, quindi una traduzione nuova o una release
nuova finiscono sul sito al giro successivo della Action, senza toccare niente.

Quello che il catalogo non sa (la lingua da scegliere nel gioco, il tasto per
tornare all'originale) sta in sito/giochi.json, ed e' facoltativo: una
traduzione che li' non compare ha comunque la sua pagina, con istruzioni
generiche.

    python tools/genera_sito.py                          # interroga GitHub
    python tools/genera_sito.py --catalogo catalog.json  # usa un catalogo gia' fatto
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from hub import config  # noqa: E402  (config non tocca il disco)

SORGENTI = RADICE / "sito"
SITO = config.SITO_URL
NOME = "Gioca in Italiano"

MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

# Quante versioni precedenti elencare, e quanti blocchi di note mostrare prima
# del rimando a GitHub: le note di certe release sono lunghe pagine intere.
MAX_VERSIONI = 6
MAX_BLOCCHI_NOTE = 10

# Sotto questa soglia il numero di download non si mostra: "scaricata 2 volte"
# allontana piu' di quanto rassicuri.
MIN_DOWNLOAD_DA_MOSTRARE = 50


# --- formattazione -----------------------------------------------------------


def e(testo) -> str:
    return html.escape(str(testo or ""), quote=True)


def slug(testo: str) -> str:
    """"ARK: Survival Ascended" -> "ark-survival-ascended"."""
    base = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return base or "gioco"


def quando(iso) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def data_it(iso) -> str:
    d = quando(iso)
    return f"{d.day} {MESI[d.month - 1]} {d.year}" if d else ""


def numero(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def peso(byte) -> str:
    mb = (byte or 0) / 1_000_000
    if mb >= 10:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB".replace(".", ",")


def arrotonda_download(n: int) -> str:
    """1.060 -> "oltre 1.000": il conto copre solo le release recenti."""
    if n >= 1000:
        return f"oltre {numero(n // 100 * 100)}"
    if n >= 100:
        return f"oltre {numero(n // 50 * 50)}"
    return numero(n)


def json_ld(dati: dict) -> str:
    # Un "</script>" dentro un titolo chiuderebbe il tag in anticipo: < > e &
    # diventano sequenze \u di JSON, che per chi legge i dati sono identiche.
    testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    for carattere, sequenza in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        testo = testo.replace(carattere, sequenza)
    return f'<script type="application/ld+json">{testo}</script>'


# --- Markdown delle note di rilascio -----------------------------------------
#
# Serve un sottoinsieme piccolo: titoli, elenchi anche annidati, grassetti,
# corsivi, codice e link. Tutto il resto (tabelle, blocchi di codice, HTML,
# immagini) nelle note e' materiale tecnico e sul sito si salta. Il testo
# viene sempre fatto passare da html.escape: nessun tag arriva alla pagina.

_CODICE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_IMMAGINE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_GRASSETTO = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_CORSIVO = re.compile(r"(?<![\w*])\*(?=\S)([^*]+?)(?<=\S)\*(?![\w*])")
_SOLO_TAG = re.compile(r"^\s*</?[a-zA-Z][^>]*>\s*$")
_TITOLO = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_VOCE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_RIGA_ORIZZONTALE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def in_linea(testo: str) -> str:
    # Il codice si mette da parte per primo: un asterisco dentro un nome di
    # file non deve diventare un corsivo.
    pezzi: list[str] = []

    def metti_da_parte(m: re.Match) -> str:
        pezzi.append(f"<code>{e(m.group(1))}</code>")
        return f"\x00{len(pezzi) - 1}\x00"

    testo = _IMMAGINE.sub("", testo)
    testo = _CODICE.sub(metti_da_parte, testo)
    testo = e(testo)
    testo = _LINK.sub(r'<a href="\2" rel="nofollow">\1</a>', testo)
    testo = _GRASSETTO.sub(r"<strong>\1</strong>", testo)
    testo = _CORSIVO.sub(r"<em>\1</em>", testo)
    return re.sub(r"\x00(\d+)\x00", lambda m: pezzi[int(m.group(1))], testo)


def markdown(testo: str, max_blocchi: int | None = None) -> tuple[str, bool]:
    """HTML sicuro da un Markdown semplice, e se e' stato accorciato."""
    out: list[str] = []
    aperte: list[str] = []  # tipo ("ul"/"ol") di ogni elenco aperto
    rientri: list[int] = []  # rientro di ogni livello di elenco
    paragrafo: list[str] = []
    blocchi = 0
    tagliato = False
    in_codice = False
    primo = True

    def chiudi_paragrafo() -> None:
        if paragrafo:
            out.append(f"<p>{in_linea(' '.join(paragrafo))}</p>")
            paragrafo.clear()

    def chiudi_elenchi() -> None:
        while aperte:
            out.append(f"</li></{aperte.pop()}>")
        rientri.clear()

    for riga in (testo or "").replace("\r\n", "\n").split("\n"):
        if riga.strip().startswith("```"):
            in_codice = not in_codice
            continue
        if in_codice or _SOLO_TAG.match(riga) or riga.lstrip().startswith("|"):
            continue
        if _RIGA_ORIZZONTALE.match(riga):
            chiudi_paragrafo()
            continue
        if not riga.strip():
            chiudi_paragrafo()
            continue

        if max_blocchi is not None and blocchi >= max_blocchi:
            tagliato = True
            break

        titolo = _TITOLO.match(riga)
        voce = _VOCE.match(riga)
        if titolo:
            chiudi_paragrafo()
            chiudi_elenchi()
            # Il primo titolo delle note ripete quasi sempre il nome della
            # release, che la pagina mostra gia'.
            if not primo:
                out.append(f"<h4>{in_linea(titolo.group(2))}</h4>")
                blocchi += 1
        elif voce:
            chiudi_paragrafo()
            rientro = len(voce.group(1).replace("\t", "    "))
            while rientri and rientro < rientri[-1]:
                rientri.pop()
            if not rientri or rientro > rientri[-1]:
                rientri.append(rientro)
            livello = len(rientri) - 1
            tipo = "ol" if voce.group(2)[0].isdigit() else "ul"
            while len(aperte) > livello + 1:
                out.append(f"</li></{aperte.pop()}>")
            if len(aperte) == livello + 1:
                if aperte[-1] != tipo:
                    out.append(f"</li></{aperte.pop()}>")
                    out.append(f"<{tipo}>")
                    aperte.append(tipo)
                else:
                    out.append("</li>")
            while len(aperte) < livello + 1:
                out.append(f"<{tipo}>")
                aperte.append(tipo)
            out.append(f"<li>{in_linea(voce.group(3))}")
            blocchi += 1
        elif aperte and riga.startswith((" ", "\t")):
            # Seguito di una voce andata a capo.
            out.append(" " + in_linea(riga.strip()))
        else:
            chiudi_elenchi()
            if not paragrafo:
                blocchi += 1
            paragrafo.append(riga.strip())
        primo = False

    chiudi_paragrafo()
    chiudi_elenchi()
    return "".join(out), tagliato


# --- dati --------------------------------------------------------------------


def carica_extra() -> dict:
    try:
        dati = json.loads((SORGENTI / "giochi.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in dati.items() if not k.startswith("_") and isinstance(v, dict)}


def giochi_dal_catalogo(dati: dict, extra: dict) -> list[dict]:
    from hub import catalog

    giochi = []
    for voce in dati.get("entries") or []:
        repo = voce.get("repo") or {}
        nome = repo.get("name") or ""
        marker = voce.get("marker") or {}
        rilasci = [r for r in voce.get("releases") or [] if not r.get("prerelease")]
        if not nome or not rilasci:
            # Senza una release non c'e' niente da scaricare: meglio nessuna
            # pagina che una pagina con un pulsante che non porta da nessuna parte.
            print(f"  {nome or '?'}: nessuna release pubblicata, niente pagina")
            continue

        titolo = marker.get("nome_gioco") or config.pretty_game_name(nome)
        ultima = rilasci[0]
        file = ultima.get("download") or catalog._pick_asset(ultima.get("assets") or [])
        if not file or not file.get("url"):
            print(f"  {nome}: l'ultima release non ha file da scaricare, niente pagina")
            continue

        # "steam_appid": null scritto apposta nel hub.json vuol dire "su Steam
        # non c'e'": allora non si cerca nemmeno, come fa l'hub.
        fuori_da_steam = bool(marker.get("non_su_steam")) or (
            "steam_appid" in marker and marker.get("steam_appid") is None
        )
        giochi.append(
            {
                "repo": nome,
                "titolo": titolo,
                "slug": slug(titolo),
                "descrizione": repo.get("description") or "",
                "url_repo": repo.get("html_url") or f"{config.PROFILE_URL}/{nome}",
                "appid": None if fuori_da_steam else marker.get("steam_appid"),
                "cerca_su_steam": not fuori_da_steam,
                "cover_url": marker.get("cover_url"),
                "versione_gioco": marker.get("game_version"),
                "rilasci": rilasci,
                "ultima": ultima,
                "file": file,
                "scaricati": sum(
                    int(a.get("downloads") or 0)
                    for r in voce.get("releases") or []
                    for a in r.get("assets") or []
                ),
                "extra": extra.get(nome, {}),
                "immagine": "",
                "tinta": "#ffb020",
                "sviluppatore": "",
                "generi": [],
                "store": "",
            }
        )

    giochi.sort(key=lambda g: g["ultima"].get("date") or "", reverse=True)

    # Due giochi con lo stesso nome darebbero la stessa cartella.
    visti: dict[str, int] = {}
    for g in giochi:
        n = visti.get(g["slug"], 0)
        visti[g["slug"]] = n + 1
        if n:
            g["slug"] = f"{g['slug']}-{n + 1}"
    return giochi


def arricchisci(giochi: list[dict], cartella_img: Path) -> None:
    """Copertine, tinta e dati dello store: la stessa strada dell'hub."""
    from hub import covers, steam

    for g in giochi:
        percorso, info = covers.ensure_cover(
            g["repo"],
            g["titolo"],
            appid=g["appid"],
            cover_url=g["cover_url"],
            allow_search=g["cerca_su_steam"],
        )
        if percorso and Path(percorso).exists():
            shutil.copyfile(percorso, cartella_img / f"{g['slug']}.jpg")
            g["immagine"] = f"img/{g['slug']}.jpg"
            g["tinta"] = covers.tinta(Path(percorso))
        if not g["appid"] and info.get("appid"):
            g["appid"] = info["appid"]

        extra = g["extra"]
        if g["appid"]:
            scheda = steam.app_details(int(g["appid"])) or {}
            g["sviluppatore"] = ", ".join(scheda.get("developers") or [])
            g["generi"] = [
                x["description"] for x in scheda.get("genres") or [] if x.get("description")
            ][:3]
            g["store"] = f"https://store.steampowered.com/app/{g['appid']}/"
        g["sviluppatore"] = g["sviluppatore"] or extra.get("sviluppatore", "")
        g["store"] = g["store"] or extra.get("sito_gioco", "")
        print(f"  {g['titolo']}: copertina {'ok' if g['immagine'] else 'mancante'}, tinta {g['tinta']}")


def hub_da_scaricare(dati: dict) -> dict | None:
    """L'exe dell'hub, se e' stato pubblicato: senza, il sito non lo nomina."""
    rel = dati.get("hub_release") or {}
    for a in rel.get("assets") or []:
        if str(a.get("name", "")).lower().endswith(".exe") and a.get("browser_download_url"):
            return {
                "versione": rel.get("tag_name") or "",
                "url": a["browser_download_url"],
                "peso": a.get("size") or 0,
                "pagina": rel.get("html_url") or "",
            }
    return None


def senza_prefisso(titolo) -> str:
    """"[Proposta] Dune: Awakening" -> "Dune: Awakening"."""
    return re.sub(r"^\s*\[proposta\]\s*", "", str(titolo or ""), flags=re.I)


def url_proposta() -> str:
    """Il modulo di GitHub gia' compilato, senza i dati del PC che aggiunge l'hub."""
    base = f"https://github.com/{config.GITHUB_USER}/{config.SUGGESTIONS_REPO}/issues/new"
    corpo = (
        "**Gioco**\n\n\n"
        "**Dove si trova** (Steam, Epic, GOG, altro)\n\n\n"
        "**Perché servirebbe** (quanto è diffuso, se esiste già una traduzione)\n\n\n"
        "**Link alla pagina del gioco**\n\n"
    )
    return f"{base}?title={quote(config.PROPOSAL_PREFIX + ' ')}&body={quote(corpo)}"


# --- pezzi di pagina ---------------------------------------------------------

ICONA_SCARICA = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0-5-5m5 5 5-5'
    'M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
ICONA_FRECCIA = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)
ICONA_GITHUB = (
    '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 '
    "0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49"
    "-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 "
    "2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08"
    "-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 "
    "1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 "
    '1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>'
)


def testata(radice: str) -> str:
    return f"""<header class="testata">
  <div class="contenitore testata-riga">
    <a class="marchio" href="{radice or './'}">
      <img src="{radice}favicon.svg" alt="" width="30" height="30">
      <span>{NOME}</span>
    </a>
    <nav class="menu" aria-label="Sezioni">
      <a href="{radice}#giochi">Giochi</a>
      <a href="{radice}#proponi">Proponi un gioco</a>
      <a class="menu-caffe" href="{e(config.BMC_URL)}">Offrimi un caffè</a>
    </nav>
  </div>
</header>"""


def piede() -> str:
    # Niente "pagina generata il...": la data di generazione cambierebbe il
    # sito a ogni giro della Action anche quando non c'e' niente di nuovo, e
    # si ripubblicherebbe tutto per niente. Le date che contano, quelle delle
    # release, sono gia' nelle pagine.
    return f"""<footer class="piede">
  <div class="contenitore">
    <p><strong>{NOME}</strong> raccoglie le traduzioni amatoriali di
      <a href="{e(config.PROFILE_URL)}">Sici29</a>. Non sono traduzioni ufficiali e non sono affiliate
      agli sviluppatori o agli editori dei giochi; nomi, marchi e immagini appartengono ai rispettivi
      proprietari. Per usarle serve una copia del gioco.</p>
    <p class="piede-link">
      <a href="{e(config.PROFILE_URL)}">{ICONA_GITHUB} GitHub</a>
      <a href="{e(config.BMC_URL)}">Offrimi un caffè</a>
    </p>
  </div>
</footer>"""


def pagina(
    *,
    titolo: str,
    descrizione: str,
    percorso: str,
    radice: str,
    corpo: str,
    immagine: str = "",
    tinta: str = "",
    strutturati: list[dict] | None = None,
    versione_css: str = "",
    indicizza: bool = True,
) -> str:
    url = SITO + percorso
    anteprima = SITO + (immagine or "img/condivisione.jpg")
    stile = f' style="--tinta:{e(tinta)}"' if tinta else ""
    robot = "" if indicizza else '\n<meta name="robots" content="noindex">'
    ld = "\n".join(json_ld(d) for d in strutturati or [])
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titolo)}</title>
<meta name="description" content="{e(descrizione)}">{robot}
<link rel="canonical" href="{e(url)}">
<meta name="theme-color" content="#0b1015">
<meta property="og:type" content="website">
<meta property="og:locale" content="it_IT">
<meta property="og:site_name" content="{NOME}">
<meta property="og:title" content="{e(titolo)}">
<meta property="og:description" content="{e(descrizione)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(anteprima)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{radice}favicon.svg" type="image/svg+xml">
<link rel="icon" href="{radice}favicon.png" type="image/png" sizes="96x96">
<link rel="apple-touch-icon" href="{radice}apple-touch-icon.png">
<link rel="stylesheet" href="{radice}stile.css?v={versione_css}">
{ld}
</head>
<body{stile}>
{testata(radice)}
<main>
{corpo}
</main>
{piede()}
</body>
</html>
"""


def scheda_gioco(g: dict, radice: str, piccola: bool = False) -> str:
    ultima, file = g["ultima"], g["file"]
    testo = g["extra"].get("cosa") or g["descrizione"]
    img = (
        f'<img src="{radice}{e(g["immagine"])}" alt="Copertina di {e(g["titolo"])}" '
        f'width="460" height="215" loading="lazy">'
        if g["immagine"]
        else f'<div class="scheda-vuota">{e(g["titolo"])}</div>'
    )
    azioni = (
        ""
        if piccola
        else f"""
  <div class="scheda-azioni">
    <a class="bottone" href="{e(file['url'])}">{ICONA_SCARICA} Scarica <span class="tenue">· {peso(file.get('size'))}</span></a>
    <a class="link-freccia" href="{radice}{g['slug']}/">Come si installa {ICONA_FRECCIA}</a>
  </div>"""
    )
    descr = "" if piccola else f"\n      <p>{e(testo)}</p>"
    return f"""<article class="scheda{' scheda-piccola' if piccola else ''}" style="--tinta:{e(g['tinta'])}">
  <a class="scheda-link" href="{radice}{g['slug']}/">
    <div class="scheda-img">{img}</div>
    <div class="scheda-testo">
      <h3>{e(g['titolo'])} in italiano</h3>{descr}
      <p class="scheda-meta">Versione {e(ultima.get('tag'))} · {e(data_it(ultima.get('date')))}</p>
    </div>
  </a>{azioni}
</article>"""


# --- pagine ------------------------------------------------------------------


def pagina_indice(giochi, hub, proposte, versione_css) -> str:
    totale = sum(g["scaricati"] for g in giochi)
    ultimo = max((g["ultima"].get("date") or "" for g in giochi), default="")
    nomi = [g["titolo"] for g in giochi]
    elenco_nomi = ", ".join(nomi[:-1]) + (f" e {nomi[-1]}" if len(nomi) > 1 else "".join(nomi))

    if hub:
        principale = f"""<a class="bottone grande" href="{e(hub['url'])}">{ICONA_SCARICA} Scarica {NOME}</a>
        <a class="bottone grande secondario" href="#giochi">Scegli il gioco</a>"""
        nota_hub = f'<p class="nota-sotto">Per Windows · {peso(hub["peso"])} · gratis, senza pubblicità</p>'
    else:
        principale = f'<a class="bottone grande" href="#giochi">Scegli il gioco {ICONA_FRECCIA}</a>'
        nota_hub = ""

    numeri = [f"<li><strong>{len(giochi)}</strong> giochi tradotti</li>"]
    if totale >= MIN_DOWNLOAD_DA_MOSTRARE:
        numeri.append(f"<li><strong>{arrotonda_download(totale)}</strong> download</li>")
    if ultimo:
        numeri.append(f"<li>ultimo aggiornamento <strong>{e(data_it(ultimo))}</strong></li>")

    copertine = "".join(
        f'<img src="{e(g["immagine"])}" alt="" width="460" height="215">' for g in giochi if g["immagine"]
    )

    if hub:
        passi = (
            ("Scarica l'app", f"{NOME} è un solo file: si apre e mostra tutte le traduzioni."),
            ("Premi Installa", "Trova il gioco sul tuo PC, fa un backup e installa, senza finestre da capire."),
            ("Gioca", "Quando esce un aggiornamento te lo dice lei. E con un clic torni all'originale."),
        )
    else:
        passi = (
            ("Scarica il file", "Ogni traduzione è un solo file: si apre con un doppio clic."),
            ("Chiudi il gioco e avvialo", "L'installer trova il gioco da solo e fa un backup prima di toccare qualcosa."),
            ("Gioca in italiano", "Per tornare all'originale basta riaprire l'installer."),
        )
    passi_html = "".join(
        f'<li><span class="passo-n">{i}</span><h3>{e(t)}</h3><p>{e(d)}</p></li>'
        for i, (t, d) in enumerate(passi, 1)
    )

    sezione_hub = ""
    if hub:
        sezione_hub = f"""
<section class="sezione app" id="app">
  <div class="contenitore app-riga">
    <div>
      <p class="occhiello">L'app</p>
      <h2>Tutte le traduzioni in un posto solo</h2>
      <ul class="spunte">
        <li>Riconosce i giochi che hai installato e ti mostra prima i tuoi</li>
        <li>Installa e aggiorna senza aprire finestre nere</li>
        <li>Ti avvisa quando esce una versione nuova</li>
        <li>Fa partire il gioco con un clic</li>
      </ul>
      <a class="bottone grande" href="{e(hub['url'])}">{ICONA_SCARICA} Scarica {NOME} <span class="tenue">· {e(hub['versione'])}</span></a>
      <p class="nota-sotto">Windows 10 e 11 · {peso(hub['peso'])} · il codice è pubblico su GitHub</p>
    </div>
  </div>
</section>"""

    righe_proposte = ""
    migliori = sorted(proposte or [], key=lambda p: -(p.get("votes") or 0))[:5]
    if migliori:
        voci = "".join(
            f"""<li><a href="{e(p.get('url'))}"><span>{e(senza_prefisso(p.get('title')))}</span>
            <span class="voti">{numero(p.get('votes') or 0)} voti</span></a></li>"""
            for p in migliori
        )
        righe_proposte = f'<ol class="proposte">{voci}</ol>'
    else:
        righe_proposte = (
            '<div class="proposte-vuote"><p><strong>Nessuna proposta, per ora.</strong><br>'
            "La prima può essere la tua: basta il nome del gioco.</p></div>"
        )
    dove_si_vota = ", o direttamente dall'app" if hub else ""

    corpo = f"""<section class="eroe">
  <div class="eroe-copertine" aria-hidden="true"><div class="eroe-copertine-piano">{copertine}{copertine}</div></div>
  <div class="contenitore eroe-testo">
    <p class="occhiello">Traduzioni amatoriali di Sici29</p>
    <h1>I tuoi giochi, <span class="evidenzia">in italiano</span>.</h1>
    <p class="attacco">Traduzioni complete e gratuite di {e(elenco_nomi)}. Ognuna si installa
      da sola, fa un backup del gioco e si toglie quando vuoi.</p>
    <div class="azioni">{principale}</div>
    {nota_hub}
    <ul class="numeri">{''.join(numeri)}</ul>
  </div>
</section>

<section class="sezione" id="giochi">
  <div class="contenitore">
    <h2>Scegli il gioco</h2>
    <div class="griglia">
{''.join(scheda_gioco(g, '') for g in giochi)}
    </div>
  </div>
</section>

<section class="sezione come">
  <div class="contenitore">
    <h2>Come funziona</h2>
    <ol class="passi">{passi_html}</ol>
  </div>
</section>
{sezione_hub}
<section class="sezione" id="proponi">
  <div class="contenitore proponi">
    <div>
      <h2>Quale gioco vorresti in italiano?</h2>
      <p>Proponilo: le proposte più votate sono le prime candidate a diventare la prossima traduzione.
        Si vota con un 👍 su GitHub{dove_si_vota}.</p>
      <a class="bottone" href="{e(url_proposta())}">Proponi un gioco {ICONA_FRECCIA}</a>
    </div>
    {righe_proposte}
  </div>
</section>

<section class="sezione caffe">
  <div class="contenitore caffe-riga">
    <p>Le traduzioni sono gratuite e restano gratuite. Se ti hanno fatto comodo e vuoi aiutarmi a tenerle
      aggiornate, puoi offrirmi un caffè.</p>
    <a class="bottone bottone-caffe" href="{e(config.BMC_URL)}">☕ Offrimi un caffè</a>
  </div>
</section>"""

    strutturati = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": NOME,
            "url": SITO,
            "inLanguage": "it",
            "description": "Traduzioni italiane amatoriali e gratuite di videogiochi.",
        },
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i, "url": f"{SITO}{g['slug']}/", "name": f"{g['titolo']} in italiano"}
                for i, g in enumerate(giochi, 1)
            ],
        },
    ]
    return pagina(
        titolo=f"{NOME} – Traduzioni italiane gratuite di videogiochi",
        descrizione=(
            f"Traduzioni italiane complete e gratuite di {elenco_nomi}. "
            "Si installano da sole, con backup e ripristino."
        ),
        percorso="",
        radice="",
        corpo=corpo,
        strutturati=strutturati,
        versione_css=versione_css,
    )


def pagina_gioco(g, altri, hub, versione_css) -> str:
    ultima, file, extra = g["ultima"], g["file"], g["extra"]
    titolo = g["titolo"]
    tag = ultima.get("tag") or ""
    data = data_it(ultima.get("date"))
    lingua = extra.get("lingua")
    chiudi = extra.get("chiudi") or titolo

    # --- installazione
    passi = [
        f"Scarica <strong>{e(file['name'])}</strong> ({peso(file.get('size'))}) con il pulsante qui sopra.",
        f"Chiudi {e(chiudi)}.",
        e(extra.get("avvio") or "Fai doppio clic sul file e segui le istruzioni: l'installer trova il gioco e fa un backup."),
    ]
    if lingua:
        passi.append(f"Avvia il gioco e scegli <strong>{e(lingua)}</strong> come lingua.")
    else:
        passi.append("Avvia il gioco: i testi sono in italiano.")
    passi_html = "".join(f"<li>{p}</li>" for p in passi)
    extra_passi = ""
    if extra.get("nota_lingua"):
        extra_passi += f'<p class="nota">{e(extra["nota_lingua"])}</p>'
    if extra.get("non_trova"):
        extra_passi += f'<p class="nota"><strong>Se l\'installer non trova il gioco.</strong> {e(extra["non_trova"])}</p>'
    if hub:
        extra_passi += (
            f'<p class="nota nota-app">Con <a href="../#app">{NOME}</a> è ancora più semplice: '
            f"premi Installa sulla scheda di {e(titolo)} e fa tutto lei, anche gli aggiornamenti.</p>"
        )

    # --- note della release
    note_html, tagliato = markdown(ultima.get("body") or "", MAX_BLOCCHI_NOTE)
    if not note_html:
        note_html = "<p>Le note di questa versione sono su GitHub.</p>"
        tagliato = True
    continua = (
        f'<p><a class="link-freccia" href="{e(ultima.get("url"))}">Leggi tutte le note su GitHub {ICONA_FRECCIA}</a></p>'
        if tagliato and ultima.get("url")
        else ""
    )

    # --- ripristino e domande
    ripristino = extra.get("ripristino") or (
        "Chiudi il gioco, riapri l'installer e scegli l'opzione per ripristinare i file originali."
    )
    avvertenza = extra.get("avvertenza") or (
        "È una modifica non ufficiale dei file del gioco: usala sapendo che gli sviluppatori non la supportano."
    )
    chi = g["sviluppatore"] or "gli sviluppatori del gioco"
    domande = [
        ("È gratis?", "Sì, e resta gratis. Se ti è utile puoi offrirmi un caffè, ma non è mai obbligatorio."),
        ("È una traduzione ufficiale?", f"No: è amatoriale, fatta da Sici29, e non è affiliata a {chi}. {avvertenza}"),
        (
            "Windows dice che il file potrebbe essere pericoloso",
            "È l'avviso che Windows mostra per i programmi gratuiti senza una firma digitale a pagamento. "
            "Premi «Ulteriori informazioni» e poi «Esegui comunque». Scarica il file solo da questa pagina "
            "o dalla pagina GitHub della traduzione.",
        ),
        (
            "E quando il gioco si aggiorna?",
            "Se l'aggiornamento cambia i testi, esce una versione nuova della traduzione: la trovi qui, "
            "e l'installer ti avvisa quando lo riapri."
            + (f" {NOME} lo segnala da solo." if hub else ""),
        ),
    ]
    domande_html = "".join(f"<h3>{e(d)}</h3><p>{e(r)}</p>" for d, r in domande)

    # --- versioni
    righe_versioni = []
    for r in g["rilasci"][:MAX_VERSIONI]:
        allegato = r.get("download") or {}
        dimensione = peso(allegato["size"]) if allegato.get("size") else ""
        righe_versioni.append(
            f'<tr><td><a href="{e(r.get("url"))}">{e(r.get("tag"))}</a></td>'
            f'<td>{e(data_it(r.get("date")))}</td><td class="num">{dimensione}</td></tr>'
        )
    versioni = "".join(righe_versioni)

    # --- colonna dei dati
    dati = [("Versione", e(tag)), ("Pubblicata", e(data))]
    if g["versione_gioco"]:
        dati.append(("Per la versione del gioco", e(g["versione_gioco"])))
    dati.append(("Lingua da scegliere nel gioco", e(lingua) if lingua else "nessuna, fa tutto l'installer"))
    if g["scaricati"] >= MIN_DOWNLOAD_DA_MOSTRARE:
        dati.append(("Download", arrotonda_download(g["scaricati"])))
    if g["sviluppatore"]:
        dati.append(("Sviluppatore del gioco", e(g["sviluppatore"])))
    if g["generi"]:
        dati.append(("Genere", e(", ".join(g["generi"]))))
    dati_html = "".join(f"<div><dt>{t}</dt><dd>{v}</dd></div>" for t, v in dati)
    store = ""
    if g["store"]:
        dove = "su Steam" if "steampowered" in g["store"] else "sul sito ufficiale"
        store = f'<li><a href="{e(g["store"])}">{e(titolo)} {dove}</a></li>'

    img = (
        f'<img class="eroe-copertina" src="../{e(g["immagine"])}" alt="Copertina di {e(titolo)}" width="460" height="215">'
        if g["immagine"]
        else ""
    )
    sfondo = (
        f'<div class="eroe-sfondo" style="background-image:url(\'../{e(g["immagine"])}\')"></div>'
        if g["immagine"]
        else ""
    )
    attacco = extra.get("cosa") or g["descrizione"] or f"La traduzione italiana di {titolo}."

    corpo = f"""<section class="eroe-gioco">
  {sfondo}
  <div class="contenitore">
    <nav class="briciole" aria-label="Percorso"><a href="../">{NOME}</a><span aria-hidden="true">›</span><span>{e(titolo)}</span></nav>
    <div class="eroe-gioco-riga">
      {img}
      <div class="eroe-gioco-testo">
        <p class="occhiello">Traduzione italiana gratuita</p>
        <h1>{e(titolo)} in italiano</h1>
        <p class="attacco">{e(attacco)}</p>
        <div class="azioni">
          <a class="bottone grande" href="{e(file['url'])}">{ICONA_SCARICA} Scarica la traduzione</a>
        </div>
        <p class="nota-sotto">Versione {e(tag)} · {e(data)} · {peso(file.get('size'))} · Windows</p>
      </div>
    </div>
  </div>
</section>

<div class="contenitore colonne">
  <aside class="laterale">
    <dl class="dati">{dati_html}</dl>
    <ul class="link-laterali">
      {store}
      <li><a href="{e(g['url_repo'])}">{ICONA_GITHUB} La traduzione su GitHub</a></li>
      <li><a href="{e(g['url_repo'])}/issues">Segnala un errore</a></li>
    </ul>
    <a class="bottone bottone-caffe pieno" href="{e(config.BMC_URL)}">☕ Offrimi un caffè</a>
  </aside>

  <div class="principale">
    <section>
      <h2>Come si installa</h2>
      <ol class="elenco-passi">{passi_html}</ol>
      {extra_passi}
    </section>

    <section>
      <h2>Novità della versione {e(tag)}</h2>
      <div class="note-rilascio">{note_html}</div>
      {continua}
    </section>

    <section>
      <h2>Come tornare al gioco originale</h2>
      <p>{e(ripristino)}</p>
    </section>

    <section class="domande">
      <h2>Domande frequenti</h2>
      {domande_html}
    </section>

    <section>
      <h2>Versioni precedenti</h2>
      <table class="versioni">
        <thead><tr><th>Versione</th><th>Pubblicata</th><th class="num">File</th></tr></thead>
        <tbody>{versioni}</tbody>
      </table>
    </section>

    <section>
      <h2>Hai trovato un errore?</h2>
      <p>Una frase che non suona bene, un testo rimasto in inglese o tagliato: segnalalo su
        <a href="{e(g['url_repo'])}/issues">GitHub</a>, meglio se con uno screenshot e il punto del gioco in cui compare.</p>
    </section>
  </div>
</div>
""" + (
        f"""
<section class="sezione altri">
  <div class="contenitore">
    <h2>Altri giochi in italiano</h2>
    <div class="griglia griglia-piccola">
{''.join(scheda_gioco(a, '../', piccola=True) for a in altri)}
    </div>
  </div>
</section>"""
        if altri
        else ""
    )

    descrizione = (
        f"Traduzione italiana gratuita di {titolo}: scarica l'installer (versione {tag}, {data}), "
        f"si installa in un minuto e si toglie quando vuoi."
    )
    strutturati = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": NOME, "item": SITO},
                {"@type": "ListItem", "position": 2, "name": f"{titolo} in italiano", "item": f"{SITO}{g['slug']}/"},
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": f"Traduzione italiana di {titolo}",
            "applicationCategory": "UtilitiesApplication",
            "operatingSystem": "Windows",
            "inLanguage": "it",
            "softwareVersion": tag,
            "datePublished": (ultima.get("date") or "")[:10],
            "downloadUrl": file["url"],
            "fileSize": peso(file.get("size")),
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "author": {"@type": "Person", "name": config.GITHUB_USER, "url": config.PROFILE_URL},
        },
    ]
    return pagina(
        titolo=f"{titolo} in italiano – Traduzione italiana gratuita | {NOME}",
        descrizione=descrizione,
        percorso=f"{g['slug']}/",
        radice="../",
        corpo=corpo,
        immagine=g["immagine"],
        tinta=g["tinta"],
        strutturati=strutturati,
        versione_css=versione_css,
    )


def pagina_404(giochi, versione_css) -> str:
    # GitHub Pages la serve per qualunque indirizzo sbagliato, a qualunque
    # profondita': i link devono quindi essere assoluti.
    voci = "".join(f'<li><a href="{SITO}{g["slug"]}/">{e(g["titolo"])} in italiano</a></li>' for g in giochi)
    corpo = f"""<section class="sezione">
  <div class="contenitore stretto">
    <h1>Pagina non trovata</h1>
    <p>L'indirizzo non porta da nessuna parte, forse è cambiato. Le traduzioni sono tutte qui:</p>
    <ul class="elenco-semplice">{voci}</ul>
    <p><a class="bottone" href="{SITO}">Torna alla pagina principale</a></p>
  </div>
</section>"""
    return pagina(
        titolo=f"Pagina non trovata | {NOME}",
        descrizione="Questa pagina non esiste.",
        percorso="404.html",
        radice=SITO,
        corpo=corpo,
        versione_css=versione_css,
        indicizza=False,
    )


def mappa(giochi) -> str:
    """sitemap.xml: da dare a Google Search Console, che la legge da li'."""
    ultimo = max((g["ultima"].get("date") or "" for g in giochi), default="")[:10]
    voci = [(SITO, ultimo)] + [(f"{SITO}{g['slug']}/", (g["ultima"].get("date") or "")[:10]) for g in giochi]
    righe = "".join(
        f"<url><loc>{e(u)}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>\n" for u, d in voci
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{righe}</urlset>\n"
    )


# --- immagini del sito -------------------------------------------------------


def favicon_svg() -> str:
    # Lo stesso marchio di tools/make_icon.py, in vettoriale: tre righe che si
    # accorciano e il punto ambra.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1e2936"/><stop offset="1" stop-color="#0d131a"/>'
        "</linearGradient></defs>"
        '<rect width="64" height="64" rx="14" fill="url(#f)"/>'
        '<rect x="10.9" y="17.6" width="39.7" height="4.6" rx="2.3" fill="#dfe9f3"/>'
        '<rect x="10.9" y="29.7" width="25.6" height="4.6" rx="2.3" fill="#dfe9f3"/>'
        '<rect x="10.9" y="41.8" width="33.3" height="4.6" rx="2.3" fill="#dfe9f3"/>'
        '<circle cx="49.6" cy="32" r="6.4" fill="#ffb020"/></svg>\n'
    )


def _font(dimensione: int):
    from PIL import ImageFont

    for percorso in (
        r"C:\Windows\Fonts\bahnschrift.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(percorso, dimensione)
        except OSError:
            continue
    return None


def immagini_del_sito(giochi, uscita: Path) -> None:
    """Favicon e l'anteprima che compare quando qualcuno condivide il link."""
    from PIL import Image, ImageDraw, ImageFilter

    sys.path.insert(0, str(RADICE / "tools"))
    from make_icon import draw_icon

    (uscita / "favicon.svg").write_text(favicon_svg(), encoding="utf-8")
    draw_icon(96).save(uscita / "favicon.png")
    # iOS arrotonda gli angoli da solo e mette il nero dove c'e' trasparenza.
    tocco = Image.new("RGB", (180, 180), (13, 19, 26))
    icona = draw_icon(180)
    tocco.paste(icona, (0, 0), icona)
    tocco.save(uscita / "apple-touch-icon.png")

    # Anteprima 1200x630: le copertine in diagonale sullo sfondo, marchio e
    # nome davanti. E' quella che mostrano WhatsApp, Telegram e Discord.
    W, H = 1200, 630
    tela = Image.new("RGB", (W, H), (11, 16, 21))
    copertine = [Image.open(uscita / g["immagine"]).convert("RGB") for g in giochi if g["immagine"]]
    if copertine:
        piano = Image.new("RGB", (1700, 1000), (11, 16, 21))
        cw, ch = 460, 215
        for riga in range(5):
            for col in range(4):
                c = copertine[(riga * 4 + col + riga) % len(copertine)]
                x = col * (cw + 18) - (riga % 2) * 230
                piano.paste(c, (x, riga * (ch + 18)))
        piano = piano.rotate(-12, resample=Image.BICUBIC, expand=False, fillcolor=(11, 16, 21))
        piano = piano.crop((250, 180, 250 + W, 180 + H))
        tela.paste(piano, (0, 0))
        # Velo scuro a sinistra, dove sta il testo.
        velo = Image.new("L", (W, H))
        dv = ImageDraw.Draw(velo)
        for x in range(W):
            dv.line([(x, 0), (x, H)], fill=int(245 - 150 * min(1, x / (W * 0.95))))
        tela = Image.composite(Image.new("RGB", (W, H), (9, 13, 18)), tela, velo)
        tela = tela.filter(ImageFilter.SMOOTH)

    marchio = draw_icon(150)
    tela.paste(marchio, (84, 150), marchio)
    d = ImageDraw.Draw(tela)
    grande, medio = _font(88), _font(38)
    if grande and medio:
        d.text((84, 330), NOME, font=grande, fill=(231, 238, 246))
        d.text((88, 440), "Traduzioni italiane gratuite di videogiochi", font=medio, fill=(255, 176, 32))
    tela.save(uscita / "img" / "condivisione.jpg", "JPEG", quality=86, optimize=True, progressive=True)


# --- principale --------------------------------------------------------------


def genera(dati: dict, uscita: Path) -> list[dict]:
    extra = carica_extra()
    giochi = giochi_dal_catalogo(dati, extra)
    if not giochi:
        raise SystemExit("nessuna traduzione con una release: niente da pubblicare")

    if uscita.exists():
        shutil.rmtree(uscita)
    (uscita / "img").mkdir(parents=True)

    arricchisci(giochi, uscita / "img")
    immagini_del_sito(giochi, uscita)

    # File da mettere tali e quali nella radice del sito, per esempio quello
    # con cui Google Search Console verifica che il sito e' tuo. Vengono
    # copiati prima delle pagine, cosi' non possono sostituirne nessuna.
    if (SORGENTI / "radice").is_dir():
        shutil.copytree(SORGENTI / "radice", uscita, dirs_exist_ok=True)

    css = (SORGENTI / "stile.css").read_text(encoding="utf-8")
    (uscita / "stile.css").write_text(css, encoding="utf-8")
    versione_css = hashlib.sha1(css.encode("utf-8")).hexdigest()[:8]

    hub = hub_da_scaricare(dati)

    (uscita / "index.html").write_text(
        pagina_indice(giochi, hub, dati.get("proposals"), versione_css), encoding="utf-8"
    )
    for g in giochi:
        altri = [a for a in giochi if a is not g]
        cartella = uscita / g["slug"]
        cartella.mkdir()
        (cartella / "index.html").write_text(
            pagina_gioco(g, altri, hub, versione_css), encoding="utf-8"
        )
    (uscita / "404.html").write_text(pagina_404(giochi, versione_css), encoding="utf-8")
    (uscita / "sitemap.xml").write_text(mappa(giochi), encoding="utf-8")
    (uscita / IMPRONTA).write_text(impronta(uscita) + "\n", encoding="utf-8")
    return giochi


# La Action la confronta con quella del sito online e ripubblica solo se e'
# cambiato qualcosa: senza, ogni giro programmato sarebbe una pubblicazione.
IMPRONTA = "impronta.txt"


def impronta(cartella: Path) -> str:
    """Hash di tutto il sito, percorsi compresi, esclusa l'impronta stessa."""
    h = hashlib.sha256()
    for f in sorted(p for p in cartella.rglob("*") if p.is_file() and p.name != IMPRONTA):
        h.update(f.relative_to(cartella).as_posix().encode("utf-8") + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--catalogo", help="catalog.json gia' generato (se manca lo si costruisce)")
    ap.add_argument("--uscita", default="_sito", help="cartella in cui scrivere il sito")
    args = ap.parse_args(argv)

    # Le copertine passano dalla pipeline dell'hub, che le tiene sotto
    # %LOCALAPPDATA%. La si dirotta in una cartella sua, cosi' il generatore
    # non tocca la cache dell'hub installato sullo stesso PC, ne' le
    # copertine scelte a mano dall'utente.
    os.environ["LOCALAPPDATA"] = str(Path(tempfile.gettempdir()) / "gioca-in-italiano-sito")

    if args.catalogo:
        dati = json.loads(Path(args.catalogo).read_text(encoding="utf-8"))
    else:
        from build_catalog import build  # stesso generatore del catalogo dell'hub

        dati = build()

    uscita = Path(args.uscita)
    giochi = genera(dati, uscita)
    print(f"\nsito scritto in {uscita}: {len(giochi)} traduzioni")
    print(f"indirizzo pubblico: {SITO}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
