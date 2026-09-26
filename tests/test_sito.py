"""Il sito su GitHub Pages e il catalogo che la stessa Action tiene nel repo."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import build_catalog  # noqa: E402
import genera_sito as sito  # noqa: E402


def rilascio(tag, data, nome="Traduzione.exe", peso=12_000_000, scaricati=0, note=""):
    allegato = {
        "name": nome,
        "size": peso,
        "downloads": scaricati,
        "url": f"https://github.com/Sici29/X/releases/download/{tag}/{nome}",
    }
    return {
        "tag": tag,
        "name": tag,
        "date": data,
        "body": note,
        "url": f"https://github.com/Sici29/X/releases/tag/{tag}",
        "prerelease": False,
        "assets": [allegato],
        "download": allegato,
        "downloads": scaricati,
    }


def voce(repo, rilasci, **marker):
    return {
        "repo": {"name": repo, "description": f"Descrizione di {repo}", "html_url": f"https://github.com/Sici29/{repo}"},
        "marker": marker,
        "releases": list(rilasci),
    }


def catalogo(*voci, hub_release=None, proposte=()):
    return {
        "version": 1,
        "generated_at": "2026-09-26T10:00:00Z",
        "entries": list(voci),
        "proposals": list(proposte),
        "hub_release": hub_release or {},
    }


class NoteDiRilascio(unittest.TestCase):
    def test_nessun_tag_arriva_alla_pagina(self):
        html, _ = sito.markdown("Prima riga\n\n<script>alert(1)</script> e <b>grassetto</b>\n- <img src=x>")
        self.assertNotIn("<script", html)
        self.assertNotIn("<b>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_elenchi_annidati(self):
        html, _ = sito.markdown("testo\n\n- uno\n  - uno.a\n  - uno.b\n- due")
        self.assertIn("<ul><li>uno<ul><li>uno.a</li><li>uno.b</li></ul></li><li>due</li></ul>", html)

    def test_il_titolo_iniziale_non_si_ripete(self):
        # La pagina mostra gia' il nome della release: il primo titolo delle
        # note lo ripeterebbe.
        html, _ = sito.markdown("# Aniimo 1.0.3603741.0\n\nAggiornamento completo.\n\n## Novità\n- una")
        self.assertNotIn("3603741", html)
        self.assertIn("<p>Aggiornamento completo.</p>", html)
        self.assertIn("<h4>Novità</h4>", html)

    def test_note_lunghe_accorciate(self):
        note = "introduzione\n\n" + "\n".join(f"- voce {i}" for i in range(30))
        html, tagliato = sito.markdown(note, max_blocchi=5)
        self.assertTrue(tagliato)
        self.assertEqual(html.count("<li>"), 4)

    def test_note_corte_intere(self):
        _, tagliato = sito.markdown("testo\n\n- una\n- due", max_blocchi=5)
        self.assertFalse(tagliato)

    def test_solo_link_web(self):
        html, _ = sito.markdown("x\n\n[buono](https://github.com/Sici29) e [cattivo](javascript:alert(1))")
        self.assertIn('href="https://github.com/Sici29"', html)
        self.assertNotIn('href="javascript', html)

    def test_il_codice_resta_codice(self):
        html, _ = sito.markdown("x\n\nfile `pakchunk*_P.pak` e *corsivo* e **grassetto**")
        self.assertIn("<code>pakchunk*_P.pak</code>", html)
        self.assertIn("<em>corsivo</em>", html)
        self.assertIn("<strong>grassetto</strong>", html)

    def test_tabelle_e_blocchi_di_codice_saltati(self):
        note = "x\n\n| File | SHA |\n| --- | --- |\n| a | b |\n\n```text\nC:\\Giochi\n```\nfine"
        html, _ = sito.markdown(note)
        self.assertNotIn("SHA", html)
        self.assertNotIn("Giochi", html)
        self.assertIn("fine", html)


class NomiNumeriEDate(unittest.TestCase):
    def test_cartelle_delle_pagine(self):
        self.assertEqual(sito.slug("ARK: Survival Ascended"), "ark-survival-ascended")
        self.assertEqual(sito.slug("Città Perduta"), "citta-perduta")
        self.assertEqual(sito.slug("Neverness to Everness"), "neverness-to-everness")

    def test_date_all_italiana(self):
        self.assertEqual(sito.data_it("2026-09-01T10:00:00Z"), "1 settembre 2026")
        self.assertEqual(sito.data_it("non una data"), "")

    def test_pesi(self):
        self.assertEqual(sito.peso(42_919_319), "43 MB")
        self.assertEqual(sito.peso(7_752_041), "7,8 MB")

    def test_download_arrotondati(self):
        # Il catalogo conta solo le release recenti: meglio "oltre" che un
        # numero preciso e sbagliato.
        self.assertEqual(sito.arrotonda_download(1060), "oltre 1.000")
        self.assertEqual(sito.arrotonda_download(180), "oltre 150")
        self.assertEqual(sito.arrotonda_download(21), "21")

    def test_proposte_senza_prefisso(self):
        self.assertEqual(sito.senza_prefisso("[Proposta] Dune: Awakening"), "Dune: Awakening")
        self.assertEqual(sito.senza_prefisso("[proposta]  Kingdom Come"), "Kingdom Come")


class Generazione(unittest.TestCase):
    """Il sito intero, senza rete: copertine e Steam restano fuori."""

    EXTRA = {
        "Aniimo-Italian-Translation": {"lingua": "Inglese", "ripristino": "Scrivi 2 e premi Invio."},
    }

    def setUp(self):
        self.uscita = Path(tempfile.mkdtemp()) / "sito"
        patch = [
            mock.patch.object(sito, "arricchisci", lambda giochi, cartella: None),
            mock.patch.object(sito, "carica_extra", lambda: dict(self.EXTRA)),
        ]
        for p in patch:
            p.start()
            self.addCleanup(p.stop)

    def dati(self, **kw):
        return catalogo(
            voce(
                "Aniimo-Italian-Translation",
                [rilascio("v2", "2026-09-26T07:00:00Z", scaricati=900), rilascio("v1", "2026-09-20T07:00:00Z", scaricati=300)],
                nome_gioco="Aniimo",
                steam_appid=4126040,
            ),
            voce("SC-Italian-Translation", [rilascio("sc-4.10", "2026-09-17T15:00:00Z")], nome_gioco="Star Citizen", steam_appid=None),
            voce("Vuota-Italian-Translation", []),
            **kw,
        )

    def leggi(self, percorso):
        return (self.uscita / percorso).read_text(encoding="utf-8")

    def test_una_pagina_per_ogni_traduzione_con_release(self):
        sito.genera(self.dati(), self.uscita)
        self.assertTrue((self.uscita / "aniimo" / "index.html").exists())
        self.assertTrue((self.uscita / "star-citizen" / "index.html").exists())
        # Senza release non c'e' niente da scaricare, quindi niente pagina.
        self.assertFalse((self.uscita / "vuota").exists())
        indice = self.leggi("index.html")
        self.assertIn('href="aniimo/"', indice)
        self.assertIn('href="star-citizen/"', indice)
        self.assertNotIn("Vuota", indice)

    def test_indirizzi_canonici_e_mappa_per_google(self):
        sito.genera(self.dati(), self.uscita)
        pagina = self.leggi("aniimo/index.html")
        self.assertIn(f'<link rel="canonical" href="{sito.SITO}aniimo/">', pagina)
        self.assertIn("<title>Aniimo in italiano", pagina)
        mappa = self.leggi("sitemap.xml")
        self.assertIn(f"<loc>{sito.SITO}aniimo/</loc><lastmod>2026-09-26</lastmod>", mappa)
        self.assertIn(f"<loc>{sito.SITO}star-citizen/</loc>", mappa)

    def test_il_pulsante_porta_all_ultima_versione(self):
        sito.genera(self.dati(), self.uscita)
        pagina = self.leggi("aniimo/index.html")
        self.assertIn('href="https://github.com/Sici29/X/releases/download/v2/Traduzione.exe"', pagina)
        self.assertIn("Versione v2", pagina)

    def test_istruzioni_dal_file_extra(self):
        sito.genera(self.dati(), self.uscita)
        aniimo = self.leggi("aniimo/index.html")
        self.assertIn("scegli <strong>Inglese</strong>", aniimo)
        self.assertIn("Scrivi 2 e premi Invio.", aniimo)
        # Chi non e' nel file ha comunque istruzioni, generiche.
        sc = self.leggi("star-citizen/index.html")
        self.assertIn("Come si installa", sc)
        self.assertIn("Come tornare al gioco originale", sc)

    def test_l_app_si_nomina_solo_se_e_scaricabile(self):
        sito.genera(self.dati(), self.uscita)
        self.assertNotIn("Scarica Gioca in Italiano", self.leggi("index.html"))

        hub = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/Sici29/gioca-in-italiano/releases/tag/v1.0.0",
            "assets": [{"name": "GiocaInItaliano.exe", "size": 25_000_000,
                        "browser_download_url": "https://example.test/GiocaInItaliano.exe"}],
        }
        sito.genera(self.dati(hub_release=hub), self.uscita)
        indice = self.leggi("index.html")
        self.assertIn("Scarica Gioca in Italiano", indice)
        self.assertIn('href="https://example.test/GiocaInItaliano.exe"', indice)

    def test_i_testi_dal_catalogo_sono_escapati(self):
        dati = catalogo(voce("X-Italian-Translation", [rilascio("v1", "2026-09-01T00:00:00Z")], nome_gioco='Gioco <b>"strano"</b>'))
        sito.genera(dati, self.uscita)
        indice = self.leggi("index.html")
        self.assertNotIn("<b>", indice)
        self.assertIn("&lt;b&gt;", indice)

    def test_file_di_verifica_nella_radice(self):
        # Il file di Google Search Console va servito cosi' com'e', ma non deve
        # poter sostituire una pagina vera.
        sorgenti = Path(tempfile.mkdtemp())
        (sorgenti / "stile.css").write_text("body{}", encoding="utf-8")
        (sorgenti / "radice").mkdir()
        (sorgenti / "radice" / "google123abc.html").write_text("google-site-verification", encoding="utf-8")
        (sorgenti / "radice" / "index.html").write_text("intruso", encoding="utf-8")
        with mock.patch.object(sito, "SORGENTI", sorgenti):
            sito.genera(self.dati(), self.uscita)
        self.assertEqual(self.leggi("google123abc.html"), "google-site-verification")
        self.assertNotEqual(self.leggi("index.html"), "intruso")

    def test_l_impronta_cambia_solo_se_cambia_il_sito(self):
        sito.genera(self.dati(), self.uscita)
        prima = self.leggi("impronta.txt")
        sito.genera(self.dati(), self.uscita)
        self.assertEqual(self.leggi("impronta.txt"), prima)

        dati = self.dati()
        dati["entries"][0]["releases"].insert(0, rilascio("v3", "2026-09-27T07:00:00Z"))
        sito.genera(dati, self.uscita)
        self.assertNotEqual(self.leggi("impronta.txt"), prima)


class CatalogoNelRepo(unittest.TestCase):
    """Il commit di catalog.json solo quando serve, non a ogni giro."""

    def catalogo(self, ore_fa=1, scaricati=10, rilasci=("v1",)):
        quando = (datetime.now(timezone.utc) - timedelta(hours=ore_fa)).isoformat()
        dati = catalogo(voce("A-Italian-Translation", [rilascio(t, "2026-09-01T00:00:00Z", scaricati=scaricati) for t in rilasci]))
        dati["generated_at"] = quando
        return dati

    def test_primo_giro(self):
        self.assertTrue(build_catalog.da_riscrivere(None, self.catalogo()))

    def test_data_e_download_non_bastano(self):
        vecchio = self.catalogo(ore_fa=2, scaricati=10)
        nuovo = self.catalogo(ore_fa=0, scaricati=500)
        self.assertFalse(build_catalog.da_riscrivere(vecchio, nuovo))

    def test_una_release_nuova_si(self):
        vecchio = self.catalogo(ore_fa=2)
        nuovo = self.catalogo(ore_fa=0, rilasci=("v2", "v1"))
        self.assertTrue(build_catalog.da_riscrivere(vecchio, nuovo))

    def test_una_volta_al_giorno_comunque(self):
        # L'hub scarta i cataloghi di oltre 36 ore: la data va rinfrescata.
        vecchio = self.catalogo(ore_fa=25)
        self.assertTrue(build_catalog.da_riscrivere(vecchio, self.catalogo(ore_fa=0)))

    def test_non_tocca_l_originale(self):
        dati = self.catalogo()
        prima = json.dumps(dati, sort_keys=True)
        build_catalog._significativo(dati)
        self.assertEqual(json.dumps(dati, sort_keys=True), prima)


if __name__ == "__main__":
    unittest.main()
