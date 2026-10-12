"""Mette in cima al README di ogni traduzione il riquadro di Gioca in Italiano.

Chi arriva sul repo di una traduzione e' gia' interessato: il riquadro gli dice
che c'e' un'app che la installa e la aggiorna da sola, che esistono le altre
traduzioni (con il link alle loro pagine) e che puo' proporre il prossimo gioco.

Il riquadro sta fra due commenti, inizio e fine: se c'e' gia' viene sostituito,
altrimenti si mette sotto il titolo e i badge. Cosi' lo strumento si rilancia
quando arriva una traduzione nuova, e tutti i README si aggiornano con
l'elenco giusto. Legge le traduzioni dal catalogo nel repo dell'hub, e legge
e scrive con la CLI di GitHub (gh), che deve essere autenticata. Per una
traduzione appena uscita, prima tools/aggiorna_sito.py: la mette in catalogo.

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

# Quante altre traduzioni nomina il riquadro: le piu' recenti, cosi' chi
# arriva su un repo scopre le novita'. Con cento traduzioni un elenco completo
# sarebbe un muro di link; le altre si trovano sul sito, a cui il riquadro
# porta comunque.
QUANTE_NEL_RIQUADRO = 5

_RIGA_BADGE = re.compile(r"^\s*(\[!\[|!\[|<a\s|<img\s|<p\s+align)", re.I)


def elenco(nomi: list[str]) -> str:
    if len(nomi) <= 1:
        return "".join(nomi)
    return ", ".join(nomi[:-1]) + " e " + nomi[-1]


def blocco(altri: list[tuple[str, str]], totale: int | None = None) -> str:
    """Il riquadro, con i link alle pagine delle altre traduzioni.

    `altri` e' una lista di (nome del gioco, cartella della pagina sul sito),
    gia' in ordine; `totale` quante sono le altre in tutto, se sono di piu'.
    """
    giochi = elenco([f"[{nome}]({SITO}{cartella}/)" for nome, cartella in altri])
    if totale and totale > len(altri):
        scoperta = (
            f" e ti fa scoprire le altre {totale}. Le più recenti: {giochi}. "
            f"[Guardale tutte]({SITO}#giochi)."
        )
    elif altri:
        scoperta = f" e ti fa scoprire le altre: {giochi}."
    else:
        scoperta = "."
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


def da_mostrare(
    tutte: list[tuple[str, str, str, str]], repo: str, quante: int = QUANTE_NEL_RIQUADRO
) -> tuple[list[tuple[str, str]], int]:
    """Le altre traduzioni da nominare nel README di `repo`, e quante sono in tutto.

    Le piu' recenti per prime, cioe' quelle uscite per ultime.
    """
    altre = [t for t in tutte if t[0] != repo]
    return [(nome, cartella) for _, nome, cartella, _ in in_ordine(altre)[:quante]], len(altre)


def in_ordine(tutte: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    """Dalla traduzione uscita per ultima alla prima; a pari data, per nome."""
    per_nome = sorted(tutte, key=lambda t: t[1].lower())
    return sorted(per_nome, key=lambda t: t[3], reverse=True)


def traduzioni() -> list[tuple[str, str, str, int]]:
    """(repo, nome del gioco, cartella sul sito, uscita) di ogni traduzione pubblicata."""
    # Dall'API e non da raw.githubusercontent, che tiene in cache il file per
    # qualche minuto: subito dopo tools/aggiorna_sito.py darebbe ancora
    # l'elenco di prima, senza la traduzione appena uscita.
    dati = _gh(
        "-H", "Accept: application/vnd.github.raw+json",
        f"repos/{config.GITHUB_USER}/{config.FEED_REPO}/contents/catalog.json",
    )
    out = []
    for voce in dati.get("entries") or []:
        repo = (voce.get("repo") or {}).get("name") or ""
        # Come il sito: senza una release vera non c'e' una pagina a cui portare.
        if not repo or not [r for r in voce.get("releases") or [] if not r.get("prerelease")]:
            continue
        marker = voce.get("marker") or {}
        nome = marker.get("nome_gioco") or config.pretty_game_name(repo)
        out.append((repo, nome, slug(nome), prima_uscita(repo)))
    return out


def prima_uscita(repo: str) -> str:
    """Quando e' uscita la traduzione: la data della sua prima release.

    Non dal catalogo, che di ogni repo tiene solo le release recenti: per una
    traduzione aggiornata spesso la piu' vecchia rimasta e' di poche settimane
    fa, e passerebbe per nuova.
    """
    esito = subprocess.run(
        [
            "gh", "api", "--paginate",
            f"repos/{config.GITHUB_USER}/{repo}/releases?per_page=100",
            "--jq", ".[] | select((.draft or .prerelease) | not) | .published_at",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if esito.returncode != 0:
        raise RuntimeError(esito.stderr.strip() or esito.stdout.strip())
    date = esito.stdout.split()
    return min(date) if date else ""


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
    print("Dalla piu' recente:")
    for _, nome, _, uscita in in_ordine(tutte):
        print(f"  {uscita[:10]}  {nome}")
    print()
    for repo, *_ in tutte:
        altri, totale = da_mostrare(tutte, repo)
        print(f"{repo}: {aggiorna(repo, blocco(altri, totale), args.scrivi)}")
    if not args.scrivi:
        print("\nNiente e' stato scritto: rilancia con --scrivi per fare i commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
