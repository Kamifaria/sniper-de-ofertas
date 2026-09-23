"""Coletor VTEX: busca pública de catálogo (lojas não oficiais)."""
import asyncio
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import MotorDeTeste, oferta  # noqa: E402
from sniper.collectors.base import Collector  # noqa: E402
from sniper.collectors.vtex import VtexCollector  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402

TREE = [{"id": 1, "children": [{"id": 10, "children": []}, {"id": 11, "children": [{"id": 110, "children": []}]}]},
        {"id": 2, "children": []}]


def produto(pid, sku, preco, lista=None, estoque=10, disponivel=True, ean="789", outros_skus=()):
    def item(s, p):
        return {"itemId": s, "ean": ean, "images": [{"imageUrl": f"https://img/{s}.jpg"}],
                "sellers": [{"sellerId": "1", "sellerName": "Loja", "sellerDefault": True,
                             "commertialOffer": {"Price": p, "ListPrice": lista if lista is not None else p,
                                                 "AvailableQuantity": estoque, "IsAvailable": disponivel}}]}
    return {"productId": pid, "productName": f"Produto {pid}", "link": f"https://loja.test/p{pid}/p",
            "categoryId": "10", "items": [item(sku, preco)] + [item(s, 50.0) for s in outros_skus]}


def rodar(handler, fn, limiter=None):
    async def run():
        c = VtexCollector("lojateste", "loja.test", limiter=limiter)
        c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def sem_espera(_):
            return None
        c._sleep = sem_espera
        try:
            return await fn(c)
        finally:
            await c.close()
    return asyncio.run(run())


W = Watch(name="Varre", store="lojateste", kind="varrer", max_pages=1)


class VtexColetorTests(unittest.TestCase):
    def test_folhas_da_arvore_viram_caminhos(self):
        def h(req):
            assert req.url.path.startswith("/api/catalog_system/pub/category/tree/")
            return httpx.Response(200, json=TREE)
        self.assertEqual(rodar(h, lambda c: c.sweep_units(W)), ["/1/10/", "/1/11/110/", "/2/"])

    def test_sweep_do_mais_barato_e_so_disponivel(self):
        params = []

        def h(req):
            params.append(dict(req.url.params))
            return httpx.Response(206, json=[
                produto("1", "100", 9.9, lista=19.9),
                produto("2", "200", 5.0, estoque=0),
                produto("3", "300", 7.0, disponivel=False),
            ])
        offers = rodar(h, lambda c: c.sweep("/1/10/", W))
        self.assertEqual(params[0]["fq"], "C:/1/10/")
        self.assertEqual((params[0]["O"], params[0]["_from"], params[0]["_to"]), ("OrderByPriceASC", "0", "49"))
        self.assertEqual([o.item_id for o in offers], ["100"])
        o = offers[0]
        self.assertEqual((o.store, o.price, o.original_price, o.catalog_id), ("lojateste", 9.9, 19.9, "789"))
        self.assertEqual((o.url, o.thumbnail), ("https://loja.test/p1/p", "https://img/100.jpg"))

    def test_lista_igual_ao_preco_nao_vira_de_por(self):
        offers = rodar(lambda req: httpx.Response(200, json=[produto("1", "100", 30.0)]),
                       lambda c: c.sweep("/2/", W))
        self.assertIsNone(offers[0].original_price)

    def test_refresh_em_lotes_de_50_so_skus_pedidos(self):
        lotes = []

        def h(req):
            skus = [v.split(":")[1] for k, v in req.url.params.multi_items() if k == "fq"]
            lotes.append(len(skus))
            return httpx.Response(200, json=[produto(s, s, 10.0, outros_skus=("X" + s,)) for s in skus])
        lim = RateLimiter(1000)
        ids = [str(i) for i in range(120)]
        offers = rodar(h, lambda c: c.refresh(ids), limiter=lim)
        self.assertEqual(lotes, [50, 50, 20])
        self.assertEqual(sorted(o.item_id for o in offers), sorted(ids))
        self.assertEqual({f for _, f in lim._usos}, {"rapida"})

    def test_confirm_devolve_none_quando_esgotou(self):
        o = oferta("100", 9.9, store="lojateste")
        r = rodar(lambda req: httpx.Response(200, json=[produto("1", "100", 9.9, estoque=0)]),
                  lambda c: c.confirm(o))
        self.assertIsNone(r)

    def test_403_pausa_a_loja(self):
        lim = RateLimiter(60)
        from sniper.collectors import CollectorError
        with self.assertRaises(CollectorError):
            rodar(lambda req: httpx.Response(403, text="bloqueado"), lambda c: c.sweep("/2/", W), limiter=lim)
        self.assertTrue(lim.pausada)

    def test_5xx_persistente_da_erro_sem_pausar(self):
        lim = RateLimiter(60)
        from sniper.collectors import CollectorError
        with self.assertRaises(CollectorError):
            rodar(lambda req: httpx.Response(503), lambda c: c.sweep("/2/", W), limiter=lim)
        self.assertFalse(lim.pausada)


class RegistroVtexTests(unittest.TestCase):
    def test_dez_lojas_nao_oficiais(self):
        vtex = {k: i for k, i in LOJAS.items() if k != "mercadolivre"}
        self.assertEqual(len(vtex), 10)
        self.assertTrue(all(not i.oficial for i in vtex.values()))
        self.assertIn("samsclub", vtex)


class PrecoSimbolicoTests(unittest.TestCase):
    class Loja(Collector):
        store = "t"
        precos_simbolicos = True

        async def collect(self, watch):
            return []

    def test_ja_nasce_simbolico_nao_alerta(self):
        with MotorDeTeste() as m:
            col = self.Loja()
            w = Watch(name="w", store="t")
            for _ in range(3):
                r = asyncio.run(m.engine._process(w, col, [oferta("A", 0.01, catalog="")]))
                self.assertEqual(r["alertas"], 0)

    def test_cair_para_simbolico_depois_de_historico_alerta(self):
        with MotorDeTeste() as m:
            col = self.Loja()
            w = Watch(name="w", store="t")
            for _ in range(3):
                asyncio.run(m.engine._process(w, col, [oferta("A", 2500.0, catalog="")]))
            r = asyncio.run(m.engine._process(w, col, [oferta("A", 0.01, catalog="")]))
            self.assertEqual(r["alertas"], 1)
            self.assertEqual(m.engine.db.list_alerts()[0]["level"], "GRATIS")


if __name__ == "__main__":
    unittest.main()
