"""Mette in cima al README di ogni traduzione il riquadro di Gioca in Italiano.

Chi arriva sul repo di una traduzione e' gia' interessato: il riquadro gli dice
che c'e' un'app che la installa e la aggiorna da sola, che esistono le altre
traduzioni (con il link alle loro pagine) e che puo' proporre il prossimo gioco.

Il riquadro sta fra due commenti, inizio e fine: se c'e' gia' viene sostituito,
altrimenti si mette sotto il titolo e i badge. Cosi' lo strumento si rilancia
quando arriva una traduzione nuova, e tutti i README si aggiornano con
l'elenco giusto. Legge le traduzioni dal catalogo pubblicato, e scrive con la
CLI di GitHub (gh), che deve essere autenticata.

    python tools/readme_traduzioni.py            # dice solo cosa cambierebbe
    python tools/readme_traduzioni.py --scrivi   # fa i commit
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "tools"))

from hub import config  # noqa: E402
from genera_sito import BANNER, slug  # noqa: E402

INIZIO = "<!-- gioca-in-italiano:inizio -->"
FINE = "<!-- gioca-in-italiano:fine -->"

SITO = config.SITO_URL
SCARICA = (
    f"https://github.com/{config.GITHUB_USER}/{config.FEED_REPO}"
    "/releases/latest/download/GiocaInItaliano.exe"
)
MESSAGGIO = "README: il riquadro di Gioca in Italiano, l'app con tutte le traduzioni"
FIRMA = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

_RIGA_BADGE = re.compile(r"^\s*(\[!\[|!\[|<a\s|<img\s|<p\s+align)", re.I)


def elenco(nomi: list[str]) -> str:
    if len(nomi) <= 1:
        return "".join(nomi)
    return ", ".join(nomi[:-1]) + " e " + nomi[-1]


def blocco(altri: list[tuple[str, str]]) -> str:
    """Il riquadro, con i link alle pagine delle altre traduzioni.

    `altri` e' una lista di (nome del gioco, cartella della pagina sul sito).
    """
    giochi = elenco([f"[{nome}]({SITO}{cartella}/)" for nome, cartella in altri])
    scoperta = f" e ti fa scoprire le altre: {giochi}." if altri else "."
    return "\n".join(
        [
            INIZIO,
            f'<p align="center"><a href="{SITO}"><img src="{SITO}img/{BANNER}" '
            f'alt="Gioca in Italiano: tutte le traduzioni italiane di Sici29 in un\'app sola" width="100%"></a></p>',
            "",
            "> [!TIP]",
            f"> **Tutte le mie traduzioni in un'app sola: [Gioca in Italiano]({SITO})**",
            ">",
            "> Installa e aggiorna questa traduzione con un clic, ti avvisa quando esce "
            "una nuova versione" + scoperta,
            ">",
            f"> **Manca il tuo gioco?** [Proponilo]({SITO}#proponi) e vota quelli proposti "
            "dagli altri: i più votati diventano le prossime traduzioni.",
            ">",
            f"> **[⬇ Scarica Gioca in Italiano]({SCARICA})** · gratis, per Windows 10 e 11",
            FINE,
        ]
    )


def inserisci(readme: str, riquadro: str) -> str:
    """Il README con il riquadro: sostituito se c'e' gia', se no sotto titolo e badge.

    Rispetta gli a capo del file (CRLF o LF), e rilanciata sul risultato non
    cambia niente.
    """
    a_capo = "\r\n" if "\r\n" in readme else "\n"
    righe = readme.replace("\r\n", "\n").split("\n")
    nuovo = riquadro.split("\n")

    if INIZIO in righe and FINE in righe[righe.index(INIZIO):]:
        i = righe.index(INIZIO)
        j = righe.index(FINE, i)
        righe[i:j + 1] = nuovo
        return a_capo.join(righe)

    # Sotto il titolo (la prima riga "# ...") e sotto i badge che lo seguono,
    # cosi' in cima al repo resta il nome della traduzione.
    pos = 0
    titolo = next((k for k, r in enumerate(righe) if r.startswith("# ")), None)
    if titolo is not None and titolo < 5:
        pos = titolo + 1
        k = pos
        while k < len(righe) and (not righe[k].strip() or _RIGA_BADGE.match(righe[k])):
            if righe[k].strip():
                pos = k + 1
            k += 1
    blocco_righe = [""] + nuovo + [""] if pos else nuovo + [""]
    # Niente righe vuote doppie attorno al riquadro.
    while pos < len(righe) and not righe[pos].strip():
        righe.pop(pos)
    righe[pos:pos] = blocco_righe
    return a_capo.join(righe)


# --- GitHub ------------------------------------------------------------------


def traduzioni() -> list[tuple[str, str, str]]:
    """(repo, nome del gioco, cartella sul sito) di ogni traduzione pubblicata."""
    dati = requests.get(config.FEED_URL, timeout=30).json()
    out = []
    for voce in dati.get("entries") or []:
        repo = (voce.get("repo") or {}).get("name") or ""
        if not repo or not voce.get("releases"):
            continue
        marker = voce.get("marker") or {}
        nome = marker.get("nome_gioco") or config.pretty_game_name(repo)
        out.append((repo, nome, slug(nome)))
    return out


def _gh(*argomenti: str, dati: dict | None = None) -> dict:
    comando = ["gh", "api", *argomenti]
    if dati is not None:
        comando += ["--input", "-"]
    esito = subprocess.run(
        comando,
        input=json.dumps(dati) if dati is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if esito.returncode != 0:
        raise RuntimeError(esito.stderr.strip() or esito.stdout.strip())
    return json.loads(esito.stdout or "{}")


def aggiorna(repo: str, riquadro: str, scrivi: bool) -> str:
    utente = config.GITHUB_USER
    info = _gh(f"repos/{utente}/{repo}/readme")
    attuale = base64.b64decode(info["content"]).decode("utf-8")
    nuovo = inserisci(attuale, riquadro)
    if nuovo == attuale:
        return "gia' a posto"
    if not scrivi:
        return f"da aggiornare (+{len(nuovo) - len(attuale)} caratteri)"
    _gh(
        "-X", "PUT", f"repos/{utente}/{repo}/contents/{info['path']}",
        dati={
            "message": f"{MESSAGGIO}\n\n{FIRMA}",
            "content": base64.b64encode(nuovo.encode("utf-8")).decode("ascii"),
            "sha": info["sha"],
        },
    )
    return "aggiornato"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scrivi", action="store_true", help="fa davvero i commit")
    args = ap.parse_args(argv)

    tutte = traduzioni()
    for repo, nome, _ in tutte:
        altri = [(n, c) for r, n, c in tutte if r != repo]
        print(f"{repo}: {aggiorna(repo, blocco(altri), args.scrivi)}")
    if not args.scrivi:
        print("\nNiente e' stato scritto: rilancia con --scrivi per fare i commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
