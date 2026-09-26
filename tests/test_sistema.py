"""Libreria locale, stato su disco e trattamento delle immagini."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from hub import config, covers, scan, state


class LibreriaLocale(unittest.TestCase):
    def _risultato(self, giochi):
        by_appid = {g["appid"]: g for g in giochi if g.get("appid")}
        by_name = {scan.norm(g["name"]): g for g in giochi}
        return {"games": giochi, "by_appid": by_appid, "by_name": by_name}

    def test_abbina_per_appid(self):
        r = self._risultato([{"name": "Qualsiasi Nome", "appid": 2399830, "path": "p", "source": "Steam"}])
        trovato = scan.match(r, "ARK: Survival Ascended", 2399830)
        self.assertIsNotNone(trovato)
        self.assertEqual(trovato["path"], "p")

    def test_abbina_per_nome_senza_appid(self):
        r = self._risultato([{"name": "Fatekeeper", "appid": None, "path": "p", "source": "GOG"}])
        self.assertIsNotNone(scan.match(r, "Fatekeeper", None))

    def test_percorso_vero_batte_voce_vuota(self):
        # Il registro elenca "RSI Launcher" senza percorso; la cartella trovata
        # su disco deve avere la precedenza nell'indice per nome.
        giochi = [
            {"name": "Star Citizen", "appid": None, "path": "", "source": "Windows"},
            {"name": "Star Citizen", "appid": None, "path": "D:\SC\LIVE", "source": "RSI Launcher"},
        ]
        by_name = {}
        for g in giochi:
            key = scan.norm(g["name"])
            forte = g["source"] == scan.SOURCE_STEAM or g.get("path")
            if key and (key not in by_name or forte):
                by_name[key] = g
        self.assertEqual(by_name["star citizen"]["source"], "RSI Launcher")

    def test_nome_contenuto(self):
        # Il launcher RSI si registra come "RSI Launcher - Star Citizen".
        r = self._risultato([{"name": "RSI Launcher - Star Citizen", "appid": None, "path": "p", "source": "Windows"}])
        self.assertIsNotNone(scan.match(r, "Star Citizen", None))

    def test_non_abbina_nomi_corti_a_caso(self):
        # Con nomi brevissimi il contenimento darebbe falsi positivi.
        r = self._risultato([{"name": "Steam", "appid": None, "path": "p", "source": "Windows"}])
        self.assertIsNone(scan.match(r, "Tea", None))

    def test_nessuna_corrispondenza(self):
        r = self._risultato([{"name": "Altro Gioco", "appid": 1, "path": "p", "source": "Steam"}])
        self.assertIsNone(scan.match(r, "Fatekeeper", 2186990))

    def test_normalizzazione(self):
        self.assertEqual(scan.norm("ARK: Survival Ascended!"), "ark survival ascended")
        self.assertEqual(scan.norm(""), "")


class GiochiFuoriDagliStore(unittest.TestCase):
    """Star Citizen e simili: non stanno in nessuno store e il registro
    elenca solo il launcher, senza percorso. Vanno cercati su disco."""

    def _finta_installazione(self, nome_cartella="StarCitizen", canale="LIVE"):
        radice = Path(tempfile.mkdtemp())
        exe = radice / nome_cartella / canale / "Bin64" / "StarCitizen.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"finto eseguibile")
        return radice, exe.parent.parent

    def test_verifica_trova_il_canale(self):
        radice, canale = self._finta_installazione()
        voce = scan.STANDALONE[0]
        self.assertEqual(scan._verifica(voce, radice / "StarCitizen"), str(canale))

    def test_verifica_rifiuta_una_cartella_vuota(self):
        vuota = Path(tempfile.mkdtemp()) / "StarCitizen"
        vuota.mkdir()
        self.assertIsNone(scan._verifica(scan.STANDALONE[0], vuota))

    def test_percorso_noto_evita_la_scansione(self):
        # Il punto della cache: se il percorso salvato esiste ancora, non si
        # devono riscandire i dischi (costa secondi, non millisecondi).
        _, canale = self._finta_installazione()
        giochi, memoria = scan.standalone_games({"Star Citizen": str(canale)})
        self.assertEqual(len(giochi), 1)
        self.assertEqual(giochi[0]["path"], str(canale))
        self.assertEqual(memoria["Star Citizen"], str(canale))

    def test_percorso_noto_ma_sparito_non_viene_riusato(self):
        finto = str(Path(tempfile.mkdtemp()) / "cartella-che-non-esiste")
        giochi, _ = scan.standalone_games({"Star Citizen": finto})
        self.assertFalse([g for g in giochi if g["path"] == finto])

    def test_cartelle_di_sistema_saltate(self):
        for nome in ("windows", "node_modules", "steamapps", "$recycle.bin"):
            with self.subTest(nome=nome):
                self.assertIn(nome, scan.SKIP_DIRS | {"$recycle.bin"})


class LetturaManifestSteam(unittest.TestCase):
    ACF = '''"AppState"
{
	"appid"		"2399830"
	"name"		"ARK: Survival Ascended"
	"installdir"		"ARK Survival Ascended"
}'''

    def test_estrae_i_campi(self):
        self.assertEqual(scan._vdf_value(self.ACF, "appid"), "2399830")
        self.assertEqual(scan._vdf_value(self.ACF, "name"), "ARK: Survival Ascended")
        self.assertEqual(scan._vdf_value(self.ACF, "installdir"), "ARK Survival Ascended")

    def test_campo_assente(self):
        self.assertIsNone(scan._vdf_value(self.ACF, "inesistente"))


class StatoSuDisco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.precedente = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp

    def tearDown(self):
        if self.precedente is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.precedente

    def test_stato_iniziale_completo(self):
        s = state.load()
        for chiave in ("installed", "seen", "custom_covers", "voted", "window", "settings"):
            self.assertIn(chiave, s)

    def test_salva_e_rilegge(self):
        s = state.load()
        s["installed"]["X"] = {"tag": "v1"}
        state.save(s)
        self.assertEqual(state.load()["installed"]["X"]["tag"], "v1")

    def test_chiavi_nuove_aggiunte_a_uno_stato_vecchio(self):
        # Chi aggiorna l'hub ha uno state.json senza i campi introdotti dopo:
        # devono comparire con il valore predefinito, non far saltare tutto.
        from hub import paths

        paths.state_file().write_text(json.dumps({"installed": {"A": {"tag": "v0"}}}), encoding="utf-8")
        s = state.load()
        self.assertEqual(s["installed"]["A"]["tag"], "v0")
        self.assertEqual(s["voted"], {})
        self.assertIn("notify", s["settings"])

    def test_file_corrotto_non_fa_crashare(self):
        from hub import paths

        paths.state_file().write_text("{non sono json", encoding="utf-8")
        self.assertEqual(state.load()["installed"], {})


class CacheGitHubFraThread(unittest.TestCase):
    """Il catalogo costruisce i progetti in parallelo e tutti scrivono nella
    stessa cache. Senza protezione json.dump falliva con "dictionary changed
    size during iteration", e la traduzione del thread perdente spariva dalla
    griglia senza lasciare traccia."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.precedente = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp

    def tearDown(self):
        if self.precedente is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.precedente

    def test_scritture_concorrenti_non_falliscono(self):
        import threading

        from hub.ghclient import GitHubClient

        client = GitHubClient()
        errori = []

        def lavora(inizio: int) -> None:
            try:
                for i in range(inizio, inizio + 150):
                    with client._cache_lock:
                        client._cache[f"https://esempio/{i}"] = {
                            "etag": f"e{i}",
                            "data": {"n": i},
                            "ts": i,
                        }
                    client._save_cache()
            except Exception as exc:  # noqa: BLE001
                errori.append(exc)

        thread = [threading.Thread(target=lavora, args=(n * 1000,)) for n in range(6)]
        for t in thread:
            t.start()
        for t in thread:
            t.join()

        self.assertEqual(errori, [], f"scritture concorrenti fallite: {errori}")
        self.assertEqual(len(client._cache), 900)

        # E il file salvato deve restare JSON valido, non troncato a meta'.
        riletto = GitHubClient()
        self.assertEqual(len(riletto._cache), 900)


class Immagini(unittest.TestCase):
    def _png(self, size=(600, 300), alpha=0):
        img = Image.new("RGBA", size, (0, 0, 0, alpha))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def test_riconosce_un_logo_trasparente(self):
        # Il file ufficiale di Star Citizen e' per il 90% trasparente: va
        # trattato come marchio, non come copertina.
        self.assertGreater(covers.transparency_ratio(self._png(alpha=0)), 0.8)

    def test_una_foto_opaca_non_e_un_logo(self):
        self.assertLess(covers.transparency_ratio(self._png(alpha=255)), 0.2)

    def test_immagine_illeggibile(self):
        self.assertEqual(covers.transparency_ratio(b"non sono un png"), 0.0)

    def test_la_trasparenza_non_diventa_nera(self):
        # Il bug trovato con il logo di Star Citizen: convertendo RGBA in RGB
        # i pixel trasparenti diventavano neri, e il marchio nero spariva.
        immagine = Image.new("RGBA", (600, 300), (255, 255, 255, 0))
        buf = io.BytesIO()
        immagine.save(buf, "PNG")

        dest = Path(tempfile.mkdtemp()) / "out.jpg"
        self.assertTrue(covers._normalise(buf.getvalue(), dest))

        with Image.open(dest) as aperta:
            risultato = aperta.convert("RGB")
        self.assertEqual(risultato.size, config.COVER_SIZE)
        # Il fondo deve essere quello scuro dell'interfaccia, non nero pieno.
        self.assertGreater(sum(risultato.getpixel((5, 5))), 10)

    def test_normalizza_a_misura_fissa(self):
        for size in ((1920, 620), (600, 900), (231, 87)):
            with self.subTest(size=size):
                buf = io.BytesIO()
                Image.new("RGB", size, (100, 120, 140)).save(buf, "PNG")
                dest = Path(tempfile.mkdtemp()) / "out.jpg"
                self.assertTrue(covers._normalise(buf.getvalue(), dest))
                with Image.open(dest) as aperta:
                    self.assertEqual(aperta.size, config.COVER_SIZE)

    def test_copertina_generata_e_stabile(self):
        # Lo stesso gioco deve avere sempre la stessa copertina fra un avvio
        # e l'altro, altrimenti la griglia cambierebbe colore a ogni riavvio.
        self.assertEqual(covers._palette_for("Star Citizen"), covers._palette_for("Star Citizen"))

    def test_copertina_generata_si_disegna(self):
        dest = Path(tempfile.mkdtemp()) / "gen.jpg"
        self.assertTrue(covers.generate_cover("Gioco Senza Steam", dest))
        with Image.open(dest) as aperta:
            self.assertEqual(aperta.size, config.COVER_SIZE)


class TintaDellaCopertina(unittest.TestCase):
    """Il colore che ogni gioco presta all'interfaccia.

    Non e' decorazione fine a se stessa: sbagliarlo si vede addosso a tutta
    la card. Le due trappole sono prendere la media dei pixel (viene sempre
    un grigio fango) e lasciar vincere il nero di sfondo, che su una copertina
    di gioco e' quasi sempre il colore piu' esteso.
    """

    def _immagine(self, colori, dimensione=(64, 32)):
        """Immagine a bande verticali, una per colore."""
        img = Image.new("RGB", dimensione)
        larghezza = dimensione[0] // len(colori)
        for i, colore in enumerate(colori):
            banda = Image.new("RGB", (larghezza, dimensione[1]), colore)
            img.paste(banda, (i * larghezza, 0))
        percorso = Path(self.tmp.name) / f"{abs(hash(tuple(colori)))}.jpg"
        img.save(percorso, "JPEG", quality=95)
        return percorso

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        covers._TINTE.clear()

    def test_un_colore_solo_torna_quel_colore(self):
        tinta = covers.tinta(self._immagine([(40, 110, 200)]))
        r, g, b = (int(tinta[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(b, r)
        self.assertGreater(b, g)

    def test_il_nero_di_sfondo_non_vince(self):
        # Tre quarti neri e un quarto rosso: la tinta deve essere il rosso.
        tinta = covers.tinta(
            self._immagine([(0, 0, 0), (0, 0, 0), (0, 0, 0), (210, 40, 40)])
        )
        r, g, b = (int(tinta[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, g + 40)
        self.assertGreater(r, b + 40)

    def test_una_copertina_senza_colore_ripiega_sull_ambra(self):
        grigi = self._immagine([(20, 20, 20), (120, 120, 120), (220, 220, 220)])
        self.assertEqual(covers.tinta(grigi), covers._TINTA_PREDEFINITA)

    def test_senza_file_non_esplode(self):
        self.assertEqual(covers.tinta(None), covers._TINTA_PREDEFINITA)
        self.assertEqual(
            covers.tinta(Path(self.tmp.name) / "non-esiste.jpg"),
            covers._TINTA_PREDEFINITA,
        )

    def test_un_file_che_non_e_un_immagine(self):
        rotto = Path(self.tmp.name) / "rotto.jpg"
        rotto.write_bytes(b"questo non e' un JPEG")
        self.assertEqual(covers.tinta(rotto), covers._TINTA_PREDEFINITA)

    def test_esce_sempre_un_colore_usabile(self):
        # Qualunque immagine entri, il risultato deve essere un esadecimale
        # valido e abbastanza acceso da vedersi sul grafite dell'hub.
        for colori in ([(10, 60, 30)], [(250, 250, 200)], [(90, 10, 120)]):
            with self.subTest(colori=colori):
                tinta = covers.tinta(self._immagine(colori))
                self.assertRegex(tinta, r"^#[0-9a-f]{6}$")
                canali = [int(tinta[i:i + 2], 16) for i in (1, 3, 5)]
                self.assertGreater(max(canali), 90)

    def test_la_cache_non_cresce_all_infinito(self):
        covers._TINTE.clear()
        for n in range(70):
            covers.tinta(self._immagine([(n * 3 % 256, 90, 160)]))
        self.assertLessEqual(len(covers._TINTE), 65)


if __name__ == "__main__":
    unittest.main()
