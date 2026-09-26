"""Catalogo, feed pre-generato e controllo versione dell'hub."""

import json
import unittest
from unittest import mock

from hub import catalog, feed, selfupdate


class SceltaAllegato(unittest.TestCase):
    def test_preferisce_l_installer(self):
        # NTE pubblica sia l'installer sia il .pak grezzo: va scaricato il primo.
        assets = [
            {"name": "pakchunk999.pak", "size": 1, "downloads": 0, "url": "a"},
            {"name": "Installatore.exe", "size": 2, "downloads": 0, "url": "b"},
        ]
        self.assertEqual(catalog._pick_asset(assets)["name"], "Installatore.exe")

    def test_ripiega_sul_primo(self):
        assets = [{"name": "traduzione.zip", "size": 1, "downloads": 0, "url": "a"}]
        self.assertEqual(catalog._pick_asset(assets)["name"], "traduzione.zip")

    def test_nessun_allegato(self):
        self.assertIsNone(catalog._pick_asset([]))


class PuliziaRelease(unittest.TestCase):
    def test_somma_i_download(self):
        grezza = {
            "tag_name": "v1.2",
            "published_at": "2026-09-01T10:00:00Z",
            "assets": [
                {"name": "a.exe", "size": 10, "download_count": 7, "browser_download_url": "u1"},
                {"name": "b.pak", "size": 20, "download_count": 3, "browser_download_url": "u2"},
            ],
        }
        pulita = catalog._clean_release(grezza)
        self.assertEqual(pulita["downloads"], 10)
        self.assertEqual(pulita["tag"], "v1.2")
        self.assertEqual(pulita["download"]["name"], "a.exe")

    def test_release_senza_nome_usa_il_tag(self):
        self.assertEqual(catalog._clean_release({"tag_name": "sc-4.10-r2"})["name"], "sc-4.10-r2")


class Proposte(unittest.TestCase):
    def test_voti_come_differenza_di_reazioni(self):
        issue = {
            "number": 7,
            "title": "[Proposta] Elden Ring",
            "html_url": "u",
            "reactions": {"+1": 40, "-1": 5},
            "comments": 3,
            "labels": [{"name": "proposta"}],
        }
        p = catalog.clean_proposal(issue)
        self.assertEqual(p["votes"], 35)
        self.assertEqual(p["up"], 40)
        self.assertFalse(p["in_lavorazione"])

    def test_etichetta_in_lavorazione(self):
        issue = {"number": 1, "title": "x", "reactions": {}, "labels": [{"name": "in lavorazione"}]}
        self.assertTrue(catalog.clean_proposal(issue)["in_lavorazione"])

    def test_issue_senza_reazioni(self):
        self.assertEqual(catalog.clean_proposal({"number": 1, "title": "x"})["votes"], 0)


class VociNascoste(unittest.TestCase):
    def _local(self, nascosti=()):
        return {"settings": {"hidden_repos": list(nascosti)}}

    def test_nasconde_da_impostazioni(self):
        voci = [{"repo": {"name": "Gioco-Italian-Translation"}, "marker": {}}]
        self.assertEqual(catalog._drop_hidden(voci, self._local(["gioco-italian-translation"])), [])

    def test_nasconde_da_hub_json(self):
        voci = [{"repo": {"name": "X-Italian-Translation"}, "marker": {"nascondi": True}}]
        self.assertEqual(catalog._drop_hidden(voci, self._local()), [])

    def test_tiene_il_resto(self):
        voci = [{"repo": {"name": "X-Italian-Translation"}, "marker": {}}]
        self.assertEqual(len(catalog._drop_hidden(voci, self._local())), 1)


class CatalogoPreGenerato(unittest.TestCase):
    def _risposta(self, payload, status=200):
        finta = mock.Mock()
        finta.status_code = status
        finta.json = mock.Mock(return_value=payload)
        return finta

    def _valido(self, **extra):
        base = {
            "version": feed.FORMAT_VERSION,
            "generated_at": feed.stamp(),
            "entries": [{"repo": {"name": "X-Italian-Translation"}, "marker": {}, "releases": []}],
        }
        base.update(extra)
        return base

    def test_accetta_un_catalogo_valido(self):
        with mock.patch.object(feed.requests, "get", return_value=self._risposta(self._valido())):
            self.assertIsNotNone(feed.fetch())

    def test_rifiuta_un_formato_piu_recente(self):
        # Un hub vecchio non deve provare a interpretare campi che non conosce.
        payload = self._valido(version=feed.FORMAT_VERSION + 1)
        with mock.patch.object(feed.requests, "get", return_value=self._risposta(payload)):
            self.assertIsNone(feed.fetch())

    def test_rifiuta_un_catalogo_scaduto(self):
        payload = self._valido(generated_at="2020-01-01T00:00:00+00:00")
        with mock.patch.object(feed.requests, "get", return_value=self._risposta(payload)):
            self.assertIsNone(feed.fetch())

    def test_rifiuta_un_404(self):
        with mock.patch.object(feed.requests, "get", return_value=self._risposta({}, status=404)):
            self.assertIsNone(feed.fetch())

    def test_rifiuta_senza_voci(self):
        with mock.patch.object(feed.requests, "get", return_value=self._risposta(self._valido(entries=[]))):
            self.assertIsNone(feed.fetch())

    def test_estrae_le_voci(self):
        voci = feed.entries_from(self._valido())
        self.assertEqual(len(voci), 1)
        self.assertIn("releases", voci[0])

    def test_scarta_voci_malformate(self):
        rotto = {"entries": [{"repo": None}, {"nonsense": 1}, {"repo": {"name": ""}}]}
        self.assertEqual(feed.entries_from(rotto), [])


class VersioneHub(unittest.TestCase):
    def test_confronto_numerico(self):
        self.assertTrue(selfupdate.is_newer("1.1.0", "1.0.9"))
        self.assertTrue(selfupdate.is_newer("v2.0.0", "1.9.9"))
        self.assertFalse(selfupdate.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(selfupdate.is_newer("0.9.0", "1.0.0"))

    def test_lunghezze_diverse(self):
        # (1, 1) deve battere (1, 0, 5): senza allineare le lunghezze il
        # confronto fra tuple darebbe il risultato sbagliato.
        self.assertTrue(selfupdate.is_newer("1.1", "1.0.5"))
        self.assertFalse(selfupdate.is_newer("1.0", "1.0.1"))

    def test_versione_illeggibile(self):
        self.assertFalse(selfupdate.is_newer("", "1.0.0"))
        self.assertFalse(selfupdate.is_newer("boh", "1.0.0"))

    def test_estrae_l_eseguibile_dalla_release(self):
        release = {
            "tag_name": "v1.1.0",
            "html_url": "u",
            "assets": [
                {"name": "note.txt", "browser_download_url": "a", "size": 1},
                {"name": "Sici29Hub.exe", "browser_download_url": "b", "size": 999},
            ],
        }
        shaped = selfupdate._shape(release)
        self.assertEqual(shaped["asset"]["name"], "Sici29Hub.exe")
        self.assertEqual(shaped["version"], "v1.1.0")

    def test_release_senza_eseguibile(self):
        shaped = selfupdate._shape({"tag_name": "v1", "assets": [{"name": "x.txt"}]})
        self.assertIsNone(shaped["asset"])


class DopoUnInstallazione(unittest.TestCase):
    """Il caso segnalato: installi, e la card resta com'era.

    L'installazione veniva registrata correttamente sul disco, ma per
    rimandarla alla finestra si chiedeva un giro completo su GitHub - che il
    freno dei dieci minuti rimandava, perche' un controllo era appena
    avvenuto. Risultato: stato giusto sul disco, card sbagliata sullo schermo
    fino alla riapertura dell'hub.

    Il ricalcolo locale non tocca la rete: quello che cambia dopo
    un'installazione sta tutto sul disco di chi usa l'hub.
    """

    def _progetti(self):
        return [
            {
                "repo": "Aniimo-Italian-Translation",
                "latest": {"tag": "v1.0.3595896.0", "date": "2026-09-24T16:53:50Z"},
                "installed_tag": None,
                "installed_at": None,
                "status": catalog.STATUS_NOT_INSTALLED,
                "novita": "aggiornamento",
                "total_downloads": 1040,
                "release_count": 29,
                "installed_game": True,
            }
        ]

    def test_appena_installata_diventa_allineata(self):
        progetti = self._progetti()
        locale = {
            "installed": {
                "Aniimo-Italian-Translation": {
                    "tag": "v1.0.3595896.0",
                    "installed_at": "2026-09-26T07:42:47+00:00",
                }
            },
            "seen": {"Aniimo-Italian-Translation": "v1.0.3595896.0"},
        }
        catalog.ricalcola_stato(progetti, locale)

        self.assertEqual(progetti[0]["status"], catalog.STATUS_UP_TO_DATE)
        self.assertEqual(progetti[0]["installed_tag"], "v1.0.3595896.0")
        self.assertEqual(progetti[0]["installed_at"], "2026-09-26T07:42:47+00:00")
        # Installata l'ultima versione: il badge "novita'" deve sparire.
        self.assertIsNone(progetti[0]["novita"])

    def test_installata_una_versione_vecchia_resta_da_aggiornare(self):
        progetti = self._progetti()
        locale = {
            "installed": {"Aniimo-Italian-Translation": {"tag": "v0.9"}},
            "seen": {"Aniimo-Italian-Translation": "v1.0.3595896.0"},
        }
        catalog.ricalcola_stato(progetti, locale)
        self.assertEqual(progetti[0]["status"], catalog.STATUS_UPDATE)

    def test_dimenticare_l_installazione_torna_indietro(self):
        progetti = self._progetti()
        progetti[0]["status"] = catalog.STATUS_UP_TO_DATE
        progetti[0]["installed_tag"] = "v1.0.3595896.0"
        catalog.ricalcola_stato(progetti, {"installed": {}, "seen": {}})
        self.assertEqual(progetti[0]["status"], catalog.STATUS_NOT_INSTALLED)
        self.assertIsNone(progetti[0]["installed_tag"])

    def test_il_riepilogo_segue(self):
        progetti = self._progetti()
        locale = {
            "installed": {"Aniimo-Italian-Translation": {"tag": "v1.0.3595896.0"}},
            "seen": {"Aniimo-Italian-Translation": "v1.0.3595896.0"},
        }
        catalog.ricalcola_stato(progetti, locale)
        riepilogo = catalog.summary(progetti)
        self.assertEqual(riepilogo["updates"], 0)
        self.assertEqual(riepilogo["installed"], 1)

    def test_non_tocca_la_rete(self):
        # La garanzia che rende sensato chiamarlo a ogni installazione.
        with mock.patch.object(catalog, "GitHubClient", side_effect=AssertionError):
            catalog.ricalcola_stato(self._progetti(), {"installed": {}, "seen": {}})


if __name__ == "__main__":
    unittest.main()
