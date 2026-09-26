"""La logica pura dell'interfaccia, eseguita davvero con Node.

app.js non e' solo disegno: decide l'ordine delle card, come si cerca e cosa
si legge sotto il titolo quando c'e' un aggiornamento. Sono le parti che si
rompono in silenzio - restano sintatticamente valide e mostrano la cosa
sbagliata - quindi qui si eseguono per davvero invece di leggerle.

Serve Node, che su Windows arriva con gli strumenti di sviluppo: se non c'e',
i test si saltano da soli e il resto della suite non ne risente.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
APP_JS = RADICE / "hub" / "web" / "app.js"
NODE = shutil.which("node")

# app.js si aspetta un browser: aggancia gestori e cerca elementi appena viene
# caricato. Qui gli si mette sotto il minimo indispensabile perche' arrivi in
# fondo, poi si chiamano le funzioni che interessano. Nessun DOM vero: se una
# funzione di questo file avesse bisogno della pagina, non sarebbe pura e non
# andrebbe provata cosi'.
IMPALCATURA = """
const elementoFinto = new Proxy({}, {
  get(_, prop) {
    if (prop === 'classList') return { toggle() {}, add() {}, remove() {}, contains: () => false };
    if (prop === 'dataset') return {};
    if (prop === 'style') return {};
    if (typeof prop === 'string' && ['addEventListener','focus','scrollIntoView','remove','click'].includes(prop)) return () => {};
    return '';
  },
  set() { return true; },
});
globalThis.document = {
  querySelector: () => elementoFinto,
  querySelectorAll: () => [],
  addEventListener: () => {},
  get activeElement() { return null; },
};
globalThis.window = { addEventListener: () => {}, scrollTo: () => {}, scrollY: 0 };
globalThis.navigator = { clipboard: { writeText: async () => {} } };
globalThis.CSS = { escape: (s) => s };
globalThis.console = { warn() {}, error() {}, log() {} };
"""


def esegui(espressione: str):
    """Carica app.js in Node e restituisce il valore dell'espressione.

    Il codice passa da un file temporaneo e non da `node -e`: app.js supera i
    50 KB e Windows rifiuta righe di comando cosi' lunghe.
    """
    codice = (
        IMPALCATURA
        + APP_JS.read_text(encoding="utf-8")
        + f"\nprocess.stdout.write(JSON.stringify({espressione}));"
    )
    with tempfile.TemporaryDirectory() as cartella:
        prova = Path(cartella) / "prova.js"
        prova.write_text(codice, encoding="utf-8")
        esito = subprocess.run(
            [NODE, str(prova)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    if esito.returncode != 0:
        raise AssertionError(f"Node ha fallito:\n{esito.stderr[:1500]}")
    return json.loads(esito.stdout)


@unittest.skipUnless(NODE, "Node non e' installato")
class Sintassi(unittest.TestCase):
    def test_app_js_si_carica_senza_errori(self):
        # Da solo vale il prezzo del file: una virgola di troppo in app.js
        # non si vede finche' non si apre la finestra.
        self.assertEqual(esegui("1 + 1"), 2)


@unittest.skipUnless(NODE, "Node non e' installato")
class RigaDelleNovita(unittest.TestCase):
    """Cosa finisce sotto il titolo della card quando c'e' un aggiornamento."""

    def test_salta_il_titolo_e_prende_il_primo_punto(self):
        note = "# Aniimo 1.0\n\n### Novita':\n\n- Tradotte 11 stringhe nuove\n- Refusi"
        self.assertEqual(
            esegui(f"primaRiga({json.dumps(note)})"), "Tradotte 11 stringhe nuove"
        )

    def test_le_liste_numerate_valgono_come_punti(self):
        note = "## Changelog\n1. Rifatti i dialoghi del capitolo 3\n2. Altro"
        self.assertEqual(
            esegui(f"primaRiga({json.dumps(note)})"), "Rifatti i dialoghi del capitolo 3"
        )

    def test_senza_elenco_va_bene_la_prosa(self):
        note = "Corretta la traduzione del menu impostazioni."
        self.assertEqual(esegui(f"primaRiga({json.dumps(note)})"), note)

    def test_dei_link_resta_solo_il_testo(self):
        note = "- Vedi [le note complete](https://esempio.it/note) per i dettagli"
        self.assertEqual(
            esegui(f"primaRiga({json.dumps(note)})"),
            "Vedi le note complete per i dettagli",
        )

    def test_note_fatte_di_soli_titoli_non_dicono_niente(self):
        # Meglio niente che ripetere il nome del gioco, che sulla card c'e' gia'.
        self.assertEqual(esegui('primaRiga("# Release 1.2\\n## Sottotitolo")'), "")

    def test_note_vuote(self):
        self.assertEqual(esegui('primaRiga("")'), "")
        self.assertEqual(esegui("primaRiga(null)"), "")


@unittest.skipUnless(NODE, "Node non e' installato")
class Ricerca(unittest.TestCase):
    def test_gli_accenti_non_contano(self):
        # Nessuno scrive gli accenti in un campo di ricerca.
        self.assertEqual(esegui('piatto("Pok\\u00e9mon Caf\\u00e9")'), "pokemon cafe")

    def test_le_maiuscole_nemmeno(self):
        self.assertEqual(esegui('piatto("ARK: Survival")'), "ark: survival")

    def test_regge_i_valori_mancanti(self):
        self.assertEqual(esegui("piatto(undefined)"), "")


@unittest.skipUnless(NODE, "Node non e' installato")
class OrdinePerTe(unittest.TestCase):
    """Prima quello che ti riguarda, non quello che e' uscito per ultimo."""

    CASI = [
        ({"installed_game": True, "status": "aggiornamento"}, 0),
        ({"installed_game": True, "installed_tag": ""}, 1),
        ({"installed_game": True, "installed_tag": "v1"}, 2),
        ({"installed_game": False, "status": "aggiornamento"}, 3),
        ({"installed_game": False, "installed_tag": "v1"}, 4),
        ({"installed_game": False}, 5),
    ]

    def test_la_scala_delle_priorita(self):
        for progetto, atteso in self.CASI:
            with self.subTest(progetto=progetto):
                self.assertEqual(esegui(f"urgenza({json.dumps(progetto)})"), atteso)

    def test_il_tuo_gioco_da_aggiornare_batte_tutto(self):
        tuo = {"installed_game": True, "status": "aggiornamento"}
        altro = {"installed_game": False, "status": "aggiornamento"}
        self.assertLess(
            esegui(f"urgenza({json.dumps(tuo)})"),
            esegui(f"urgenza({json.dumps(altro)})"),
        )


@unittest.skipUnless(NODE, "Node non e' installato")
class NumeriAllItaliana(unittest.TestCase):
    def test_migliaia_col_punto_anche_a_quattro_cifre(self):
        # L'italiano non raggruppa i numeri di quattro cifre se non glielo si
        # chiede: senza useGrouping "always" qui uscirebbe 1284.
        self.assertEqual(esegui("fmtNum(1284)"), "1.284")
        self.assertEqual(esegui("fmtNum(1284000)"), "1.284.000")


def _badge(progetto: dict) -> list:
    """I testi dei badge che cardHtml mette su una card."""
    base = {
        "repo": "X", "title": "X", "latest": {"tag": "v2", "date": "2026-09-20T00:00:00Z"},
        "total_downloads": 0, "stars": 0, "cover": "", "tinta": "",
    }
    base.update(progetto)
    return esegui(
        f"[...cardHtml({json.dumps(base)}).matchAll(/class=\"badge[^\"]*\"[^>]*>([^<]+)</g)].map(m => m[1])"
    )


@unittest.skipUnless(NODE, "Node non e' installato")
class UnBadgeSoloPerLoStato(unittest.TestCase):
    """Il caso segnalato: "Aggiornata" e "Da aggiornare" sulla stessa card.

    In italiano "aggiornata" si legge "e' gia' a posto", cioe' l'opposto di
    quello che il badge voleva dire. Adesso lo stato ha un badge solo.
    """

    def test_da_aggiornare_non_si_somma_alla_novita(self):
        badge = _badge({"status": "aggiornamento", "novita": "aggiornamento",
                        "installed_tag": "v1"})
        self.assertEqual(badge, ["Da aggiornare"])

    def test_la_parola_aggiornata_non_compare_piu(self):
        for stato, novita in [("aggiornamento", "aggiornamento"), ("", "aggiornamento"),
                              ("aggiornato", None), ("", "nuova")]:
            with self.subTest(stato=stato, novita=novita):
                self.assertNotIn("Aggiornata", _badge({"status": stato, "novita": novita}))

    def test_nuova_versione_di_una_traduzione_non_installata(self):
        self.assertEqual(_badge({"status": "", "novita": "aggiornamento"}), ["Nuova versione"])

    def test_traduzione_mai_vista(self):
        self.assertEqual(_badge({"status": "", "novita": "nuova"}), ["Nuova"])

    def test_installata_e_in_pari(self):
        self.assertEqual(_badge({"status": "aggiornato", "novita": None}), ["Installata"])


@unittest.skipUnless(NODE, "Node non e' installato")
class CompatibilitaSenzaPromesseFalse(unittest.TestCase):
    """Il secondo caso segnalato: un pallino verde basato su una deduzione.

    Dalle date si ricava un fatto solo in una direzione: "il gioco e' stato
    aggiornato dopo la traduzione" e' vero e basta; "non e' stato aggiornato
    dopo" non prova che la traduzione sia fatta per quella build.
    """

    def _mostra(self, stato, certezza, dove):
        c = {"stato": stato, "certezza": certezza}
        return esegui(f"compatDaMostrare({json.dumps(c)}, {json.dumps(dove)}) !== null")

    def test_niente_verde_dalle_sole_date(self):
        self.assertFalse(self._mostra("allineata", "indiziaria", "dettagli"))
        self.assertFalse(self._mostra("allineata", "indiziaria", "card"))

    def test_verde_solo_con_una_conferma_dichiarata(self):
        self.assertTrue(self._mostra("allineata", "esatta", "dettagli"))
        self.assertTrue(self._mostra("allineata", "serie", "dettagli"))

    def test_il_verde_non_finisce_mai_sulla_card(self):
        # E' il caso normale: su ogni card sarebbe rumore.
        self.assertFalse(self._mostra("allineata", "esatta", "card"))

    def test_gioco_aggiornato_dopo_e_un_fatto_anche_dalle_date(self):
        self.assertTrue(self._mostra("gioco_avanti", "indiziaria", "dettagli"))

    def test_ma_sulla_card_solo_se_certo(self):
        # Un avviso vistoso su un indizio debole diventa un falso allarme, e
        # dopo due falsi allarmi nessuno guarda piu' nemmeno quello vero.
        self.assertFalse(self._mostra("gioco_avanti", "indiziaria", "card"))
        self.assertTrue(self._mostra("gioco_avanti", "esatta", "card"))

    def test_stato_ignoto(self):
        self.assertFalse(self._mostra("", "", "dettagli"))
        self.assertEqual(esegui("compatDaMostrare(undefined, 'card')"), None)

    def test_la_frase_non_parla_di_traduzione_installata(self):
        # "Allineata alla versione che hai installata", accanto a
        # "Installata: no", faceva pensare alla traduzione e non al gioco.
        testo = esegui("COMPAT.allineata.lungo")
        self.assertNotIn("installata", testo.lower())
        self.assertIn("gioco", testo.lower())


@unittest.skipUnless(NODE, "Node non e' installato")
class PulsantePrincipale(unittest.TestCase):
    """Il pulsante della card fa la cosa piu' utile in quel momento."""

    def _azione(self, **progetto):
        base = {"repo": "R", "latest": {"tag": "v2", "download": {"url": "x"}}}
        base.update(progetto)
        return esegui(f"azionePrincipale({json.dumps(base)})")

    def test_installata_e_in_pari_si_gioca(self):
        a = self._azione(status="aggiornato", avvio="steam:1")
        self.assertEqual(a["label"], "Gioca")
        self.assertTrue(a["gioca"])

    def test_senza_modo_di_avviarla_resta_reinstalla(self):
        self.assertEqual(self._azione(status="aggiornato", avvio="")["label"], "Reinstalla")

    def test_da_aggiornare_si_aggiorna_anche_se_si_potrebbe_giocare(self):
        # Prima la traduzione aggiornata, poi il gioco: al contrario si
        # giocherebbe con la traduzione vecchia.
        self.assertEqual(self._azione(status="aggiornamento", avvio="steam:1")["label"], "Aggiorna")

    def test_non_installata(self):
        self.assertEqual(self._azione(status="")["label"], "Installa")


@unittest.skipUnless(NODE, "Node non e' installato")
class MenuAltro(unittest.TestCase):
    def _voci(self, **progetto):
        base = {"repo": "R", "bug_url": "b", "releases_url": "r",
                "installer": {"install": ["install"], "restore": ["restore"], "check": ["check"]}}
        base.update(progetto)
        return esegui(
            f"[...menuAltro({json.dumps(base)}).matchAll(/role=\"menuitem\"[^>]*>([^<]+)</g)].map(m => m[1])"
        )

    def test_senza_gioco_niente_ripristino_ne_controllo(self):
        voci = self._voci(installed_game=False)
        self.assertNotIn("Ripristina i file originali", voci)
        self.assertNotIn("Controlla la traduzione", voci)
        # L'installer completo resta sempre raggiungibile: e' la via d'uscita.
        self.assertIn("Apri l’installer completo", voci)

    def test_con_il_gioco_c_e_tutto(self):
        voci = self._voci(installed_game=True, status="aggiornato")
        for voce in ("Controlla la traduzione", "Reinstalla", "Ripristina i file originali",
                     "Apri la cartella del gioco"):
            self.assertIn(voce, voci)

    def test_i_backup_solo_se_l_installer_li_sa_aprire(self):
        self.assertNotIn("Apri la cartella dei backup", self._voci())
        con = self._voci(installer={"backup": ["backup-dir"]})
        self.assertIn("Apri la cartella dei backup", con)

    def test_cartella_scelta_a_mano(self):
        self.assertIn("Indica la cartella del gioco…", self._voci())
        voci = self._voci(cartella_scelta="E:/Giochi/X")
        self.assertIn("Cambia la cartella del gioco…", voci)
        self.assertIn("Torna a cercarla da solo", voci)


if __name__ == "__main__":
    unittest.main()
