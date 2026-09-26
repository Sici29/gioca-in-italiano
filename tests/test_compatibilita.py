"""La traduzione copre la versione del gioco installata?

Il rischio di questa funzione non e' sbagliare il calcolo: e' affermare piu'
di quanto si sappia. Un falso "il gioco e' stato aggiornato dopo" fa dubitare
di una traduzione che funziona benissimo, e dopo due volte nessuno guarda piu'
quell'avviso. Meta' di questi test servono proprio a tenere la bocca chiusa
quando i dati non bastano.
"""

import unittest
from datetime import datetime, timedelta, timezone

from hub import compat


def _unix(quando: datetime) -> int:
    return int(quando.timestamp())


ORA = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class SerieDiVersione(unittest.TestCase):
    """Estrazione della "serie", cioe' come la gente chiama una patch."""

    def test_prende_la_prima_coppia(self):
        # Sono le due forme in cui Star Citizen scrive la stessa patch.
        self.assertEqual(compat._serie("sc-alpha-4.10.0"), (4, 10))
        self.assertEqual(compat._serie("4.10.193.11644"), (4, 10))
        self.assertEqual(compat._serie("sc-4.10-r2"), (4, 10))

    def test_niente_da_estrarre(self):
        self.assertIsNone(compat._serie(""))
        self.assertIsNone(compat._serie("stabile"))
        self.assertIsNone(compat._serie(None))


class BuildDichiarata(unittest.TestCase):
    """Il confronto esatto vale solo su una dichiarazione esplicita."""

    def test_legge_il_campo_del_hub_json(self):
        self.assertEqual(compat.build_dichiarata({"game_build": 25525975}), 25525975)
        self.assertEqual(compat.build_dichiarata({"steam_build": "24475133"}), 24475133)

    def test_non_indovina_dal_nome_del_rilascio(self):
        # LA trappola. "supporto Steam build 3595896" e' il numero interno del
        # gioco; Steam per lo stesso gioco scrive 25525975 nell'appmanifest.
        # Confrontarli dava "il gioco e' avanti di ventidue milioni di build".
        self.assertIsNone(compat.build_dichiarata({}))
        self.assertIsNone(compat.build_dichiarata(None))

    def test_valori_senza_senso_vengono_ignorati(self):
        for valore in (0, -3, "", "boh", None, [], {}):
            with self.subTest(valore=valore):
                self.assertIsNone(compat.build_dichiarata({"game_build": valore}))


class ConfrontoDiBuild(unittest.TestCase):
    """Il criterio piu' solido: due numeri della stessa specie."""

    def _valuta(self, build_gioco, build_trad):
        return compat.valuta(
            {"game_build": build_trad}, {"tag": "v1"}, {"build": build_gioco}
        )

    def test_stessa_build(self):
        esito = self._valuta(25525975, 25525975)
        self.assertEqual(esito["stato"], compat.ALLINEATA)
        self.assertEqual(esito["certezza"], compat.ESATTA)

    def test_gioco_piu_avanti(self):
        esito = self._valuta(25525975, 25400000)
        self.assertEqual(esito["stato"], compat.GIOCO_AVANTI)
        self.assertEqual(esito["gioco"], "25525975")
        self.assertEqual(esito["traduzione"], "25400000")

    def test_traduzione_per_una_build_non_ancora_installata(self):
        esito = self._valuta(25400000, 25525975)
        self.assertEqual(esito["stato"], compat.TRADUZIONE_AVANTI)


class ConfrontoDiSerie(unittest.TestCase):
    """Il criterio per i giochi fuori Steam, dove le build non esistono."""

    def _valuta(self, ramo, tag):
        return compat.valuta({}, {"tag": tag}, {"branch": ramo, "version": ramo})

    def test_stessa_serie(self):
        esito = self._valuta("sc-alpha-4.10.0", "sc-4.10-r2")
        self.assertEqual(esito["stato"], compat.ALLINEATA)
        self.assertEqual(esito["certezza"], compat.SERIE)

    def test_gioco_su_una_patch_successiva(self):
        esito = self._valuta("sc-alpha-4.11.0", "sc-4.10-r2")
        self.assertEqual(esito["stato"], compat.GIOCO_AVANTI)

    def test_la_traduzione_anticipa_la_patch(self):
        esito = self._valuta("sc-alpha-4.10.0", "sc-4.11-r1")
        self.assertEqual(esito["stato"], compat.TRADUZIONE_AVANTI)

    def test_le_revisioni_minori_non_contano(self):
        # 4.10.0 e 4.10.2 sono la stessa patch per chi ci gioca: un hotfix
        # non rifa' i testi, e segnalarlo sarebbe un falso allarme.
        esito = self._valuta("sc-alpha-4.10.2", "sc-4.10-r2")
        self.assertEqual(esito["stato"], compat.ALLINEATA)


class ConfrontoPerDate(unittest.TestCase):
    """L'ultima spiaggia, e l'unica che funziona senza dichiarare niente."""

    def _valuta(self, ore_di_scarto):
        aggiornato = ORA + timedelta(hours=ore_di_scarto)
        return compat.valuta(
            {}, {"tag": "v1", "date": ORA.isoformat()}, {"updated": _unix(aggiornato)}
        )

    def test_gioco_aggiornato_molto_dopo(self):
        esito = self._valuta(72)
        self.assertEqual(esito["stato"], compat.GIOCO_AVANTI)
        self.assertEqual(esito["certezza"], compat.INDIZIARIA)
        self.assertEqual(esito["ore"], 72)

    def test_gioco_fermo_da_prima(self):
        esito = self._valuta(-200)
        self.assertEqual(esito["stato"], compat.ALLINEATA)

    def test_poche_ore_di_scarto_non_sono_un_allarme(self):
        # Steam tocca LastUpdated anche per modifiche ai depot che non
        # c'entrano col testo, e la traduzione esce sempre qualche ora dopo
        # la patch che insegue.
        for ore in (1, 6, 23):
            with self.subTest(ore=ore):
                self.assertEqual(self._valuta(ore)["stato"], compat.ALLINEATA)


class QuandoNonSiSaSiTace(unittest.TestCase):
    """Meta' del valore della funzione sta in questi casi."""

    def test_gioco_non_installato(self):
        # Senza il gioco la domanda non si pone nemmeno.
        esito = compat.valuta({"game_build": 100}, {"tag": "v1"}, None)
        self.assertEqual(esito["stato"], compat.IGNOTO)

    def test_nessun_dato_confrontabile(self):
        esito = compat.valuta({}, {"tag": "v1"}, {"path": "C:/Giochi/X"})
        self.assertEqual(esito["stato"], compat.IGNOTO)

    def test_solo_uno_dei_due_dichiara_la_build(self):
        # Build dichiarata dalla traduzione ma gioco non Steam: non si
        # ripiega su un confronto inventato.
        esito = compat.valuta({"game_build": 100}, {"tag": "v1"}, {"path": "C:/X"})
        self.assertEqual(esito["stato"], compat.IGNOTO)

    def test_date_illeggibili(self):
        esito = compat.valuta({}, {"tag": "v1", "date": "domani"}, {"updated": "boh"})
        self.assertEqual(esito["stato"], compat.IGNOTO)

    def test_rilascio_mancante(self):
        esito = compat.valuta({}, None, {"build": 25525975})
        self.assertEqual(esito["stato"], compat.IGNOTO)

    def test_non_solleva_mai(self):
        # Gira su ogni traduzione a ogni ricontrollo: un'eccezione qui
        # svuoterebbe la griglia.
        strani = [None, {}, {"build": "no"}, {"updated": []}, {"branch": 4.10}]
        for gioco in strani:
            with self.subTest(gioco=gioco):
                esito = compat.valuta(None, {"tag": "v1"}, gioco)
                self.assertIn("stato", esito)


class LaPrecedenzaFraICriteri(unittest.TestCase):
    """Quando piu' criteri sono applicabili vince il piu' solido."""

    def test_la_build_batte_le_date(self):
        esito = compat.valuta(
            {"game_build": 500},
            {"tag": "v1", "date": ORA.isoformat()},
            {"build": 500, "updated": _unix(ORA + timedelta(days=30))},
        )
        # Le date direbbero "gioco avanti", la build dice "identica": vince
        # la build, che e' un fatto invece che un indizio.
        self.assertEqual(esito["stato"], compat.ALLINEATA)
        self.assertEqual(esito["certezza"], compat.ESATTA)

    def test_la_serie_batte_le_date(self):
        esito = compat.valuta(
            {},
            {"tag": "sc-4.10-r2", "date": ORA.isoformat()},
            {"branch": "sc-alpha-4.10.0", "updated": _unix(ORA + timedelta(days=30))},
        )
        self.assertEqual(esito["certezza"], compat.SERIE)
        self.assertEqual(esito["stato"], compat.ALLINEATA)


if __name__ == "__main__":
    unittest.main()
