"""Fa partire subito il giro "Catalogo e sito" e aspetta che finisca.

Il giro programmato passa da solo ogni ora, ma GitHub non ne garantisce
l'orario: nei momenti di carico lo ritarda, a volte di ore, o lo salta.
Appena pubblicata una traduzione nuova, o una versione nuova, questo lo
anticipa: in un paio di minuti catalogo dell'hub e sito sono aggiornati.

Serve la CLI di GitHub (gh), autenticata sul proprio account.

    python tools/aggiorna_sito.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from hub import config  # noqa: E402

REPO = f"{config.GITHUB_USER}/{config.FEED_REPO}"
WORKFLOW = "catalogo-e-sito.yml"
ATTESA_MASSIMA = 15 * 60  # secondi: un giro normale ne dura due o tre minuti


def _gh(*argomenti: str) -> str:
    esito = subprocess.run(
        ["gh", *argomenti], capture_output=True, text=True, encoding="utf-8"
    )
    if esito.returncode != 0:
        raise RuntimeError(esito.stderr.strip() or esito.stdout.strip())
    return esito.stdout


def _giri_a_mano() -> list[dict]:
    uscita = _gh(
        "run", "list", "-R", REPO, "--workflow", WORKFLOW,
        "--event", "workflow_dispatch", "--limit", "5",
        "--json", "databaseId,status,conclusion,url",
    )
    return json.loads(uscita or "[]")


def avvia() -> dict:
    """Avvia il giro e restituisce quello nuovo, appena GitHub lo mostra.

    gh workflow run non dice quale giro ha creato: si riconosce perche' ha un
    numero piu' alto di tutti quelli che c'erano prima.
    """
    prima = max((g["databaseId"] for g in _giri_a_mano()), default=0)
    _gh("workflow", "run", WORKFLOW, "-R", REPO, "--ref", "main")
    for _ in range(30):
        time.sleep(2)
        nuovi = [g for g in _giri_a_mano() if g["databaseId"] > prima]
        if nuovi:
            return min(nuovi, key=lambda g: g["databaseId"])
    raise RuntimeError("GitHub non mostra il giro appena avviato: riprova tra poco.")


def aspetta(giro: dict) -> dict:
    inizio = time.monotonic()
    while time.monotonic() - inizio < ATTESA_MASSIMA:
        stato = json.loads(
            _gh("run", "view", str(giro["databaseId"]), "-R", REPO,
                "--json", "status,conclusion,url")
        )
        if stato.get("status") == "completed":
            return stato
        print(".", end="", flush=True)
        time.sleep(10)
    raise RuntimeError(f"Il giro non e' finito entro {ATTESA_MASSIMA // 60} minuti: {giro['url']}")


def main() -> int:
    try:
        print("Avvio l'aggiornamento di catalogo e sito su GitHub...")
        giro = avvia()
        print(f"Partito: {giro['url']}")
        print("Aspetto che finisca, di solito ci vogliono due o tre minuti", end="", flush=True)
        stato = aspetta(giro)
    except (RuntimeError, OSError) as errore:
        print(f"\nNon e' andato: {errore}")
        return 1
    print()
    if stato.get("conclusion") != "success":
        print(f"Il giro e' finito male ({stato.get('conclusion')}). I dettagli: {stato.get('url')}")
        return 1
    print(f"Fatto. Il sito: {config.SITO_URL}")
    print("Se vedi ancora la versione vecchia, ricarica la pagina tra un minuto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
