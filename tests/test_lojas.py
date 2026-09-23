"""Registro de lojas, config [lojas.*] e limiter no Mercado Livre."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config  # noqa: E402
from sniper.collectors import CollectorError, MercadoLivreCollector  # noqa: E402
from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.config import LojaConfig, Settings  # noqa: E402
from sniper.engine import Engine  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402


def carregar(texto: str) -> Settings:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text(texto, encoding="utf-8")
        return config.load(p)


class ConfigLojasTests(unittest.TestCase):
    def test_formato_novo(self):
        s = carregar("[lojas.mercadolivre]\nativo = true\npor_minuto = 30\n")
        self.assertEqual(s.lojas["mercadolivre"], LojaConfig(ativo=True, por_minuto=30))

    def test_formato_antigo_com_client_id_liga_o_ml(self):
        s = carregar('[mercadolivre]\nclient_id = "abc"\n')
        self.assertEqual(s.lojas["mercadolivre"], LojaConfig(ativo=True, por_minuto=None))

    def test_sem_nada_nenhuma_loja(self):
        self.assertEqual(carregar("").lojas, {})

    def test_formato_novo_vence_o_antigo(self):
        s = carregar('[lojas.mercadolivre]\nativo = false\n[mercadolivre]\nclient_id = "abc"\n')
        self.assertFalse(s.lojas["mercadolivre"].ativo)


class RegistroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)  # registrado primeiro = roda por último (depois de fechar o banco)
        self.base = Path(self.tmp.name)

    def engine(self, **kw) -> Engine:
        s = Settings(base_dir=self.base, db_path=self.base / "t.db", windows_on=False, **kw)
        eng = Engine(s)
        self.addCleanup(eng.db.conn.close)
        self.addCleanup(lambda: asyncio.run(eng.stop()))
        return eng

    def test_ml_no_registro_e_oficial(self):
        self.assertEqual((LOJAS["mercadolivre"].nome, LOJAS["mercadolivre"].oficial), ("Mercado Livre", True))

    def test_cria_loja_ativa_e_configurada_com_limiter(self):
        eng = self.engine(ml_client_id="id", ml_client_secret="s",
                          lojas={"mercadolivre": LojaConfig(ativo=True, por_minuto=30)})
        col = eng.collectors["mercadolivre"]
        self.assertIsInstance(col, MercadoLivreCollector)
        self.assertIs(col.limiter, eng.limiters["mercadolivre"])
        self.assertEqual(col.limiter.por_minuto, 30)
        self.assertTrue(eng.store_status["mercadolivre"]["configurada"])

    def test_limite_padrao_da_loja(self):
        eng = self.engine(ml_client_id="id", lojas={"mercadolivre": LojaConfig(ativo=True)})
        self.assertEqual(eng.limiters["mercadolivre"].por_minuto, LOJAS["mercadolivre"].por_minuto)

    def test_loja_ativa_sem_credencial(self):
        eng = self.engine(lojas={"mercadolivre": LojaConfig(ativo=True)})
        self.assertNotIn("mercadolivre", eng.collectors)
        self.assertFalse(eng.store_status["mercadolivre"]["configurada"])
        self.assertIn("auth_ml.py", eng.store_status["mercadolivre"]["motivo"])
        self.assertIn("mercadolivre", eng.limiters)

    def test_loja_desligada_nao_cria_nada(self):
        eng = self.engine(ml_client_id="id", lojas={"mercadolivre": LojaConfig(ativo=False)})
        self.assertEqual((eng.collectors, eng.limiters), ({}, {}))
        self.assertIn("desligada", eng._motivo_sem_coletor("mercadolivre"))

    def test_motivo_loja_inexistente_e_nao_configurada(self):
        eng = self.engine()
        self.assertIn("não existe", eng._motivo_sem_coletor("xpto"))
        self.assertIn("auth_ml.py", eng._motivo_sem_coletor("mercadolivre"))


class MLLimiteTests(unittest.TestCase):
    def rodar(self, handler, limiter, chamadas=1):
        async def run():
            with tempfile.TemporaryDirectory() as d:
                tok = Path(d) / "tok.json"
                tok.write_text(json.dumps({"access_token": "OK", "refresh_token": "R",
                                           "expires_at": time.time() + 3600}))
                c = MercadoLivreCollector("id", "secret", tok, limiter=limiter)
                c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

                async def sem_espera(_):
                    return None
                c._sleep = sem_espera
                orig = mlmod.API
                mlmod.API = "https://api.test"
                try:
                    for _ in range(chamadas):
                        await c._get("/sites/MLB/search", {"q": "x"})
                finally:
                    mlmod.API = orig
                    await c.close()
        asyncio.run(run())

    def test_429_persistente_pausa_a_loja(self):
        lim = RateLimiter(60)
        with self.assertRaises(CollectorError):
            self.rodar(lambda req: httpx.Response(429), lim)
        self.assertIsNotNone(lim.estado()["pausada_ate"])
        self.assertEqual(lim.degrau, 1)

    def test_403_pausa_a_loja(self):
        lim = RateLimiter(60)
        with self.assertRaises(CollectorError):
            self.rodar(lambda req: httpx.Response(403, text="forbidden"), lim)
        self.assertTrue(lim.pausada)

    def test_5xx_persistente_da_erro(self):
        lim = RateLimiter(60)
        with self.assertRaises(CollectorError):
            self.rodar(lambda req: httpx.Response(503), lim)
        self.assertFalse(lim.pausada)

    def test_sucesso_zera_degrau_e_conta_consulta(self):
        lim = RateLimiter(60)
        lim.degrau = 2
        self.rodar(lambda req: httpx.Response(200, json={"results": []}), lim, chamadas=2)
        self.assertEqual(lim.degrau, 0)
        self.assertEqual(lim.estado()["ultimo_minuto"], 2)


if __name__ == "__main__":
    unittest.main()
