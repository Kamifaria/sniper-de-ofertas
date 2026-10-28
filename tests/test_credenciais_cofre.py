"""Config e token do ML lidos/gravados no cofre quando não estão em arquivo."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import keyring

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config, segredos  # noqa: E402
from sniper.collectors.mercadolivre import TokenStore  # noqa: E402
from tests.test_segredos import CofreFalso  # noqa: E402


class CofreBase(unittest.TestCase):
    def setUp(self):
        self.antes = keyring.get_keyring()
        keyring.set_keyring(CofreFalso())
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        keyring.set_keyring(self.antes)


class ConfigTests(CofreBase):
    def _cfg(self, texto):
        p = self.tmp / "config.toml"
        p.write_text(texto, encoding="utf-8")
        return config.load(p)

    def test_secret_vazio_no_arquivo_vem_do_cofre(self):
        segredos.guardar("ml_client_secret", "do-cofre")
        segredos.guardar("telegram_bot_token", "tg-cofre")
        s = self._cfg('[mercadolivre]\nclient_id = "1"\nclient_secret = ""\n[telegram]\nbot_token = ""\n')
        self.assertEqual(s.ml_client_secret, "do-cofre")
        self.assertEqual(s.telegram_token, "tg-cofre")

    def test_valor_no_arquivo_continua_valendo(self):
        segredos.guardar("ml_client_secret", "do-cofre")
        s = self._cfg('[mercadolivre]\nclient_id = "1"\nclient_secret = "do-arquivo"\n')
        self.assertEqual(s.ml_client_secret, "do-arquivo")


class TokenCofreTests(CofreBase):
    def test_salva_token_no_cofre_e_nao_em_arquivo(self):
        arq = self.tmp / "ml_token.json"
        t = TokenStore(arq, "id", "sec", cofre=True)
        t.save({"access_token": "A", "refresh_token": "R", "expires_in": 3600})
        self.assertFalse(arq.exists())
        t2 = TokenStore(arq, "id", "sec", cofre=True)
        self.assertEqual(t2.data["refresh_token"], "R")
        self.assertTrue(t2.has_token)
        self.assertGreater(t2.data["expires_at"], time.time())

    def test_sem_cofre_continua_em_arquivo(self):
        arq = self.tmp / "ml_token.json"
        TokenStore(arq, "id", "sec").save({"access_token": "A", "refresh_token": "R"})
        self.assertEqual(json.loads(arq.read_text())["refresh_token"], "R")


if __name__ == "__main__":
    unittest.main()
