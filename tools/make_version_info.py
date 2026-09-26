"""Genera build/version_info.txt, le proprieta' che Windows mostra sull'exe.

Viene ricavato da hub.__version__, cosi' la versione nelle proprieta' del file
non puo' divergere da quella dell'applicazione.

    python tools/make_version_info.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import APP_TITLE, __version__  # noqa: E402
from hub import config  # noqa: E402

TEMPLATE = """# Generato da tools/make_version_info.py - non modificare a mano.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041004b0',
        [
          StringStruct('CompanyName', '{autore}'),
          StringStruct('FileDescription', '{descrizione}'),
          StringStruct('FileVersion', '{versione}'),
          StringStruct('InternalName', '{interno}'),
          StringStruct('LegalCopyright', '{copyright}'),
          StringStruct('OriginalFilename', '{file}'),
          StringStruct('ProductName', '{prodotto}'),
          StringStruct('ProductVersion', '{versione}')
        ]
      )
    ]),
    # 1040 = italiano (Italia), 1200 = Unicode
    VarFileInfo([VarStruct('Translation', [1040, 1200])])
  ]
)
"""


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/version_info.txt")
    dest.parent.mkdir(parents=True, exist_ok=True)

    parti = (__version__.split("+")[0].split("-")[0].split(".") + ["0", "0", "0"])[:3]
    numeri = [int(p) if p.isdigit() else 0 for p in parti]

    dest.write_text(
        TEMPLATE.format(
            v0=numeri[0],
            v1=numeri[1],
            v2=numeri[2],
            autore=config.GITHUB_USER,
            descrizione="Gioca in Italiano - le traduzioni di Sici29",
            versione=__version__,
            interno="GiocaInItaliano",
            copyright=f"{config.GITHUB_USER} - traduzioni amatoriali non ufficiali",
            file="GiocaInItaliano.exe",
            prodotto=APP_TITLE,
        ),
        encoding="utf-8",
    )
    print(f"scritto {dest} (versione {__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
