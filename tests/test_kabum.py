"""Coletor KaBuM: API pública de catálogo (loja não oficial)."""
import asyncio
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sniper.collectors.kabum import KabumCollector  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402


def prod(pid, preco, com_desc=None, antigo=0.0, oferta=None, estoque=5, disponivel=True,
         marketplace=False, openbox=False):
    return {"id": pid, "attributes": {
        "title": f"Produto {pid}", "price": preco, "old_price": antigo,
        "price_with_discount": com_desc if com_desc is not None else preco,
        "offer": {"price_with_discount": oferta} if oferta else None,
        "available": disponivel, "stock": estoque, "is_marketplace": marketplace, "is_openbox": openbox,
        "has_free_shipping": True, "product_link": f"produto-{pid}",
        "manufacturer": {"name": "Marca"},
        "marketplace": {"seller_id": 77, "seller_name": "Vendedor"} if marketplace else None,
        "photos": {"p": ["https://img/p.jpg"]}}}


def rodar(handler, fn):
    async def run():
        c = KabumCollector()
        c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def sem_espera(_):
            return None
        c._sleep = sem_espera
        try:
            return await fn(c)
        finally:
            await c.close()
    return asyncio.run(run())


W = Watch(name="Varre", store="kabum", kind="varrer")


class KabumTests(unittest.TestCase):
    def test_registrada_como_loja_nao_oficial(self):
        info = LOJAS["kabum"]
        self.assertFalse(info.oficial)
        self.assertIsInstance(info.criar(None, None), KabumCollector)

    def test_sweep_do_mais_barato_com_link_e_campos(self):
        reqs = []

        def h(req):
            reqs.append(req)
            return httpx.Response(200, json={"data": [prod(1, 9.9, antigo=19.9), prod(2, 5.0, estoque=0),
                                                      prod(3, 7.0, disponivel=False)]})
        offers = rodar(h, lambda c: c.sweep("hardware", W))
        self.assertEqual(reqs[0].url.path.rsplit("/", 2)[-2:], ["products-by-category", "hardware"])
        self.assertEqual(reqs[0].url.params["sort"], "price")
        self.assertEqual([o.item_id for o in offers], ["1"])
        o = offers[0]
        self.assertEqual((o.store, o.price, o.original_price, o.condition), ("kabum", 9.9, 19.9, "new"))
        self.assertEqual(o.url, "https://www.kabum.com.br/produto/1/produto-1")
        self.assertTrue(o.official_seller)
        self.assertEqual(o.brand, "Marca")

    def test_preco_usa_a_oferta_relampago_quando_existe(self):
        h = lambda req: httpx.Response(200, json={"data": [prod(1, 29.4, com_desc=24.99, oferta=9.99)]})  # noqa: E731
        self.assertEqual(rodar(h, lambda c: c.sweep("tv", W))[0].price, 9.99)

    def test_preco_com_desconto_vale_mais_que_o_cheio(self):
        h = lambda req: httpx.Response(200, json={"data": [prod(1, 29.4, com_desc=24.99)]})  # noqa: E731
        self.assertEqual(rodar(h, lambda c: c.sweep("tv", W))[0].price, 24.99)

    def test_marketplace_nao_e_vendedor_oficial_e_openbox_e_usado(self):
        h = lambda req: httpx.Response(200, json={"data": [prod(1, 10, marketplace=True),  # noqa: E731
                                                           prod(2, 10, openbox=True)]})
        a, b = rodar(h, lambda c: c.sweep("tv", W))
        self.assertEqual((a.official_seller, a.seller_id, a.seller_name), (False, "77", "Vendedor"))
        self.assertEqual(b.condition, "used")

    def test_categoria_sem_produto_devolve_vazio(self):
        h = lambda req: httpx.Response(404, json={"errors": [{"code": "CATALOG_NOT_MATCH"}]})  # noqa: E731
        self.assertEqual(rodar(h, lambda c: c.sweep("games", W)), [])

    def test_busca_por_termo(self):
        reqs = []

        def h(req):
            reqs.append(req)
            return httpx.Response(200, json={"data": [prod(1, 319.0)]})
        offers = rodar(h, lambda c: c.collect(Watch(name="b", store="kabum", query="iphone")))
        self.assertEqual(reqs[0].url.path.rsplit("/", 1)[-1], "products")
        self.assertEqual(reqs[0].url.params["query"], "iphone")
        self.assertEqual(len(offers), 1)

    def test_refresh_e_confirm_leem_cada_produto(self):
        def h(req):
            pid = req.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=prod(int(pid), 8.0))
        offers = rodar(h, lambda c: c.refresh(["1", "2"]))
        self.assertEqual([(o.item_id, o.price) for o in offers], [("1", 8.0), ("2", 8.0)])
        fresh = rodar(h, lambda c: c.confirm(offers[0]))
        self.assertTrue(fresh.confirmed)

    def test_confirm_devolve_none_se_sumiu(self):
        h = lambda req: httpx.Response(404, json={})  # noqa: E731
        o = rodar(lambda r: httpx.Response(200, json={"data": [prod(1, 5.0)]}), lambda c: c.sweep("tv", W))[0]
        self.assertIsNone(rodar(h, lambda c: c.confirm(o)))


if __name__ == "__main__":
    unittest.main()
