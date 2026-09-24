"""Amazon pela Creators API (afiliados): token, busca, releitura, erros e conversão da oferta."""
import asyncio
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config  # noqa: E402
from sniper.collectors import CollectorError  # noqa: E402
from sniper.collectors import amazon as amz  # noqa: E402
from sniper.models import Offer, Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402


def item(asin, preco, de=None, estoque="IN_STOCK", vendedor="Amazon.com.br", condicao="New",
         marca="Sony", ean="4548736132610", buybox=True):
    listing = {"price": {"money": {"amount": preco, "currency": "BRL"}},
               "availability": {"type": estoque},
               "merchantInfo": {"name": vendedor, "id": "M1" if vendedor.startswith("Amazon") else "M9"},
               "condition": {"value": condicao}, "isBuyBoxWinner": buybox}
    if de:
        listing["price"]["savingBasis"] = {"money": {"amount": de}}
    return {"asin": asin, "detailPageURL": f"https://www.amazon.com.br/dp/{asin}?tag=minhatag-20",
            "images": {"primary": {"medium": {"url": f"https://img/{asin}.jpg"}}},
            "itemInfo": {"title": {"displayValue": f"Produto {asin}"},
                         "byLineInfo": {"brand": {"displayValue": marca}},
                         "externalIds": {"EANs": {"displayValues": [ean]}}},
            "offersV2": {"listings": [listing]}}


class Loja:
    """Amazon falsa: guarda os pedidos e responde conforme `respostas` (fila por caminho)."""

    def __init__(self):
        self.pedidos: list[httpx.Request] = []
        self.tokens = 0
        self.busca: list = []            # páginas de itens da searchItems
        self.catalogo: dict = {}         # asin -> item, para a getItems
        self.forcar: list[int] = []      # status a devolver antes do normal (ex.: [401])

    def __call__(self, req: httpx.Request):
        self.pedidos.append(req)
        if req.url.host == "api.amazon.com":
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"TOK{self.tokens}", "expires_in": 3600})
        if self.forcar:
            return httpx.Response(self.forcar.pop(0), text="erro")
        corpo = json.loads(req.content)
        if req.url.path == "/catalog/v1/searchItems":
            pagina = corpo.get("itemPage", 1) - 1
            itens = self.busca[pagina] if pagina < len(self.busca) else []
            return httpx.Response(200, json={"searchResult": {"items": itens}})
        if req.url.path == "/catalog/v1/getItems":
            return httpx.Response(200, json={"itemsResult": {
                "items": [self.catalogo[a] for a in corpo["itemIds"] if a in self.catalogo]}})
        return httpx.Response(404)


def coletor(loja: Loja, limiter=None):
    c = amz.AmazonCollector("ID", "SEGREDO", "minhatag-20", limiter=limiter)
    c.client = httpx.AsyncClient(transport=httpx.MockTransport(loja))
    esperas: list[float] = []

    async def sleep(s):
        esperas.append(s)
    c._sleep = sleep
    c.esperas = esperas
    return c


def rodar(loja, fn, limiter=None):
    async def go():
        c = coletor(loja, limiter)
        try:
            return await fn(c), c
        finally:
            await c.close()
    return asyncio.run(go())


BUSCA = Watch(name="w", store="amazon", query="headphone sony", min_price=300, max_pages=2)


class TokenTests(unittest.TestCase):
    def test_token_login_with_amazon(self):
        loja = Loja()
        loja.busca = [[item("A1", 500.0)]]
        rodar(loja, lambda c: c.collect(BUSCA))
        tok = loja.pedidos[0]
        self.assertEqual(str(tok.url), "https://api.amazon.com/auth/o2/token")
        self.assertEqual(tok.headers["authorization"], "Basic " + base64.b64encode(b"ID:SEGREDO").decode())
        corpo = dict(x.split("=") for x in tok.content.decode().split("&"))
        self.assertEqual(corpo["grant_type"], "client_credentials")
        self.assertEqual(corpo["scope"], "creatorsapi%3A%3Adefault")

    def test_token_reaproveitado(self):
        loja = Loja()
        loja.busca = [[item(f"A{i}", 500.0) for i in range(10)], [item("B1", 600.0)]]
        rodar(loja, lambda c: c.collect(BUSCA))
        self.assertEqual(loja.tokens, 1)

    def test_401_renova_o_token(self):
        loja = Loja()
        loja.busca = [[item("A1", 500.0)]]
        loja.forcar = [401]
        offers, _ = rodar(loja, lambda c: c.collect(BUSCA))
        self.assertEqual(loja.tokens, 2)
        self.assertEqual([o.item_id for o in offers], ["A1"])


class BuscaTests(unittest.TestCase):
    def test_pedido_da_busca(self):
        loja = Loja()
        loja.busca = [[item("A1", 500.0)]]
        rodar(loja, lambda c: c.collect(BUSCA))
        req = loja.pedidos[1]
        self.assertEqual(str(req.url), "https://creatorsapi.amazon/catalog/v1/searchItems")
        self.assertEqual(req.headers["authorization"], "Bearer TOK1")
        self.assertEqual(req.headers["x-marketplace"], "www.amazon.com.br")
        corpo = json.loads(req.content)
        self.assertEqual(corpo["keywords"], "headphone sony")
        self.assertEqual(corpo["partnerTag"], "minhatag-20")
        self.assertEqual(corpo["sortBy"], "Price:LowToHigh")
        self.assertEqual(corpo["minPrice"], 30000)  # centavos
        self.assertEqual(corpo["condition"], "New")
        self.assertEqual(corpo["itemCount"], 10)
        self.assertIn("offersV2.listings.price", corpo["resources"])

    def test_paginas_param_quando_acaba(self):
        loja = Loja()
        loja.busca = [[item(f"A{i}", 500.0 + i) for i in range(10)], [item("B1", 900.0)]]
        offers, _ = rodar(loja, lambda c: c.collect(BUSCA))
        self.assertEqual(len(offers), 11)
        buscas = [json.loads(r.content)["itemPage"] for r in loja.pedidos if r.url.path.endswith("searchItems")]
        self.assertEqual(buscas, [1, 2])

    def test_pagina_incompleta_nao_pede_a_proxima(self):
        loja = Loja()
        loja.busca = [[item("A1", 500.0)], [item("B1", 900.0)]]
        rodar(loja, lambda c: c.collect(BUSCA))
        self.assertEqual(sum(r.url.path.endswith("searchItems") for r in loja.pedidos), 1)

    def test_regra_por_asin_usa_getitems(self):
        loja = Loja()
        loja.catalogo = {"A1": item("A1", 500.0)}
        offers, _ = rodar(loja, lambda c: c.collect(Watch(name="w", store="amazon", item_ids=["A1"])))
        self.assertEqual([o.item_id for o in offers], ["A1"])

    def test_uma_consulta_por_segundo(self):
        loja = Loja()
        loja.busca = [[item(f"A{i}", 500.0) for i in range(10)], [item("B1", 600.0)]]
        _, c = rodar(loja, lambda c: c.collect(BUSCA))
        self.assertTrue(any(e >= 1.0 for e in c.esperas), c.esperas)


class OfertaTests(unittest.TestCase):
    def converte(self, it):
        return amz._to_offer(it, Watch(name="w", store="amazon"))

    def test_campos(self):
        o = self.converte(item("A1", 199.9, de=999.9))
        self.assertEqual((o.store, o.item_id, o.price, o.original_price), ("amazon", "A1", 199.9, 999.9))
        self.assertEqual(o.title, "Produto A1")
        self.assertEqual(o.brand, "Sony")
        self.assertEqual(o.catalog_id, "4548736132610")
        self.assertIn("tag=minhatag-20", o.url)
        self.assertEqual(o.thumbnail, "https://img/A1.jpg")
        self.assertEqual(o.condition, "new")
        self.assertTrue(o.official_seller)

    def test_vendedor_de_fora_nao_e_oficial(self):
        o = self.converte(item("A1", 199.9, vendedor="Loja XPTO"))
        self.assertFalse(o.official_seller)
        self.assertEqual(o.seller_name, "Loja XPTO")

    def test_fora_de_estoque_e_sem_oferta_somem(self):
        self.assertIsNone(self.converte(item("A1", 199.9, estoque="OUT_OF_STOCK")))
        sem = item("A1", 199.9)
        sem["offersV2"] = {"listings": []}
        self.assertIsNone(self.converte(sem))

    def test_usado(self):
        self.assertEqual(self.converte(item("A1", 199.9, condicao="Used")).condition, "used")

    def test_prefere_o_vencedor_do_buybox(self):
        it = item("A1", 300.0, buybox=False)
        it["offersV2"]["listings"].append(item("A1", 250.0)["offersV2"]["listings"][0])
        self.assertEqual(self.converte(it).price, 250.0)

    def test_chaves_em_caixa_diferente(self):
        it = item("A1", 199.9)
        it["itemInfo"]["externalIds"] = {"eans": {"displayValues": ["789"]}}
        self.assertEqual(self.converte(it).catalog_id, "789")


class ReleituraTests(unittest.TestCase):
    def test_fila_rapida_em_lotes_de_10(self):
        loja = Loja()
        loja.catalogo = {f"A{i}": item(f"A{i}", 500.0) for i in range(23)}
        offers, _ = rodar(loja, lambda c: c.refresh([f"A{i}" for i in range(23)]))
        self.assertEqual(len(offers), 23)
        lotes = [len(json.loads(r.content)["itemIds"]) for r in loja.pedidos if r.url.path.endswith("getItems")]
        self.assertEqual(lotes, [10, 10, 3])

    def test_reconfirma(self):
        loja = Loja()
        loja.catalogo = {"A1": item("A1", 480.0)}
        velho = Offer(store="amazon", item_id="A1", title="x", price=500.0, url="u", watch="w")
        fresh, _ = rodar(loja, lambda c: c.confirm(velho))
        self.assertEqual((fresh.price, fresh.confirmed, fresh.watch), (480.0, True, "w"))

    def test_reconfirma_item_que_sumiu(self):
        velho = Offer(store="amazon", item_id="A1", title="x", price=500.0, url="u")
        fresh, _ = rodar(Loja(), lambda c: c.confirm(velho))
        self.assertIsNone(fresh)


class ErroTests(unittest.TestCase):
    def test_429_pausa_a_loja(self):
        loja = Loja()
        loja.forcar = [429] * 4
        lim = RateLimiter(50)
        with self.assertRaises(CollectorError):
            rodar(loja, lambda c: c.collect(BUSCA), limiter=lim)
        self.assertTrue(lim.pausada_ate)

    def test_403_explica(self):
        loja = Loja()
        loja.forcar = [403]
        with self.assertRaises(CollectorError) as ctx:
            rodar(loja, lambda c: c.collect(BUSCA))
        self.assertIn("vendas", str(ctx.exception))

    def test_5xx_passageiro(self):
        loja = Loja()
        loja.busca = [[item("A1", 500.0)]]
        loja.forcar = [503]
        offers, _ = rodar(loja, lambda c: c.collect(BUSCA))
        self.assertEqual(len(offers), 1)


class RegistroTests(unittest.TestCase):
    def config(self, texto):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(texto, encoding="utf-8")
            return config.load(p)

    def test_le_o_bloco_amazon_e_liga_a_loja(self):
        s = self.config('[amazon]\ncredencial_id = "I"\ncredencial_segredo = "S"\ntag_afiliado = "t-20"\n')
        self.assertEqual((s.amazon_id, s.amazon_secret, s.amazon_tag), ("I", "S", "t-20"))
        self.assertTrue(s.lojas["amazon"].ativo)

    def test_loja_oficial_e_sem_credencial_nao_configurada(self):
        info = LOJAS["amazon"]
        self.assertTrue(info.oficial)
        self.assertIsNone(info.criar(self.config(""), RateLimiter(50)))
        self.assertIn("[amazon]", info.motivo_sem_config)

    def test_com_credencial_cria_o_coletor(self):
        s = self.config('[amazon]\ncredencial_id = "I"\ncredencial_segredo = "S"\ntag_afiliado = "t-20"\n')
        col = LOJAS["amazon"].criar(s, RateLimiter(50))
        self.assertIsInstance(col, amz.AmazonCollector)
        asyncio.run(col.close())


if __name__ == "__main__":
    unittest.main()
