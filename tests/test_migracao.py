"""Move segredos do config.toml e do ml_token.json para o cofre."""
import sys
import tempfile
import unittest
from pathlib import Path

import keyring

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import migracao, segredos  # noqa: E402
from tests.test_segredos import CofreFalso  # noqa: E402

CFG = '''[mercadolivre]
client_id = "111"   # comentário
client_secret = "SEGREDO"
redirect_uri = "https://www.google.com"
[telegram]
ativo = false
bot_token = "TG:TOKEN"
chat_id = "5"
'''


class MigracaoTests(unittest.TestCase):
    def setUp(self):
        self.antes = keyring.get_keyring()
        keyring.set_keyring(CofreFalso())
        self.d = Path(tempfile.mkdtemp())
        self.cfg = self.d / "config.toml"
        self.cfg.write_text(CFG, encoding="utf-8")
        self.tok = self.d / "data" / "ml_token.json"
        self.tok.parent.mkdir()
        self.tok.write_text('{"access_token": "A", "refresh_token": "R", "expires_at": 1}')

    def tearDown(self):
        keyring.set_keyring(self.antes)

    def test_migra_e_limpa_arquivos(self):
        feito = migracao.migrar(self.cfg, self.tok)
        self.assertEqual(segredos.ler("ml_client_secret"), "SEGREDO")
        self.assertEqual(segredos.ler("telegram_bot_token"), "TG:TOKEN")
        self.assertIn('"refresh_token": "R"', segredos.ler("ml_token"))
        texto = self.cfg.read_text(encoding="utf-8")
        self.assertNotIn("SEGREDO", texto)
        self.assertNotIn("TG:TOKEN", texto)
        self.assertIn('client_id = "111"', texto)      # id não é segredo: fica
        self.assertIn('chat_id = "5"', texto)
        self.assertFalse(self.tok.exists())
        self.assertEqual(len(feito), 3)

    def test_nao_apaga_nada_se_o_cofre_falhar(self):
        class Quebrado(CofreFalso):
            def set_password(self, *a):
                raise keyring.errors.KeyringError("x")
        keyring.set_keyring(Quebrado())
        with self.assertRaises(segredos.CofreIndisponivel):
            migracao.migrar(self.cfg, self.tok)
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), CFG)
        self.assertTrue(self.tok.exists())

    def test_rodar_de_novo_nao_faz_nada(self):
        migracao.migrar(self.cfg, self.tok)
        self.assertEqual(migracao.migrar(self.cfg, self.tok), [])
        self.assertEqual(segredos.ler("ml_client_secret"), "SEGREDO")


if __name__ == "__main__":
    unittest.main()
