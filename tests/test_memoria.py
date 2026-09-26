"""L'ultimo catalogo buono, e cosa succede quando GitHub non risponde.

L'avviso diceva "vedi i dati salvati dall'ultima volta", ma di salvato non
c'era niente: con GitHub irraggiungibile all'avvio la griglia restava vuota.
E con il limite di richieste esaurito a meta' giro, quattro traduzioni su
cinque sparivano. Questi test fissano il comportamento giusto: quello che si
e' visto l'ultima volta non si perde per un controllo andato male.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hub import api, catalog


def _progetto(repo, data="2026-09-20T00:00:00Z", **extra):
    base = {
        "repo": repo,
        "title": repo,
        "latest": {"tag": "v1", "date": data},
        "cover": "data:image/jpeg;base64,QUJD",
        "installed_tag": None,
        "installed_at": None,
        "status": catalog.STATUS_NOT_INSTALLED,
        "novita": None,
        "total_downloads": 3,
        "release_count": 1,
        "installed_game": False,
    }
    base.update(extra)
    return base


class CartellaFinta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cartella = Path(self.tmp.name)
        for bersaglio in (catalog.paths, catalog.covers.paths):
            patch = mock.patch.object(bersaglio, "cache_dir", lambda: self.cartella)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(
            catalog.covers, "percorso", lambda repo: self.cartella / f"{repo}.jpg"
        )
        patch.start()
        self.addCleanup(patch.stop)


class UltimoCatalogo(CartellaFinta):
    def test_salva_e_ricarica(self):
        catalog.salva_ultimo(
            {"projects": [_progetto("A"), _progetto("B")], "source": "api"},
            "2026-09-26T08:00:00+00:00",
        )
        with mock.patch.object(catalog.state, "load", return_value={"installed": {}, "seen": {}}):
            ricaricato = catalog.carica_ultimo()
        self.assertEqual([p["repo"] for p in ricaricato["projects"]], ["A", "B"])
        self.assertEqual(ricaricato["checked_at"], "2026-09-26T08:00:00+00:00")
        self.assertEqual(ricaricato["error"], "")

    def test_le_copertine_non_finiscono_nel_json(self):
        # Sono gia' su disco come immagini: dentro il JSON peserebbero dieci
        # volte, e con cinquanta traduzioni il file diventerebbe enorme.
        catalog.salva_ultimo({"projects": [_progetto("A")]})
        testo = (self.cartella / catalog.ULTIMO).read_text(encoding="utf-8")
        self.assertNotIn("base64", testo)

    def test_le_copertine_tornano_dal_disco(self):
        (self.cartella / "A.jpg").write_bytes(b"\xff\xd8finto")
        catalog.salva_ultimo({"projects": [_progetto("A"), _progetto("B")]})
        with mock.patch.object(catalog.state, "load", return_value={"installed": {}, "seen": {}}):
            ricaricato = catalog.carica_ultimo()
        copertine = {p["repo"]: p["cover"] for p in ricaricato["projects"]}
        self.assertTrue(copertine["A"].startswith("data:image"))
        self.assertEqual(copertine["B"], "")  # nessun file: nessuna immagine

    def test_lo_stato_locale_si_rilegge(self):
        # Fra una sessione e l'altra si puo' aver installato qualcosa: il
        # catalogo salvato non deve riportare indietro lo stato.
        catalog.salva_ultimo({"projects": [_progetto("A")]})
        locale = {"installed": {"A": {"tag": "v1"}}, "seen": {"A": "v1"}}
        with mock.patch.object(catalog.state, "load", return_value=locale):
            ricaricato = catalog.carica_ultimo()
        self.assertEqual(ricaricato["projects"][0]["status"], catalog.STATUS_UP_TO_DATE)

    def test_un_catalogo_vuoto_non_sovrascrive_quello_buono(self):
        catalog.salva_ultimo({"projects": [_progetto("A")]})
        catalog.salva_ultimo({"projects": []})
        with mock.patch.object(catalog.state, "load", return_value={"installed": {}, "seen": {}}):
            self.assertEqual(len(catalog.carica_ultimo()["projects"]), 1)

    def test_file_assente_o_rovinato(self):
        self.assertIsNone(catalog.carica_ultimo())
        (self.cartella / catalog.ULTIMO).write_text("{ non e' json", encoding="utf-8")
        self.assertIsNone(catalog.carica_ultimo())
        (self.cartella / catalog.ULTIMO).write_text(json.dumps({"projects": "no"}), encoding="utf-8")
        self.assertIsNone(catalog.carica_ultimo())


class TraduzioniMancanti(unittest.TestCase):
    def test_chi_non_si_e_potuto_ricontrollare_resta(self):
        vecchio = {"projects": [_progetto("A"), _progetto("B"), _progetto("C")]}
        nuovo = {"projects": [_progetto("A", data="2026-09-26T00:00:00Z")], "mancanti": ["B", "C"]}
        unito = catalog.unisci_mancanti(nuovo, vecchio)
        self.assertEqual(sorted(p["repo"] for p in unito["projects"]), ["A", "B", "C"])
        # La versione nuova di A non viene sostituita da quella vecchia.
        a = next(p for p in unito["projects"] if p["repo"] == "A")
        self.assertEqual(a["latest"]["date"], "2026-09-26T00:00:00Z")

    def test_senza_mancanti_non_tocca_niente(self):
        nuovo = {"projects": [_progetto("A")]}
        self.assertIs(catalog.unisci_mancanti(nuovo, {"projects": [_progetto("B")]}), nuovo)

    def test_senza_catalogo_precedente(self):
        nuovo = {"projects": [_progetto("A")], "mancanti": ["B"]}
        self.assertEqual(len(catalog.unisci_mancanti(nuovo, None)["projects"]), 1)

    def test_il_limite_a_meta_giro_si_dichiara(self):
        # Era il caso delle "1 traduzione su 5": il limite scattava mentre si
        # costruivano i progetti, e quelli rimasti fuori sparivano in silenzio.
        voci = [{"repo": {"name": n}, "marker": {}} for n in ("A", "B")]

        def costruisci(client, voce, *a, **k):
            if voce["repo"]["name"] == "B":
                raise catalog.RateLimited(0)
            return _progetto("A")

        with mock.patch.object(catalog, "discover", return_value=voci), \
             mock.patch.object(catalog, "_build_project", side_effect=costruisci), \
             mock.patch.object(catalog, "fetch_proposals", return_value=[]):
            esito = catalog.build(
                mock.Mock(rate_remaining=0), fetch_covers=False,
                scan_library=False, use_feed=False,
            )
        self.assertEqual(esito["mancanti"], ["B"])
        self.assertEqual(esito["error"], "rate_limit")


class CioCheArrivaAllaFinestra(unittest.TestCase):
    def _api(self, progetti, proposte=()):
        finta = api.Api.__new__(api.Api)
        finta._catalog = {"projects": progetti, "proposals": list(proposte), "error": ""}
        finta._checked_at = "2026-09-26T08:00:00+00:00"
        finta._hub_update = None
        finta.auth_state = mock.Mock(return_value={})
        return finta

    def test_le_proposte_arrivano_davvero(self):
        # Il pacchetto di prima non le conteneva: la bacheca "Cosa vorrebbe
        # la comunita'" non poteva mostrare nemmeno una proposta, e non ce ne
        # si accorgeva perche' l'anteprima le iniettava per conto suo.
        proposta = {"number": 7, "title": "[Proposta] Elden Ring", "votes": 3}
        pacchetto = self._api([_progetto("A")], [proposta])._pacchetto()
        self.assertEqual(pacchetto["proposals"], [proposta])

    def test_il_pacchetto_ha_tutto_quello_che_la_finestra_legge(self):
        pacchetto = self._api([_progetto("A")])._pacchetto()
        for chiave in ("projects", "summary", "library", "proposals", "error",
                       "rate_remaining", "checked_at", "hub_update", "source", "auth"):
            self.assertIn(chiave, pacchetto)


class ControlloFallito(unittest.TestCase):
    """GitHub non risponde: la griglia resta com'era, cambia solo l'avviso."""

    def _api_con_catalogo(self):
        finta = api.Api.__new__(api.Api)
        finta._catalog = {"projects": [_progetto("A"), _progetto("B")], "error": ""}
        finta._checked_at = ""
        finta._hub_update = None
        finta._update_checked = True
        finta._tentativi = 0
        finta._busy = False
        finta._lock = api.threading.Lock()
        finta._last_refresh = 0.0
        finta._account = None
        finta._client = mock.Mock(token_revocato=False, rate_remaining=None)
        finta.log = mock.Mock()
        finta._emit = mock.Mock()
        finta._status = mock.Mock()
        finta._riprova_da_solo = mock.Mock()
        finta.auth_state = mock.Mock(return_value={})
        return finta

    def _giro(self, finta, esito):
        with mock.patch.object(api.catalog, "build", return_value=esito), \
             mock.patch.object(api.catalog, "salva_ultimo") as salva, \
             mock.patch.object(api.state, "load", return_value={"seen": {"A": "v1"}}), \
             mock.patch.object(api.threading, "Thread") as filo:
            filo.side_effect = lambda target, daemon: mock.Mock(start=target)
            finta.refresh(force=True, silent=True)
        return salva

    def test_senza_rete_la_griglia_non_si_svuota(self):
        finta = self._api_con_catalogo()
        salva = self._giro(finta, {"projects": [], "error": "rete"})

        cataloghi = [c.args[1] for c in finta._emit.call_args_list if c.args[0] == "catalog"]
        self.assertEqual(len(cataloghi), 1)
        self.assertEqual([p["repo"] for p in cataloghi[0]["projects"]], ["A", "B"])
        self.assertEqual(cataloghi[0]["error"], "rete")
        # Il catalogo buono resta quello di prima, su disco e in memoria.
        salva.assert_not_called()
        self.assertEqual(len(finta._catalog["projects"]), 2)
        finta._riprova_da_solo.assert_called_once()

    def test_col_limite_esaurito_non_riprova_a_raffica(self):
        finta = self._api_con_catalogo()
        self._giro(finta, {"projects": [], "error": "rate_limit"})
        finta._riprova_da_solo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
