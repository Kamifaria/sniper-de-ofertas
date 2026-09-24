"""Menos falso alerta: marca muito falsificada só de vendedor oficial, preço de mercado e preço de sempre."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config, filters  # noqa: E402
from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.collectors.vtex import VtexCollector  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.models import Offer, Watch  # noqa: E402


def chk(title, brand="", oficial=None, cfg=None, w=None):
    o = Offer(store="t", item_id="1", title=title, price=50, url="https://x", brand=brand, official_seller=oficial)
    return filters.check_listing(o, w, cfg or filters.FilterConfig(), set())


class MarcaFalsificadaTests(unittest.TestCase):
    def test_marca_visada_de_vendedor_comum_e_descartada(self):
        self.assertIn("vendedor não oficial", chk("Boné Gucci Luxo Aba Curva Ajustável", oficial=False))

    def test_sem_saber_se_e_oficial_tambem_descarta(self):
        self.assertIn("vendedor não oficial", chk("Tênis Nike Air Max 90", oficial=None))

    def test_vendedor_oficial_passa(self):
        self.assertIsNone(chk("Boné Gucci Luxo Aba Curva Ajustável", oficial=True))

    def test_marca_pelo_campo_da_loja(self):
        self.assertIn("Stanley", chk("Copo Térmico 473ml Verde", brand="Stanley", oficial=False))

    def test_marcas_de_varias_palavras_e_sem_acento(self):
        self.assertIn("Louis Vuitton", chk("Bolsa LOUIS VUITTON Neverfull", oficial=False))
        self.assertIn("Hermès", chk("Cinto Hermes H Couro", oficial=False))

    def test_palavra_parecida_nao_conta(self):
        self.assertIsNone(chk("Ômega 3 1000mg 120 Cápsulas", oficial=False))
        self.assertIsNone(chk("Filtro de Óleo Motor Diesel", oficial=False))
        self.assertIsNone(chk("Vinho Diamante Tinto", oficial=False))

    def test_marca_comum_nao_e_afetada(self):
        self.assertIsNone(chk("Açúcar Refinado União 1kg", brand="União", oficial=False))

    def test_marcas_extras_do_config(self):
        cfg = filters.FilterConfig()
        cfg.counterfeit_brands += ["Minha Marca"]
        self.assertIn("Minha Marca", chk("Camiseta Minha Marca Preta", cfg=cfg, oficial=False))

    def test_busca_pela_marca_nao_libera_falsificado(self):
        w = Watch(name="w", store="t", query="gucci")
        self.assertIn("vendedor não oficial", chk("Boné Gucci Luxo", oficial=False, w=w))

    def test_config_le_marcas_extras(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text('[filtros]\nmarcas_falsificadas_extras = ["Minha Marca"]\n', encoding="utf-8")
            s = config.load(p)
        self.assertIn("Minha Marca", s.filters.counterfeit_brands)
        self.assertIn("Gucci", s.filters.counterfeit_brands)


class PalavrasTests(unittest.TestCase):
    def test_replica_disfarcada(self):
        for t in ["Tênis Inspired Jordan", "Relógio Primeira Linha", "Óculos AAA Espelhado", "Perfume Inspiração 212"]:
            self.assertIsNotNone(chk(t), t)

    def test_gift_card(self):
        self.assertIsNotNone(chk("Gift Card Centauro R$ 50"))
        self.assertIsNotNone(chk("Cartão Presente Riachuelo"))


class PrecoDeMercadoTests(unittest.TestCase):
    def test_varios_vendedores_perto_nao_e_bug(self):
        # livro: vários vendedores entre R$ 48 e R$ 70, mediana puxada por quem vende a R$ 359
        peers = [48.73, 48.9, 68.4, 68.93, 70.93] + [359.7] * 10 + [400.0] * 10
        v = evaluate(Offer(store="t", item_id="1", title="Livro", price=48.72, url="x"), [], peers=peers)
        self.assertEqual(v.level, "NENHUM")
        self.assertTrue(any("vendem perto" in r for r in v.reasons))

    def test_no_meio_do_grupo_tambem_nao_e_bug(self):
        # vendedor de R$ 48,73: um concorrente mais barato (48,72) e outro logo acima (48,90)
        peers = [48.72, 48.9] + [359.7] * 10
        v = evaluate(Offer(store="t", item_id="1", title="Livro", price=48.73, url="x"), [], peers=peers)
        self.assertEqual(v.level, "NENHUM")

    def test_um_vendedor_isolado_ainda_e_bug(self):
        v = evaluate(Offer(store="t", item_id="1", title="TV", price=450.0, url="x"), [],
                     peers=[450.0 * 1.5, 4800.0, 4900.0, 5000.0])
        self.assertEqual(v.level, "CRITICO")

    def test_preco_de_sempre_na_loja_nao_e_bug(self):
        # unidade (R$ 4,99) com o mesmo código de barras da caixa em outras lojas (R$ 45)
        v = evaluate(Offer(store="t", item_id="1", title="Snickers", price=4.99, url="x"),
                     [4.99] * 5, peers=[45.0, 46.0])
        self.assertEqual(v.level, "NENHUM")
        self.assertTrue(any("preço de sempre" in r for r in v.reasons))

    def test_queda_no_proprio_historico_continua_valendo(self):
        v = evaluate(Offer(store="t", item_id="1", title="TV", price=100.0, url="x"), [1000.0] * 5,
                     peers=[1000.0, 1000.0])
        self.assertEqual(v.level, "CRITICO")


class ColetoresTests(unittest.TestCase):
    def test_ml_marca_e_loja_oficial(self):
        def handler(req: httpx.Request):
            if req.url.path == "/products/search":
                return httpx.Response(200, json={"results": [{"id": "MLBP1"}]})
            if req.url.path == "/products/MLBP1":
                return httpx.Response(200, json={"name": "Boné Gucci", "pictures": [],
                                                 "attributes": [{"id": "BRAND", "value_name": "Gucci"}]})
            if req.url.path == "/products/MLBP1/items":
                return httpx.Response(200, json={"results": [
                    {"item_id": "MLB1", "price": 54.9, "seller_id": 1, "official_store_id": None, "tags": []},
                    {"item_id": "MLB2", "price": 499.0, "seller_id": 2, "official_store_id": 123, "tags": []},
                    {"item_id": "MLB3", "price": 499.0, "seller_id": 3, "tags": ["first_party"]}]})
            return httpx.Response(404)

        async def run():
            with tempfile.TemporaryDirectory() as d:
                tok = Path(d) / "tok.json"
                tok.write_text(json.dumps({"access_token": "T", "refresh_token": "R", "expires_at": 9e12}))
                c = mlmod.MercadoLivreCollector("id", "secret", tok)
                c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                orig, mlmod.API = mlmod.API, "https://api.test"
                try:
                    return await c.collect(Watch(name="w", store="mercadolivre", query="gucci"))
                finally:
                    mlmod.API = orig
                    await c.close()

        offers = {o.item_id: o for o in asyncio.run(run())}
        self.assertEqual({o.brand for o in offers.values()}, {"Gucci"})
        self.assertEqual([offers[i].official_seller for i in ("MLB1", "MLB2", "MLB3")], [False, True, True])

    def test_vtex_marca_e_vendedor_da_propria_loja(self):
        def prod(seller):
            return {"productId": "1", "productName": "Tênis Nike", "brand": "Nike", "link": "https://l/p",
                    "categoryId": "1", "items": [{"itemId": f"S{seller}", "ean": "", "images": [], "sellers": [
                        {"sellerId": seller, "sellerDefault": True, "commertialOffer": {
                            "Price": 100.0, "ListPrice": 100.0, "AvailableQuantity": 5, "IsAvailable": True}}]}]}

        def handler(req: httpx.Request):
            return httpx.Response(200, json=[prod("1"), prod("mktplace9")])

        async def run():
            c = VtexCollector("t", "loja.test")
            c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                return await c.collect(Watch(name="w", store="t", query="nike"))
            finally:
                await c.close()

        offers = {o.item_id: o for o in asyncio.run(run())}
        self.assertEqual(offers["S1"].brand, "Nike")
        self.assertTrue(offers["S1"].official_seller)
        self.assertFalse(offers["Smktplace9"].official_seller)


if __name__ == "__main__":
    unittest.main()
