"""Autorização do Mercado Livre feita dentro do app (substitui auth_ml.py)."""
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
import keyring
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import ml_auth, segredos  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.server import create_app  # noqa: E402
from tests.test_segredos import CofreFalso  # noqa: E402


class FuncoesTests(unittest.TestCase):
    def test_url_de_autorizacao(self):
        u = ml_auth.url_autorizacao("123", "https://www.google.com")
        self.assertTrue(u.startswith("https://auth.mercadolivre.com.br/authorization?"))
        self.assertIn("client_id=123", u)
        self.assertIn("redirect_uri=https%3A%2F%2Fwww.google.com", u)

    def test_extrai_codigo_da_url_ou_puro(self):
        self.assertEqual(ml_auth.extrair_codigo("https://www.google.com/?code=TG-abc&state=1"), "TG-abc")
        self.assertEqual(ml_auth.extrair_codigo("  TG-abc "), "TG-abc")

    def test_troca_codigo_por_token(self):
        def h(req):
            self.assertIn(b"grant_type=authorization_code", req.content)
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "expires_in": 100})
        p = ml_auth.trocar_codigo("1", "s", "https://x", "c", transporte=httpx.MockTransport(h))
        self.assertEqual(p["refresh_token"], "R")

    def test_troca_com_erro_explica(self):
        t = httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "invalid_grant"}))
        with self.assertRaises(ml_auth.AutorizacaoFalhou) as e:
            ml_auth.trocar_codigo("1", "s", "https://x", "c", transporte=t)
        self.assertIn("invalid_grant", str(e.exception))


class RotasTests(unittest.TestCase):
    def setUp(self):
        self.antes = keyring.get_keyring()
        keyring.set_keyring(CofreFalso())
        self.d = tempfile.TemporaryDirectory()
        base = Path(self.d.name)
        self.app = create_app(Settings(base_dir=base, db_path=base / "t.db", windows_on=False))
        self.c = TestClient(self.app)

    def tearDown(self):
        self.app.state.engine.db.conn.close()
        keyring.set_keyring(self.antes)
        self.d.cleanup()

    def test_status_inicial(self):
        r = self.c.get("/api/ml/status").json()
        self.assertEqual((r["tem_credenciais"], r["tem_token"]), (False, False))

    def test_credenciais_vao_para_o_cofre_e_devolvem_url(self):
        r = self.c.post("/api/ml/credenciais", json={"client_id": "99", "client_secret": "seg",
                                                     "redirect_uri": "https://www.google.com"}).json()
        self.assertIn("client_id=99", r["auth_url"])
        self.assertEqual(segredos.ler("ml_client_secret"), "seg")
        self.assertTrue(self.c.get("/api/ml/status").json()["tem_credenciais"])
        self.assertNotIn("seg", self.c.get("/api/ml/status").text)  # o segredo nunca volta pela API

    def test_credenciais_incompletas_dao_400(self):
        r = self.c.post("/api/ml/credenciais", json={"client_id": "99"})
        self.assertEqual(r.status_code, 400)

    def test_autorizar_sem_credenciais_dao_400(self):
        self.assertEqual(self.c.post("/api/ml/autorizar", json={"codigo": "x"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
