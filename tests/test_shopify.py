"""Coletor Shopify: /products.json público das lojas de maquiagem (lojas não oficiais)."""
import asyncio
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sniper.collectors.shopify import ShopifyCollector  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402


def produto(pid, handle, titulo, variantes, vendor="MARCA", tipo="Base"):
    return {"id": pid, "title": titulo, "handle": handle, "vendor": vendor, "product_type": tipo,
            "images": [{"src": f"https://img/{handle}.jpg"}],
            "variants": [{"id": vid, "title": vt, "price": preco, "compare_at_price": de, "available": disp}
                         for vid, vt, preco, de, disp in variantes]}


def rodar(handler, fn):
    async def run():
        c = ShopifyCollector("lojateste", "loja.test")
        c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def sem_espera(_):
            return None
        c._sleep = sem_espera
        try:
            return await fn(c)
        finally:
            await c.close()
    return asyncio.run(run())


W = Watch(name="Varre", store="lojateste", kind="varrer")
BASE = produto(1, "base-liquida", "Base Líquida", [(11, "01 - Magnólia", "69.90", None, True),
                                                      (12, "02 - Bege", "69.90", "99.90", True),
                                                      (13, "03 - Esgotado", "69.90", None, False)])


class ShopifyTests(unittest.TestCase):
    def test_registradas_como_lojas_nao_oficiais(self):
        for chave in ("bocarosa", "marimaria"):
            info = LOJAS[chave]
            self.assertFalse(info.oficial)
            self.assertIsInstance(info.criar(None, None), ShopifyCollector)

    def test_brinde_a_zero_e_preco_simbolico(self):
        self.assertTrue(ShopifyCollector("x", "x.test").precos_simbolicos)

    def test_uma_oferta_por_variante_disponivel(self):
        h = lambda req: httpx.Response(200, json={"products": [BASE]})  # noqa: E731
        offers = rodar(h, lambda c: c.sweep("all", W))
        self.assertEqual([o.item_id for o in offers], ["11", "12"])
        a, b = offers
        self.assertEqual((a.store, a.price, a.original_price, a.brand, a.category), ("lojateste", 69.9, None, "MARCA", "Base"))
        self.assertEqual(b.original_price, 99.9)
        self.assertEqual(a.title, "Base Líquida - 01 - Magnólia")
        self.assertEqual(a.url, "https://loja.test/products/base-liquida?variant=11")
        self.assertEqual(a.cart_url, "https://loja.test/cart/11:1")
        self.assertEqual(a.thumbnail, "https://img/base-liquida.jpg")
        self.assertTrue(a.official_seller)
        self.assertEqual(a.condition, "new")

    def test_variante_unica_nao_repete_o_nome(self):
        p = produto(2, "batom", "Batom", [(21, "Default Title", "29.90", None, True)])
        offers = rodar(lambda r: httpx.Response(200, json={"products": [p]}), lambda c: c.sweep("all", W))
        self.assertEqual(offers[0].title, "Batom")

    def test_le_varias_paginas_ate_acabar(self):
        pags = []

        def h(req):
            n = int(req.url.params["page"])
            pags.append(n)
            qtd = 250 if n < 3 else 2
            return httpx.Response(200, json={"products": [produto(n * 1000 + i, f"p{n}-{i}", "P", [(n * 1000 + i, "Default Title", "10.00", None, True)])
                                                          for i in range(qtd)]})
        offers = rodar(h, lambda c: c.sweep("all", W))
        self.assertEqual(pags, [1, 2, 3])
        self.assertEqual(len(offers), 502)

    def test_sweep_so_tem_uma_unidade(self):
        self.assertEqual(rodar(lambda r: httpx.Response(200, json={"products": []}), lambda c: c.sweep_units(W)), ["all"])

    def test_busca_filtra_pelo_nome_sem_acento(self):
        p2 = produto(2, "batom", "Batom Vermelho", [(21, "Default Title", "29.90", None, True)])
        h = lambda req: httpx.Response(200, json={"products": [BASE, p2]})  # noqa: E731
        offers = rodar(h, lambda c: c.collect(Watch(name="b", store="lojateste", query="liquida base")))
        self.assertEqual({o.title.split(" - ")[0] for o in offers}, {"Base Líquida"})
        self.assertEqual(rodar(h, lambda c: c.collect(Watch(name="b", store="lojateste"))), [])

    def test_confirm_le_o_produto_e_acha_a_variante(self):
        o = rodar(lambda r: httpx.Response(200, json={"products": [BASE]}), lambda c: c.sweep("all", W))[1]

        def h(req):
            self.assertEqual(req.url.path, "/products/base-liquida.js")
            return httpx.Response(200, json={"variants": [{"id": 12, "price": 5990, "compare_at_price": 9990, "available": True}]})
        fresh = rodar(h, lambda c: c.confirm(o))
        self.assertEqual((fresh.price, fresh.original_price, fresh.confirmed), (59.9, 99.9, True))

    def test_confirm_devolve_none_se_esgotou_ou_sumiu(self):
        o = rodar(lambda r: httpx.Response(200, json={"products": [BASE]}), lambda c: c.sweep("all", W))[1]
        esgotado = lambda r: httpx.Response(200, json={"variants": [{"id": 12, "price": 6990, "available": False}]})  # noqa: E731
        self.assertIsNone(rodar(esgotado, lambda c: c.confirm(o)))
        self.assertIsNone(rodar(lambda r: httpx.Response(404, json={}), lambda c: c.confirm(o)))

    def test_bloqueio_403_levanta_erro_de_coleta(self):
        from sniper.collectors import CollectorError
        with self.assertRaises(CollectorError):
            rodar(lambda r: httpx.Response(403), lambda c: c.sweep("all", W))


if __name__ == "__main__":
    unittest.main()
