"""Verificação de versão nova (arquivo JSON publicado por você)."""
import sys
import unittest
from pathlib import Path

import httpx
from starlette.testclient import TestClient
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import atualizacao  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.server import create_app  # noqa: E402


def t(json=None, status=200, erro=False):
    def h(req):
        if erro:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(status, json=json)
    return httpx.MockTransport(h)


class AtualizacaoTests(unittest.TestCase):
    def test_versao_nova_disponivel(self):
        r = atualizacao.verificar("https://x/v.json", "1.0.0",
                                  t({"versao": "1.1.0", "url": "https://x/Setup.exe", "notas": "Corrige bugs"}))
        self.assertEqual(r, {"versao": "1.1.0", "url": "https://x/Setup.exe", "notas": "Corrige bugs"})

    def test_compara_numericamente(self):
        self.assertIsNotNone(atualizacao.verificar("https://x", "1.9.0", t({"versao": "1.10.0", "url": "https://x/a"})))

    def test_mesma_versao_ou_mais_antiga_nao_avisa(self):
        self.assertIsNone(atualizacao.verificar("https://x", "1.1.0", t({"versao": "1.1.0", "url": "https://x/a"})))
        self.assertIsNone(atualizacao.verificar("https://x", "1.1.0", t({"versao": "1.0.9", "url": "https://x/a"})))

    def test_sem_internet_ou_json_ruim_ou_sem_url_nao_quebra(self):
        self.assertIsNone(atualizacao.verificar("https://x", "1.0.0", t(erro=True)))
        self.assertIsNone(atualizacao.verificar("https://x", "1.0.0", t({"lixo": 1})))
        self.assertIsNone(atualizacao.verificar("", "1.0.0"))

    def test_so_aceita_link_https_de_download(self):
        self.assertIsNone(atualizacao.verificar("https://x", "1.0.0", t({"versao": "2.0.0", "url": "http://x/a.exe"})))

    def test_rota(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d)
            app = create_app(Settings(base_dir=b, db_path=b / "t.db", windows_on=False), exigir_licenca=False)
            try:
                r = TestClient(app).get("/api/atualizacao").json()
            finally:
                app.state.engine.db.conn.close()
        self.assertEqual(r["atual"], atualizacao.versao.VERSAO)
        self.assertIsNone(r["nova"])


if __name__ == "__main__":
    unittest.main()
