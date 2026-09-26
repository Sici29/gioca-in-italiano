"""Abbinamento dei giochi su Steam.

Questi test nascono da due errori veri visti in funzione: "Star Citizen" che
agganciava la copertina di Citizen Sleeper 2, e un AppID scritto a mano nel
hub.json che puntava a un gioco completamente diverso.
"""

import unittest
from unittest import mock

from hub import steam


class ChiaveDiConfronto(unittest.TestCase):
    def test_ignora_punteggiatura_e_maiuscole(self):
        self.assertEqual(steam._key("ARK: Survival Ascended"), steam._key("ark survival ascended"))
        self.assertEqual(steam._key("NTE: Neverness to Everness"), "nte neverness to everness")

    def test_stringa_vuota(self):
        self.assertEqual(steam._key(""), "")
        self.assertEqual(steam._key(None), "")


class PunteggioSomiglianza(unittest.TestCase):
    def test_identico_vince(self):
        self.assertGreater(steam._score("Fatekeeper", "Fatekeeper"), 100)

    def test_citizen_sleeper_non_e_star_citizen(self):
        # Il caso che ha motivato il punteggio: la ricerca di Steam per
        # "Star Citizen" restituisce questi titoli, e nessuno va accettato.
        for falso in (
            "Citizen Sleeper 2: Starward Vector",
            "Citizen Sleeper 2: Starward Vector Soundtrack",
            "Starship Troopers: Extermination - Path to Citizenship MEGA Supporter Pack",
        ):
            with self.subTest(titolo=falso):
                self.assertLess(steam._score(falso, "Star Citizen"), steam.MIN_SCORE)

    def test_gioco_base_batte_il_pacchetto(self):
        base = steam._score("NTE: Neverness to Everness", "Neverness to Everness")
        pacchetto = steam._score("NTE: Neverness to Everness Starter Pack", "Neverness to Everness")
        self.assertGreater(base, pacchetto)
        self.assertGreater(base, steam.MIN_SCORE)

    def test_parole_in_piu_abbassano(self):
        self.assertGreater(
            steam._score("Fatekeeper", "Fatekeeper"),
            steam._score("Fatekeeper Deluxe Edition Bundle", "Fatekeeper"),
        )


class PuliziaNome(unittest.TestCase):
    def test_toglie_parentesi_e_separatori(self):
        self.assertEqual(steam.clean_name("Elden Ring (2022) [GOTY]"), "Elden Ring")
        self.assertEqual(steam.clean_name("ARK: Survival Ascended"), "ARK Survival Ascended")


class RicercaAppId(unittest.TestCase):
    def _risposta(self, items):
        finta = mock.Mock()
        finta.raise_for_status = mock.Mock()
        finta.json = mock.Mock(return_value={"items": items})
        return finta

    def test_accetta_il_match_esatto(self):
        items = [{"id": 2186990, "type": "app", "name": "Fatekeeper"}]
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta(items)
            self.assertEqual(steam.search_appid("Fatekeeper"), 2186990)

    def test_rifiuta_quando_non_somiglia(self):
        # Star Citizen su Steam non esiste: meglio nessun AppID che quello
        # sbagliato, perche' a valle diventerebbe una copertina errata.
        items = [
            {"id": 2442460, "type": "app", "name": "Citizen Sleeper 2: Starward Vector"},
            {"id": 3398420, "type": "app", "name": "Citizen Sleeper 2: Starward Vector Soundtrack"},
        ]
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta(items)
            self.assertIsNone(steam.search_appid("Star Citizen"))

    def test_nessun_risultato(self):
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta([])
            self.assertIsNone(steam.search_appid("Gioco Inesistente"))

    def test_nome_vuoto_non_interroga_la_rete(self):
        with mock.patch.object(steam, "_session") as sess:
            self.assertIsNone(steam.search_appid(""))
            sess.assert_not_called()


class VerificaAppId(unittest.TestCase):
    def test_smaschera_appid_sbagliato(self):
        # 2498620 sullo store si chiama "King Krieg": era l'AppID dichiarato
        # per errore nel hub.json di Fatekeeper.
        with mock.patch.object(steam, "app_details", return_value={"name": "King Krieg", "type": "game"}):
            self.assertIs(steam.verify_appid(2498620, "Fatekeeper"), False)

    def test_conferma_appid_giusto(self):
        with mock.patch.object(steam, "app_details", return_value={"name": "Fatekeeper", "type": "game"}):
            self.assertIs(steam.verify_appid(2186990, "Fatekeeper"), True)

    def test_scheda_non_consultabile_da_il_beneficio_del_dubbio(self):
        # Succede con i titoli molto recenti: non potendo sapere, non si
        # scarta un AppID che potrebbe essere giusto.
        with mock.patch.object(steam, "app_details", return_value=None):
            self.assertIsNone(steam.verify_appid(4508340, "Neverness to Everness"))


class Scaricamento(unittest.TestCase):
    def _risposta(self, status=200, tipo="image/jpeg", contenuto=b"x" * 5000):
        finta = mock.Mock()
        finta.status_code = status
        finta.headers = {"Content-Type": tipo}
        finta.content = contenuto
        return finta

    def test_scarta_i_segnaposto_minuscoli(self):
        # Steam a volte risponde 200 con un'immagine di pochi byte al posto
        # di un 404: va trattata come assente.
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta(contenuto=b"x" * 500)
            self.assertIsNone(steam.download("http://esempio/x.jpg"))

    def test_scarta_cio_che_non_e_immagine(self):
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta(tipo="text/html")
            self.assertIsNone(steam.download("http://esempio/x.jpg"))

    def test_accetta_un_immagine_vera(self):
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self._risposta()
            self.assertEqual(len(steam.download("http://esempio/x.jpg")), 5000)


class SchedaIntestataAltrove(unittest.TestCase):
    """Steam a volte intesta la scheda a un altro numero: visto con ARK e NTE."""

    def risposta(self, payload):
        finta = mock.Mock()
        finta.raise_for_status = mock.Mock()
        finta.json = mock.Mock(return_value=payload)
        return finta

    def setUp(self):
        steam._DETAILS_CACHE.clear()
        self.addCleanup(steam._DETAILS_CACHE.clear)

    def test_conta_l_appid_dentro_la_scheda(self):
        payload = {"4558490": {"success": True, "data": {"steam_appid": 2399830, "name": "ARK: Survival Ascended"}}}
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self.risposta(payload)
            self.assertEqual(steam.app_details(2399830)["name"], "ARK: Survival Ascended")

    def test_una_scheda_di_un_altro_gioco_no(self):
        payload = {"4558490": {"success": True, "data": {"steam_appid": 111, "name": "Altro"}}}
        with mock.patch.object(steam, "_session") as sess:
            sess.return_value.get.return_value = self.risposta(payload)
            self.assertIsNone(steam.app_details(2399830))


if __name__ == "__main__":
    unittest.main()
