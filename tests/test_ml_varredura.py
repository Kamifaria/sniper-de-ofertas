"""Mercado Livre pelo catálogo: mais vendidos por categoria e todos os vendedores de cada produto.

A busca de anúncios (/sites/MLB/search) e a leitura direta (/items) são bloqueadas para apps comuns
(403, conferido em 2026-09-24); o catálogo (/highlights, /products) é liberado.
"""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, oferta  # noqa: E402
from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402

RAIZES = [{"id": "A"}, {"id": "B"}]
DUMP = {"A": {"children_categories": [{"id": "A1"}, {"id": "A2"}]}, "A1": {"children_categories": []},
        "A2": {"children_categories": [{"id": "A2x"}]}, "A2x": {"children_categories": []},
        "B": {"children_categories": []}}
NOS = {"A": [{"id": "A1"}, {"id": "A2"}], "B": []}


def vendedor(item, preco, orig=None, seller=5, cond="new"):
    return {"item_id": item, "price": preco, "original_price": orig, "seller_id": seller, "condition": cond,
            "category_id": "A1", "shipping": {"free_shipping": True}}


def catalogo(req, chamadas=None):
    """Handler padrão: categoria A1 tem 1 produto de catálogo (P1) com 2 vendedores."""
    p = req.url.path
    if chamadas is not None:
        chamadas.append(p)
    if p == "/highlights/MLB/category/A1":
        return httpx.Response(200, json={"content": [{"id": "MLBP1", "type": "PRODUCT"},
                                                     {"id": "MLBU9", "type": "USER_PRODUCT"}]})
    if p.startswith("/highlights/"):
        return httpx.Response(404, json={"message": "not found"})
    if p == "/products/search":
        return httpx.Response(200, json={"results": [{"id": "MLBP1"}]})
    if p == "/products/MLBP1":
        return httpx.Response(200, json={"name": "Celular X 256GB", "pictures": [{"url": "http://img/p1.jpg"}]})
    if p == "/products/MLBP1/items":
        return httpx.Response(200, json={"paging": {"total": 2}, "results": [
            vendedor("MLB111", 1000.0), vendedor("MLB222", 99.0, orig=1100.0, seller=6)]})
    return httpx.Response(404)


def rodar(handler, fn, limiter=None):
    """Cria o coletor com transporte falso, roda fn(coletor) e devolve o resultado."""
    async def run():
        with tempfile.TemporaryDirectory() as d:
            tok = Path(d) / "tok.json"
            tok.write_text(json.dumps({"access_token": "OK", "refresh_token": "R",
                                       "expires_at": time.time() + 3600}))
            c = mlmod.MercadoLivreCollector("id", "secret", tok, limiter=limiter)
            c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

            async def sem_espera(_):
                return None
            c._sleep = sem_espera
            orig = mlmod.API
            mlmod.API = "https://api.test"
            try:
                return await fn(c)
            finally:
                mlmod.API = orig
                await c.close()
    return asyncio.run(run())


W = Watch(name="v", store="mercadolivre", kind="varrer")


class CategoriasTests(unittest.TestCase):
    def test_unidades_sao_categorias_do_segundo_nivel(self):
        calls = []

        def h(req):
            calls.append(req.url.path)
            if req.url.path == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if req.url.path == "/sites/MLB/categories/all":
                return httpx.Response(200, json=DUMP)
            return httpx.Response(404)

        self.assertEqual(rodar(h, lambda c: c.sweep_units(W)), ["A1", "A2", "B"])
        self.assertFalse(any(p.startswith("/categories/") for p in calls))

    def test_sem_dump_le_no_a_no_sem_pausar(self):
        lim = RateLimiter(60)

        def h(req):
            p = req.url.path
            if p == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if p == "/sites/MLB/categories/all":
                return httpx.Response(403, json={"message": "forbidden"})
            if p.startswith("/categories/"):
                return httpx.Response(200, json={"children_categories": NOS[p.rsplit("/", 1)[1]]})
            return httpx.Response(404)

        self.assertEqual(rodar(h, lambda c: c.sweep_units(W), limiter=lim), ["A1", "A2", "B"])
        self.assertFalse(lim.pausada)

    def test_categorias_escolhidas_viram_unidades(self):
        w = Watch(name="v", store="mercadolivre", kind="varrer", sweep_categories=["MLB1055", "MLB1648"])
        self.assertEqual(rodar(lambda req: httpx.Response(500), lambda c: c.sweep_units(w)), ["MLB1055", "MLB1648"])


class CatalogoTests(unittest.TestCase):
    def test_sweep_le_todos_os_vendedores_dos_mais_vendidos(self):
        offers = rodar(catalogo, lambda c: c.sweep("A1", W))
        self.assertEqual([o.item_id for o in offers], ["MLB111", "MLB222"])
        o = offers[1]
        self.assertEqual((o.price, o.original_price, o.catalog_id, o.seller_id), (99.0, 1100.0, "MLBP1", "6"))
        self.assertEqual((o.title, o.thumbnail), ("Celular X 256GB", "https://img/p1.jpg"))
        self.assertEqual(o.url, "https://produto.mercadolivre.com.br/MLB-222")
        self.assertTrue(o.free_shipping)

    def test_categoria_sem_mais_vendidos_nao_e_erro(self):
        self.assertEqual(rodar(catalogo, lambda c: c.sweep("Z9", W)), [])

    def test_nome_do_produto_fica_em_cache(self):
        chamadas = []

        async def duas_vezes(c):
            await c.sweep("A1", W)
            await c.sweep("A1", W)
        rodar(lambda req: catalogo(req, chamadas), duas_vezes)
        self.assertEqual(chamadas.count("/products/MLBP1"), 1)
        self.assertEqual(chamadas.count("/products/MLBP1/items"), 2)

    def test_regra_por_termo_busca_no_catalogo(self):
        w = Watch(name="iPhones", store="mercadolivre", query="iphone 15")
        offers = rodar(catalogo, lambda c: c.collect(w))
        self.assertEqual({o.item_id for o in offers}, {"MLB111", "MLB222"})

    def test_itens_avulsos_sao_ignorados_sem_chamar_items(self):
        chamadas = []
        w = Watch(name="w", store="mercadolivre", item_ids=["MLB1"])
        self.assertEqual(rodar(lambda req: catalogo(req, chamadas), lambda c: c.collect(w)), [])
        self.assertNotIn("/items", chamadas)

    def test_refresh_por_produto_na_fila_rapida(self):
        lim = RateLimiter(1000)
        offers = rodar(catalogo, lambda c: c.refresh(["MLBP1"]), limiter=lim)
        self.assertEqual({o.watch for o in offers}, {"Fila rápida"})
        self.assertEqual(len(offers), 2)
        self.assertEqual({f for _, f in lim._usos}, {"rapida"})

    def test_confirm_acha_o_vendedor_no_produto(self):
        o = oferta("MLB222", 99.0, store="mercadolivre", catalog="MLBP1")
        r = rodar(catalogo, lambda c: c.confirm(o))
        self.assertTrue(r.confirmed)
        self.assertEqual(r.price, 99.0)
        sumiu = oferta("MLB999", 99.0, store="mercadolivre", catalog="MLBP1")
        self.assertIsNone(rodar(catalogo, lambda c: c.confirm(sumiu)))

    def test_5xx_persistente_da_erro_sem_pausar(self):
        lim = RateLimiter(60)
        from sniper.collectors import CollectorError
        with self.assertRaises(CollectorError):
            rodar(lambda req: httpx.Response(503), lambda c: c.sweep("A1", W), limiter=lim)
        self.assertFalse(lim.pausada)


class FilaPorCatalogoTests(unittest.TestCase):
    class Loja(FakeCollector):
        supports_refresh = True
        refresh_por_catalogo = True

        def __init__(self):
            super().__init__()
            self.pedidos = []

        async def refresh(self, ids):
            self.pedidos.append(sorted(ids))
            return []

    def test_fila_rapida_manda_produtos_do_catalogo(self):
        with MotorDeTeste() as m:
            db = m.engine.db
            for iid, cat in (("I1", "P1"), ("I2", "P1"), ("I3", "P2"), ("I4", "")):
                db.save_offer(oferta(iid, 5000.0, catalog=cat))
            col = self.Loja()
            m.engine.collectors["t"] = col
            asyncio.run(m.engine.fast_lane_step())
            self.assertEqual(col.pedidos, [["P1", "P2"]])


if __name__ == "__main__":
    unittest.main()
