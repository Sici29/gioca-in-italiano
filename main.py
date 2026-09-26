"""Punto di ingresso per l'eseguibile compilato.

Sta nella root e usa un import assoluto di proposito: PyInstaller esegue lo
script di avvio come modulo di primo livello, senza pacchetto padre, quindi
un `from .app import ...` dentro hub/ fallirebbe con
"attempted relative import with no known parent package".
"""

import sys

from hub.app import main

if __name__ == "__main__":
    sys.exit(main())
