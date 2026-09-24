"""Testes: python -m unittest discover tests"""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.db import Database  # noqa: E402
from sniper.detector import DetectorConfig, evaluate  # noqa: E402
from sniper import filters  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.collectors.base import Collector  # noqa: E402
from sniper.engine import Engine  # noqa: E402
from sniper.models import Offer, SellerInfo, Watch  # noqa: E402


def offer(price, orig=None, free=False):
    return Offer(store="t", item_id="X1", title="Produto", price=price, url="https://x",
                 original_price=orig, free_shipping=free)


class DetectorTests(unittest.TestCase):
    hist = [1000.0, 1010.0, 990.0, 1005.0, 995.0]

    def test_preco_normal_nao_alerta(self):
        self.assertEqual(evaluate(offer(980), self.hist).level, "NENHUM")

    def test_gratis(self):
        v = evaluate(offer(0.0), self.hist)
        self.assertEqual((v.level, v.score), ("GRATIS", 100))

    def test_virgula_errada_e_critico(self):
        v = evaluate(offer(100.0), self.hist)  # 90% abaixo + queda brusca
        self.assertEqual(v.level, "CRITICO")
        self.assertAlmostEqual(v.drop_pct, 0.9, places=2)

    def test_queda_moderada(self):
        v = evaluate(offer(550.0), self.hist)  # ~45% abaixo + queda brusca
        self.assertIn(v.level, ("MEDIO", "ALTO"))

    def test_desconto_de_por_sozinho_tem_teto(self):
        v = evaluate(offer(100.0, orig=1000.0), [])
        self.assertLessEqual(v.score, 75)

    def test_piso_da_regra(self):
        w = Watch(name="w", store="t", floor=2500)
        v = evaluate(offer(900.0), [], w)
        self.assertGreater(v.score, 0)
        self.assertTrue(any("piso" in r for r in v.reasons))

    def test_item_barato_por_natureza_ignorado(self):
        w = Watch(name="w", store="t", min_price=100)
        self.assertEqual(evaluate(offer(1.5), [30.0, 31.0, 29.0], w).level, "NENHUM")

    def test_config_gratis(self):
        v = evaluate(offer(4.99), self.hist, cfg=DetectorConfig(free_threshold=5))
        self.assertEqual(v.level, "GRATIS")


class PeerTests(unittest.TestCase):
    def test_bug_confirmado_por_concorrentes_sem_historico(self):
        v = evaluate(offer(450.0), [], peers=[4800.0, 4900.0, 5000.0])
        self.assertEqual(v.level, "CRITICO")
        self.assertAlmostEqual(v.ref_price, 4900.0)

    def test_queda_de_mercado_nao_e_bug(self):
        # caiu 45% no histórico, mas todos os concorrentes estão no mesmo preço
        v = evaluate(offer(550.0), [1000.0, 1000.0, 1000.0], peers=[560.0, 545.0, 570.0])
        self.assertEqual(v.level, "NENHUM")
        self.assertTrue(any("Concorrentes já vendem" in r for r in v.reasons))


class FilterTests(unittest.TestCase):
    cfg = filters.FilterConfig()
    w = Watch(name="w", store="t", query="iphone 15")

    def chk(self, title, **kw):
        o = Offer(store="t", item_id="1", title=title, price=10, url="https://x", **{"official_seller": True, **kw})
        return filters.check_listing(o, self.w, self.cfg, blocked={"t:BAD"})

    def test_anuncio_de_teste(self):
        self.assertIn("teste", self.chk("TESTE - NÃO COMPRAR iPhone 15"))
        self.assertIn("nao comprar", self.chk("iPhone 15 Não Comprar"))

    def test_nao_confunde_palavra_parecida(self):
        self.assertIsNone(self.chk("Apple iPhone 15 128GB Testado e Aprovado Lacrado"))

    def test_acessorio(self):
        self.assertIn("Acessório", self.chk("Capinha Silicone iPhone 15"))

    def test_modelo_errado(self):
        self.assertIn("15", self.chk("Apple iPhone 13 128GB"))

    def test_alias_ps5(self):
        w = Watch(name="w", store="t", query="playstation 5")
        o = Offer(store="t", item_id="1", title="Console Sony PS5 Slim 1TB", price=10, url="https://x")
        self.assertIsNone(filters.check_listing(o, w, self.cfg, set()))

    def test_usado_estoque_e_bloqueado(self):
        self.assertEqual(self.chk("Apple iPhone 15", condition="used"), "Produto usado")
        self.assertEqual(self.chk("Apple iPhone 15", available_qty=0), "Sem estoque")
        self.assertIn("bloqueado", self.chk("Apple iPhone 15", seller_id="BAD"))

    def test_vendedor(self):
        c = self.cfg
        self.assertIn("provável teste", filters.check_seller(SellerInfo("1", sales=0, registered_days=900), c))
        self.assertIn("Conta criada", filters.check_seller(SellerInfo("1", sales=500, registered_days=2), c))
        self.assertIsNone(filters.check_seller(SellerInfo("1", sales=500, registered_days=900), c))


class FakeCollector(Collector):
    store = "t"

    def __init__(self):
        self.batch = []
        self.sellers = {"GOOD": SellerInfo("GOOD", "BOA_LOJA", 5000, "5_green", 2000),
                        "NEW": SellerInfo("NEW", "LOJA_TESTE", 0, None, 2)}
        self.fixed_price = None

    async def collect(self, watch):
        return [Offer(**o.__dict__) for o in self.batch]

    async def seller_info(self, o):
        return self.sellers.get(o.seller_id)

    async def confirm(self, o):
        f = Offer(**o.__dict__)
        if self.fixed_price is not None:
            f.price = self.fixed_price
        f.confirmed = True
        return f


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = Settings(base_dir=Path(self.tmp.name), db_path=Path(self.tmp.name) / "t.db", windows_on=False)
        self.w = Watch(name="w", store="t", query="iphone 15")
        s.watches = [self.w]
        self.eng = Engine(s)
        self.col = FakeCollector()
        self.eng.collectors["t"] = self.col
        self.eng.watch_status["w"] = {}

    def tearDown(self):
        self.eng.db.conn.close()
        self.tmp.cleanup()

    def mk(self, iid, price, seller="GOOD", title="Apple iPhone 15 128GB"):
        return Offer(store="t", item_id=iid, title=title, price=price, url="https://x",
                     seller_id=seller, catalog_id="C1", official_seller=True)

    def run_once(self):
        return asyncio.run(self.eng.run_watch(self.w))

    def base(self):
        return [self.mk("A", 4900), self.mk("B", 5000), self.mk("C", 4950)]

    def test_bug_real_vira_alerta_confirmado(self):
        self.col.batch = self.base() + [self.mk("D", 490)]
        self.assertEqual(self.run_once(), 1)
        a = self.eng.db.list_alerts()[0]
        self.assertEqual((a["item_id"], a["confirmed"]), ("D", True))

    def test_loja_de_teste_descartada_e_bloqueada(self):
        self.col.batch = self.base() + [self.mk("X", 490, seller="NEW")]
        self.assertEqual(self.run_once(), 0)
        self.assertIn("t:NEW", self.eng.db.blocked_sellers())
        self.assertIn("provável teste", self.eng.db.list_discards()[0]["reason"])

    def test_anuncio_teste_nao_polui_referencia(self):
        self.col.batch = self.base() + [self.mk("T", 1.0, title="TESTE iPhone 15")]
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.eng.db.history("t", "T"), [])

    def test_preco_ja_corrigido(self):
        self.col.batch = self.base() + [self.mk("D", 490)]
        self.col.fixed_price = 4890
        self.assertEqual(self.run_once(), 0)
        self.assertIn("corrigiu", self.eng.db.list_discards()[0]["reason"])


class DatabaseTests(unittest.TestCase):
    def test_historico_e_alerta(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            for p in (100, 101, 99):
                o = offer(p); db.save_offer(o)
            self.assertEqual(db.history("t", "X1"), [100, 101, 99])
            o = offer(10); v = evaluate(o, db.history("t", "X1"))
            a = db.save_alert(o, v)
            self.assertEqual(a["level"], "CRITICO")
            db.set_alert_status(a["id"], "comprado")
            self.assertEqual(db.stats()["comprados"], 1)
            db.conn.close()


class MercadoLivreTests(unittest.TestCase):
    def test_catalogo_e_refresh_de_token(self):
        calls = []

        def handler(req: httpx.Request):
            calls.append(req.url.path)
            if req.url.path == "/oauth/token":
                return httpx.Response(200, json={"access_token": "NOVO", "refresh_token": "R2", "expires_in": 21600})
            assert req.headers["authorization"] == "Bearer NOVO"
            if req.url.path == "/products/search":
                return httpx.Response(200, json={"results": [{"id": "MLBP1"}]})
            if req.url.path == "/products/MLBP1":
                return httpx.Response(200, json={"name": "iPhone 15", "pictures": [{"url": "http://img/1.jpg"}]})
            if req.url.path == "/products/MLBP1/items":
                return httpx.Response(200, json={"results": [
                    {"item_id": "MLB1", "price": 399.0, "original_price": 4999.0, "seller_id": 7,
                     "shipping": {"free_shipping": True}, "condition": "new"}]})
            return httpx.Response(404)

        async def run():
            with tempfile.TemporaryDirectory() as d:
                tok = Path(d) / "tok.json"
                tok.write_text(json.dumps({"access_token": "VELHO", "refresh_token": "R1", "expires_at": 0}))
                c = mlmod.MercadoLivreCollector("id", "secret", tok)
                c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                c.tokens.data = json.loads(tok.read_text())
                orig_api = mlmod.API
                mlmod.API = "https://api.test"
                try:
                    offers = await c.collect(Watch(name="w", store="mercadolivre", query="iphone"))
                finally:
                    mlmod.API = orig_api
                    await c.close()
                saved = json.loads(tok.read_text())
                return offers, saved

        offers, saved = asyncio.run(run())
        self.assertEqual([o.item_id for o in offers], ["MLB1"])
        self.assertTrue(offers[0].free_shipping)
        self.assertTrue(offers[0].thumbnail.startswith("https://"))
        self.assertEqual(saved["refresh_token"], "R2")
        self.assertEqual(calls.count("/oauth/token"), 1)


if __name__ == "__main__":
    unittest.main()
