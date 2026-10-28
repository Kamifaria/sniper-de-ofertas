"""Licença por chave assinada, revogável online."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import keyring
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import licenca  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.server import create_app  # noqa: E402
from tests.test_segredos import CofreFalso  # noqa: E402

AGORA = datetime(2026, 11, 1, tzinfo=timezone.utc)


def par():
    priv = Ed25519PrivateKey.generate()
    return priv, licenca.publica_b64(priv)


class ChaveTests(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = par()

    def test_chave_valida(self):
        k = licenca.emitir(self.priv, "Maria", 30, agora=AGORA)
        l = licenca.validar(k, self.pub, agora=AGORA)
        self.assertEqual(l.cliente, "Maria")

    def test_vencida(self):
        k = licenca.emitir(self.priv, "Maria", 30, agora=AGORA)
        with self.assertRaises(licenca.LicencaInvalida) as e:
            licenca.validar(k, self.pub, agora=AGORA + timedelta(days=31))
        self.assertIn("venceu", str(e.exception))

    def test_adulterada(self):
        k = licenca.emitir(self.priv, "Maria", 30, agora=AGORA)
        with self.assertRaises(licenca.LicencaInvalida):
            licenca.validar(k[:-3] + "AAA", self.pub, agora=AGORA)

    def test_assinada_por_outra_chave(self):
        outra, _ = par()
        k = licenca.emitir(outra, "Maria", 30, agora=AGORA)
        with self.assertRaises(licenca.LicencaInvalida):
            licenca.validar(k, self.pub, agora=AGORA)

    def test_lixo(self):
        for k in ("", "abc", "SNP-xx.yy"):
            with self.assertRaises(licenca.LicencaInvalida):
                licenca.validar(k, self.pub, agora=AGORA)


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = par()
        self.antes = keyring.get_keyring()
        keyring.set_keyring(CofreFalso())
        self.l = licenca.validar(licenca.emitir(self.priv, "M", 90, agora=AGORA), self.pub, agora=AGORA)

    def tearDown(self):
        keyring.set_keyring(self.antes)

    def _t(self, revogadas):
        return httpx.MockTransport(lambda r: httpx.Response(200, json={"revogadas": revogadas}))

    def test_nao_revogada_passa(self):
        licenca.checar_online(self.l, "https://x/r.json", self._t([]), agora=AGORA)

    def test_revogada_barra(self):
        with self.assertRaises(licenca.LicencaInvalida) as e:
            licenca.checar_online(self.l, "https://x/r.json", self._t([self.l.id]), agora=AGORA)
        self.assertIn("cancelada", str(e.exception))

    def test_sem_internet_tolera_ate_7_dias_da_ultima_checagem(self):
        licenca.checar_online(self.l, "https://x/r.json", self._t([]), agora=AGORA)
        def cai(r): raise httpx.ConnectError("sem rede")
        off = httpx.MockTransport(cai)
        licenca.checar_online(self.l, "https://x/r.json", off, agora=AGORA + timedelta(days=6))
        with self.assertRaises(licenca.LicencaInvalida) as e:
            licenca.checar_online(self.l, "https://x/r.json", off, agora=AGORA + timedelta(days=8))
        self.assertIn("internet", str(e.exception))

    def test_sem_url_nao_checa(self):
        licenca.checar_online(self.l, "", None, agora=AGORA)


class RotasTests(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = par()
        self.antes = keyring.get_keyring()
        keyring.set_keyring(CofreFalso())
        self.d = tempfile.TemporaryDirectory()
        b = Path(self.d.name)
        s = Settings(base_dir=b, db_path=b / "t.db", windows_on=False)
        self.app = create_app(s, exigir_licenca=True, chave_publica=self.pub, url_revogadas="")
        self.c = TestClient(self.app)

    def tearDown(self):
        self.app.state.engine.db.conn.close()
        keyring.set_keyring(self.antes)
        self.d.cleanup()

    def test_sem_licenca_api_bloqueada_e_motor_pausado(self):
        self.assertEqual(self.c.get("/api/alerts").status_code, 402)
        self.assertEqual(self.c.get("/api/licenca/status").json()["ativa"], False)
        self.assertTrue(self.app.state.engine.paused)
        self.assertEqual(self.c.get("/").status_code, 200)  # a tela de ativação precisa abrir

    def test_ativar_com_chave_boa_libera(self):
        k = licenca.emitir(self.priv, "Maria", 30)
        r = self.c.post("/api/licenca/ativar", json={"chave": k}).json()
        self.assertTrue(r["ativa"])
        self.assertEqual(self.c.get("/api/alerts").status_code, 200)
        self.assertFalse(self.app.state.engine.paused)

    def test_ativar_com_chave_ruim_da_mensagem(self):
        r = self.c.post("/api/licenca/ativar", json={"chave": "SNP-ruim"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["erro"])
        self.assertEqual(self.c.get("/api/alerts").status_code, 402)


if __name__ == "__main__":
    unittest.main()
