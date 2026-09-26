"""Regole di riconoscimento dei repo e nomi dei giochi."""

import unittest

from hub import config


def repo(name, **extra):
    base = {"name": name, "topics": [], "fork": False, "archived": False, "private": False}
    base.update(extra)
    return base


class RiconoscimentoRepo(unittest.TestCase):
    def test_hub_json_basta_da_solo(self):
        # Il marcatore e' il criterio piu' forte: vale anche con un nome che
        # non dice nulla, ed e' la via consigliata per i repo futuri.
        self.assertTrue(config.looks_like_translation(repo("un-nome-qualsiasi"), True))

    def test_convenzione_sul_nome(self):
        for nome in (
            "ARK-Survival-Ascended-Italian-Translation",
            "SC-Italian-Translation",
            "Qualcosa-Traduzione-Italiana",
            "Traduzione-Mio-Gioco",
        ):
            with self.subTest(nome=nome):
                self.assertTrue(config.looks_like_translation(repo(nome), False))

    def test_topic_riconosciuto(self):
        self.assertTrue(
            config.looks_like_translation(
                repo("progetto-x", topics=["italian-translation"]), False
            )
        )

    def test_repo_estraneo_escluso(self):
        for nome in ("dotfiles", "sito-personale", "appunti"):
            with self.subTest(nome=nome):
                self.assertFalse(config.looks_like_translation(repo(nome), False))

    def test_repo_profilo_sempre_escluso(self):
        # Il repo che porta il nome dell'account contiene il README del
        # profilo: non e' una traduzione nemmeno se avesse un hub.json.
        self.assertFalse(config.looks_like_translation(repo("Sici29"), True))
        self.assertFalse(config.looks_like_translation(repo("sici29"), True))

    def test_il_repo_dell_hub_non_e_una_traduzione(self):
        # Ospita sito e catalogo, e potrebbe avere topic sulle traduzioni:
        # comparirebbe nell'hub come un gioco.
        self.assertFalse(
            config.looks_like_translation(
                repo(config.FEED_REPO, topics=["italian-translation"]), True
            )
        )

    def test_fork_archiviati_e_privati_esclusi(self):
        nome = "Gioco-Italian-Translation"
        for chiave in ("fork", "archived", "private", "disabled"):
            with self.subTest(chiave=chiave):
                self.assertFalse(
                    config.looks_like_translation(repo(nome, **{chiave: True}), True)
                )

    def test_nome_vuoto(self):
        self.assertFalse(config.looks_like_translation(repo(""), True))


class NomeLeggibile(unittest.TestCase):
    def test_toglie_il_suffisso(self):
        self.assertEqual(
            config.pretty_game_name("Fatekeeper-Italian-Translation"), "Fatekeeper"
        )

    def test_sigle_restano_maiuscole(self):
        # ARK e NTE sono sigle: trasformarle in "Ark" e "Nte" sarebbe sbagliato.
        self.assertEqual(
            config.pretty_game_name("ARK-Survival-Ascended-Italian-Translation"),
            "ARK Survival Ascended",
        )
        self.assertEqual(config.pretty_game_name("NTE-Italian-Translation"), "NTE")

    def test_nome_senza_convenzione(self):
        self.assertEqual(config.pretty_game_name("mio_gioco"), "Mio Gioco")

    def test_non_resta_mai_vuoto(self):
        self.assertTrue(config.pretty_game_name("Italian-Translation"))


class CopertineUfficiali(unittest.TestCase):
    """Per i giochi che su Steam non esistono resta il sito dell'editore."""

    def test_trova_star_citizen(self):
        url = config.official_cover("Star Citizen")
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("https://"))

    def test_confronto_tollerante(self):
        # Il nome arriva dal hub.json o dal nome del repo: maiuscole e
        # punteggiatura non devono far fallire l'abbinamento.
        for scritto in ("star citizen", "STAR CITIZEN", "Star  Citizen", "Star-Citizen"):
            with self.subTest(scritto=scritto):
                self.assertIsNotNone(config.official_cover(scritto))

    def test_gioco_sconosciuto(self):
        self.assertIsNone(config.official_cover("Gioco Che Non Esiste"))
        self.assertIsNone(config.official_cover(""))


if __name__ == "__main__":
    unittest.main()
