"""Controlla che nell'eseguibile non sia finito niente che non ci deve stare.

PyInstaller impacchetta quello che trova installato nel Python che compila,
non quello che serve all'hub. Il 26 settembre 2026 qualcosa ha installato PyQt5
sul PC di sviluppo, e da un giro all'altro l'exe e' passato da 25 a 55 MB con
dentro una libreria sotto GPL v3: distribuirla avrebbe obbligato a pubblicare
l'hub sotto la stessa licenza. Nessun errore, nessun avviso: solo un file piu'
grosso, che poteva benissimo finire in una release.

Le esclusioni nel .spec lo impediscono; questo controllo verifica che abbiano
funzionato, e ferma la build se no.

    python tools/controlla_exe.py dist/GiocaInItaliano.exe
"""

from __future__ import annotations

import sys
from pathlib import Path

# Cosa non deve mai esserci, e perche'. Il prefisso si confronta col percorso
# della voce dentro l'archivio (es. "PyQt5\\Qt5\\bin\\Qt5Core.dll").
VIETATI = {
    "PyQt5": "licenza GPL v3, e l'hub non usa Qt",
    "PyQt6": "licenza GPL v3, e l'hub non usa Qt",
    "PySide2": "Qt non serve: l'hub usa WebView2",
    "PySide6": "Qt non serve: l'hub usa WebView2",
    "tkinter": "interfaccia non usata",
    "_tkinter": "interfaccia non usata",
}

# Oltre questo peso qualcosa e' entrato senza essere invitato. L'exe sano sta
# sui 25 MB: il margine copre la crescita normale, non un motore grafico.
PESO_MASSIMO_MB = 40


def voci(exe: Path) -> list[str]:
    from PyInstaller.archive.readers import CArchiveReader

    return list(CArchiveReader(str(exe)).toc.keys())


def controlla(exe: Path) -> list[str]:
    problemi = []
    for voce in voci(exe):
        radice = voce.replace("/", "\\").split("\\", 1)[0]
        for vietato, perche in VIETATI.items():
            if radice == vietato or radice.startswith(vietato + "."):
                problemi.append(f"{voce}: {perche}")
                break

    peso = exe.stat().st_size / 1_000_000
    if peso > PESO_MASSIMO_MB:
        problemi.append(
            f"l'eseguibile pesa {peso:.1f} MB, oltre il limite di {PESO_MASSIMO_MB}: "
            f"qualche libreria e' entrata senza essere invitata"
        )
    return problemi


def main(argv: list[str]) -> int:
    exe = Path(argv[0] if argv else "dist/GiocaInItaliano.exe")
    if not exe.exists():
        print(f"{exe} non esiste", file=sys.stderr)
        return 2

    problemi = controlla(exe)
    if not problemi:
        print(f"{exe.name}: contenuto a posto ({exe.stat().st_size / 1_000_000:.1f} MB)")
        return 0

    # Una riga per libreria, non una per file: 60 DLL di Qt direbbero la
    # stessa cosa sessanta volte.
    visti, righe = set(), []
    for problema in problemi:
        chiave = problema.split("\\", 1)[0]
        if chiave not in visti:
            visti.add(chiave)
            righe.append(problema)
    print(f"{exe.name}: contenuto NON a posto", file=sys.stderr)
    for riga in righe:
        print(f"  - {riga}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
