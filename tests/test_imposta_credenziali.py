"""Lo strumento che porta le credenziali dentro l'eseguibile.

Esiste per non scriverle in config.py: GitHub fa secret scanning sui repo
pubblici e revoca i client secret che ci trova. Qui si controlla che sappia
leggere quello che l'hub mette negli appunti, in tutte le forme plausibili.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

_spec = importlib.util.spec_from_file_location(
    "imposta_credenziali", RADICE / "tools" / "imposta_credenziali.py"
)
strumento = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(strumento)

ID = "Ov23liABCDEFGHIJKLMN"
SECRET = "a1b2c3d4" + "e" * 32


class Lettura(unittest.TestCase):
    def test_le_righe_copiate_dall_hub(self):
        testo = f'OAUTH_CLIENT_ID = "{ID}"\nOAUTH_CLIENT_SECRET = "{SECRET}"'
        self.assertEqual(strumento.estrai(testo), (ID, SECRET))

    def test_con_ritorni_a_capo_di_windows(self):
        testo = f'OAUTH_CLIENT_ID = "{ID}"\r\nOAUTH_CLIENT_SECRET = "{SECRET}"\r\n'
        self.assertEqual(strumento.estrai(testo), (ID, SECRET))

    def test_anche_con_apici_singoli_o_rientri(self):
        testo = f"  OAUTH_CLIENT_ID = '{ID}'\n  OAUTH_CLIENT_SECRET = '{SECRET}'"
        self.assertEqual(strumento.estrai(testo), (ID, SECRET))

    def test_due_stringhe_nude_una_per_riga(self):
        # Chi copia a mano dalla pagina di GitHub ottiene questo.
        self.assertEqual(strumento.estrai(f"{ID}\n{SECRET}\n"), (ID, SECRET))

    def test_nude_e_invertite_vengono_rimesse_a_posto(self):
        self.assertEqual(strumento.estrai(f"{SECRET}\n{ID}"), (ID, SECRET))

    def test_appunti_vuoti_o_con_una_sola_riga(self):
        self.assertIsNone(strumento.estrai(""))
        self.assertIsNone(strumento.estrai("   \n\n"))
        self.assertIsNone(strumento.estrai(ID))


class Mascheramento(unittest.TestCase):
    """Il secret non deve comparire nemmeno sul terminale dell'autore."""

    def test_restano_solo_le_estremita(self):
        mascherato = strumento.maschera(SECRET)
        self.assertNotIn(SECRET, mascherato)
        self.assertEqual(len(mascherato), len(SECRET))
        self.assertTrue(mascherato.startswith(SECRET[:6]))
        self.assertTrue(mascherato.endswith(SECRET[-4:]))

    def test_un_valore_corto_sparisce_del_tutto(self):
        self.assertEqual(strumento.maschera("segreto"), "*******")


class FileGenerato(unittest.TestCase):
    def test_e_python_valido_e_non_versionato(self):
        testo = strumento.INTESTAZIONE.format(cid=ID, secret=SECRET)
        spazio: dict = {}
        exec(compile(testo, "credenziali.py", "exec"), spazio)
        self.assertEqual(spazio["OAUTH_CLIENT_ID"], ID)
        self.assertEqual(spazio["OAUTH_CLIENT_SECRET"], SECRET)

        ignorati = (RADICE / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("hub/credenziali.py", ignorati)

    def test_config_py_non_contiene_credenziali_scritte_a_mano(self):
        # La rete di sicurezza vera: se un domani qualcuno le incollasse li',
        # questo test lo direbbe prima del commit.
        testo = (RADICE / "hub" / "config.py").read_text(encoding="utf-8")
        self.assertIn('OAUTH_CLIENT_ID = ""', testo)
        self.assertIn('OAUTH_CLIENT_SECRET = ""', testo)


if __name__ == "__main__":
    unittest.main()
