"""Scrive hub/credenziali.py, il file che porta l'accesso dentro l'eseguibile.

Perche' esiste, invece di scrivere le due stringhe in config.py: GitHub fa
secret scanning sui repository pubblici e i client secret OAuth li **revoca da
solo** appena compaiono in un commit. Un secret in config.py, su un repo
pubblico, e' un secret che smette di funzionare per tutti nel giro di poco.

hub/credenziali.py sta nel .gitignore, quindi non finisce mai in un commit, ma
e' un normalissimo modulo: PyInstaller lo include nell'eseguibile come tutti
gli altri, e config.py lo preferisce ai propri valori. Il risultato e' che
l'exe distribuito ha le credenziali e il repository no.

    python tools/imposta_credenziali.py             dagli appunti
    python tools/imposta_credenziali.py ID SECRET   dagli argomenti
    python tools/imposta_credenziali.py --mostra    cosa c'e' adesso
    python tools/imposta_credenziali.py --togli     rimuove il file

Il secret non viene mai stampato, nemmeno da --mostra.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import auth  # noqa: E402

DESTINAZIONE = Path(__file__).resolve().parents[1] / "hub" / "credenziali.py"

INTESTAZIONE = '''"""Credenziali dell'applicazione OAuth. GENERATO, NON VERSIONARE.

Scritto da tools/imposta_credenziali.py. Sta nel .gitignore perche' GitHub
revoca i client secret che trova nei repository pubblici; finisce pero'
nell'eseguibile, ed e' cosi' che chi scarica l'hub trova l'accesso pronto.

Per rigenerarlo:  python tools/imposta_credenziali.py
"""

OAUTH_CLIENT_ID = {cid!r}
OAUTH_CLIENT_SECRET = {secret!r}
'''


def maschera(valore: str) -> str:
    """Quel tanto che basta a riconoscerlo, non a riusarlo."""
    if len(valore) <= 10:
        return "*" * len(valore)
    return f"{valore[:6]}{'*' * (len(valore) - 10)}{valore[-4:]}"


def dagli_appunti() -> str:
    try:
        esito = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return esito.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def estrai(testo: str) -> tuple[str, str] | None:
    """Ricava le due stringhe da qualunque cosa sia stata copiata.

    Accetta sia le righe pronte per config.py sia le due stringhe nude, in
    qualunque ordine: a rimetterle a posto ci pensa auth.sort_credentials,
    lo stesso codice che usa la procedura guidata nella finestra.
    """
    valori = re.findall(r'^\s*OAUTH_CLIENT_(?:ID|SECRET)\s*=\s*["\']([^"\']+)["\']',
                        testo, re.M)
    if len(valori) < 2:
        valori = [r.strip() for r in testo.splitlines() if r.strip()]
    if len(valori) < 2:
        return None
    return auth.sort_credentials(valori[0], valori[1])


def mostra() -> int:
    if not DESTINAZIONE.exists():
        print("hub/credenziali.py non c'e': l'eseguibile uscirebbe senza accesso.")
        print("Le credenziali valgono solo sul PC dove hai fatto la procedura.")
        return 1
    import importlib

    modulo = importlib.import_module("hub.credenziali")
    print(f"hub/credenziali.py c'e'.")
    print(f"  Client ID      {maschera(modulo.OAUTH_CLIENT_ID)}")
    print(f"  Client secret  {maschera(modulo.OAUTH_CLIENT_SECRET)}")
    print("\nL'eseguibile compilato adesso avra' l'accesso a un clic per tutti.")
    return 0


def togli() -> int:
    if DESTINAZIONE.exists():
        DESTINAZIONE.unlink()
        print("hub/credenziali.py rimosso.")
    else:
        print("Non c'era niente da rimuovere.")
    return 0


def main(argv: list[str]) -> int:
    if "--mostra" in argv:
        return mostra()
    if "--togli" in argv:
        return togli()

    argomenti = [a for a in argv if not a.startswith("--")]
    if len(argomenti) >= 2:
        coppia = auth.sort_credentials(argomenti[0], argomenti[1])
        provenienza = "dagli argomenti"
    else:
        coppia = estrai(dagli_appunti())
        provenienza = "dagli appunti"

    if coppia is None:
        print("Non ho trovato due stringhe negli appunti.", file=sys.stderr)
        print(
            "\nNell'hub: Impostazioni -> Copia le righe per config.py,\n"
            "poi rilancia questo comando.",
            file=sys.stderr,
        )
        return 1

    cid, secret = coppia
    DESTINAZIONE.write_text(
        INTESTAZIONE.format(cid=cid, secret=secret), encoding="utf-8"
    )
    print(f"Scritto hub/credenziali.py ({provenienza}).")
    print(f"  Client ID      {maschera(cid)}")
    print(f"  Client secret  {maschera(secret)}")
    print("\nNon e' versionato: sta nel .gitignore. Ora ricompila con")
    print("  .\\build\\build.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
