"""La traduzione e' allineata al gioco che hai installato?

E' la domanda che decide se una traduzione funzionera' davvero, e finora
l'hub non la poneva: mostrava l'ultima versione pubblicata e basta. Ma una
patch del gioco rimescola le stringhe, e una traduzione ferma a due patch fa
lascia pezzi di testo in inglese anche se e' "l'ultima disponibile".

Tre modi di rispondere, dal piu' solido al piu' debole. Si prende il primo
che da' un risultato:

  1. **Build contro build.** Steam scrive il numero esatto della build
     installata in appmanifest (`buildid`); se la traduzione dichiara quale
     build copre - in hub.json, o nel nome del rilascio - il confronto e'
     aritmetico e non lascia dubbi.

  2. **Serie contro serie.** Per i giochi fuori Steam si confronta la serie
     (4.10 contro 4.10): Star Citizen scrive `sc-alpha-4.10.0` nei suoi file
     e i rilasci si chiamano `sc-4.10-r2`. Meno preciso di una build, ma e'
     il modo in cui la gente parla delle patch.

  3. **Date.** Se nessuno dichiara niente resta il fatto che Steam registra
     quando il gioco e' stato aggiornato l'ultima volta: se e' successo dopo
     l'uscita della traduzione, il sospetto e' fondato. Vale per qualunque
     gioco Steam senza che nessuno debba dichiarare nulla, ed e' il motivo
     per cui questo terzo modo esiste.

**Cosa NON si dice.** Mai "incompatibile". Una patch puo' non toccare una
riga di testo, e allora la traduzione funziona benissimo anche con la build
diversa. L'hub riferisce quello che sa - "il gioco e' stato aggiornato dopo
questa traduzione" - e lascia la conclusione a chi legge. Quando non sa, tace:
una rassicurazione inventata e' peggio del silenzio.
"""

from __future__ import annotations

import re

# --- verdetti ----------------------------------------------------------------

IGNOTO = ""
ALLINEATA = "allineata"
GIOCO_AVANTI = "gioco_avanti"
TRADUZIONE_AVANTI = "traduzione_avanti"

# Quanto vale la risposta: "esatta" viene da numeri di build dichiarati,
# "serie" dal confronto fra versioni maggiori, "indiziaria" dalle sole date.
ESATTA = "esatta"
SERIE = "serie"
INDIZIARIA = "indiziaria"

# Sotto questo scarto un aggiornamento del gioco e una traduzione si
# considerano dello stesso giro: Steam tocca LastUpdated anche per modifiche
# ai depot che non c'entrano col testo, e la traduzione esce comunque qualche
# ora dopo la patch che insegue.
TOLLERANZA_ORE = 24

# La serie e' la PRIMA coppia maggiore.minore che si incontra: "sc-alpha-4.10.0"
# e "4.10.193.11644" danno entrambi 4.10, che e' come la gente chiama quella
# patch. Il terzo e il quarto numero cambiano a ogni hotfix e non dicono niente
# sul testo del gioco, quindi si fermano fuori.
_SERIE = re.compile(r"(\d{1,4})\.(\d{1,4})")


def _serie(testo) -> tuple[int, int] | None:
    """La serie di una versione, comunque sia scritta.

    Si converte a stringa invece di pretenderla: questi valori arrivano da
    file JSON scritti da altri, e un `"Branch": 4.10` senza virgolette
    farebbe esplodere una funzione che gira su ogni traduzione a ogni
    controllo. Il risultato sarebbe una griglia vuota.
    """
    match = _SERIE.search(str(testo) if testo is not None else "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def build_dichiarata(marker: dict | None) -> int | None:
    """La build Steam che questa traduzione copre, SOLO se dichiarata.

    Qui non si indovina, e c'e' un motivo preciso. Il primo tentativo leggeva
    il numero dal nome del rilascio: "Release 1.0.3595896.0: supporto Steam
    build 3595896" sembrava dire tutto. Ma 3595896 e' il numero di build
    *interno del gioco*, mentre nell'appmanifest Steam scrive il proprio, che
    per lo stesso gioco e' 25525975. Due numerazioni che non si parlano:
    confrontarle dava "il gioco e' avanti di ventidue milioni di build" su una
    traduzione perfettamente allineata.

    Un confronto fra build vale solo se qualcuno garantisce che i due numeri
    siano della stessa specie, e a garantirlo puo' essere solo chi pubblica la
    traduzione, scrivendo `game_build` nel hub.json. Senza quella riga si
    scende ai criteri piu' deboli, che sbagliano meno perche' promettono meno.
    """
    for chiave in ("game_build", "steam_build"):
        valore = (marker or {}).get(chiave)
        try:
            if valore is not None and int(valore) > 0:
                return int(valore)
        except (TypeError, ValueError):
            continue
    return None


def versione_dichiarata(marker: dict | None, release: dict | None) -> str:
    """La versione del gioco che questa traduzione copre, come stringa."""
    for chiave in ("game_version", "version"):
        valore = (marker or {}).get(chiave)
        if isinstance(valore, (str, int)) and str(valore).strip():
            return str(valore).strip()
    for campo in ("tag", "name"):
        testo = (release or {}).get(campo) or ""
        if _serie(testo):
            return testo
    return ""


def _ore(uno: str, due: str) -> float | None:
    """Ore fra due istanti ISO 8601, o None se non si riescono a leggere."""
    from datetime import datetime

    def leggi(valore):
        if not valore:
            return None
        try:
            return datetime.fromisoformat(str(valore).replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = leggi(uno), leggi(due)
    if not a or not b:
        return None
    return (a - b).total_seconds() / 3600


def valuta(marker: dict | None, release: dict | None, gioco: dict | None) -> dict:
    """Confronta la traduzione col gioco installato.

    `marker` e' il hub.json del repo, `release` l'ultimo rilascio, `gioco` il
    record della scansione locale. Senza gioco installato non c'e' niente da
    confrontare: la domanda non si pone.

    Torna sempre un dizionario con `stato`, `certezza` e i due valori messi a
    confronto, cosi' l'interfaccia puo' anche mostrarli.
    """
    vuoto = {"stato": IGNOTO, "certezza": "", "gioco": "", "traduzione": ""}
    if not gioco:
        return vuoto

    release = release or {}
    marker = marker or {}

    # 1. Build contro build: l'unico confronto che non lascia dubbi.
    build_gioco = gioco.get("build")
    build_trad = build_dichiarata(marker)
    if isinstance(build_gioco, int) and build_trad:
        if build_gioco == build_trad:
            stato = ALLINEATA
        elif build_gioco > build_trad:
            stato = GIOCO_AVANTI
        else:
            stato = TRADUZIONE_AVANTI
        return {
            "stato": stato,
            "certezza": ESATTA,
            "gioco": str(build_gioco),
            "traduzione": str(build_trad),
        }

    # 2. Serie contro serie, per i giochi fuori Steam.
    testo_gioco = gioco.get("branch") or gioco.get("version") or ""
    testo_trad = versione_dichiarata(marker, release)
    serie_gioco, serie_trad = _serie(testo_gioco), _serie(testo_trad)
    if serie_gioco and serie_trad:
        if serie_gioco == serie_trad:
            stato = ALLINEATA
        elif serie_gioco > serie_trad:
            stato = GIOCO_AVANTI
        else:
            stato = TRADUZIONE_AVANTI
        return {
            "stato": stato,
            "certezza": SERIE,
            "gioco": gioco.get("version") or testo_gioco,
            "traduzione": release.get("tag") or testo_trad,
        }

    # 3. Date: nessuno ha dichiarato niente, ma Steam sa quando ha aggiornato.
    scarto = _ore(_iso(gioco.get("updated")), release.get("date"))
    if scarto is not None:
        avanti = scarto > TOLLERANZA_ORE
        return {
            "stato": GIOCO_AVANTI if avanti else ALLINEATA,
            "certezza": INDIZIARIA,
            "gioco": "",
            "traduzione": release.get("tag") or "",
            "ore": round(scarto),
        }

    return vuoto


def _iso(timestamp) -> str:
    """Il LastUpdated di Steam e' un unix time: qui serve in ISO."""
    from datetime import datetime, timezone

    try:
        if not timestamp:
            return ""
        return datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
