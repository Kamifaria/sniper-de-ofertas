"""Mercado Livre: categorias finais, busca do mais barato e refresh em lote."""
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
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402

RAIZES = [{"id": "A"}, {"id": "B"}]
DUMP = {"A": {"children_categories": [{"id": "A1"}, {"id": "A2"}]},
        "A1": {"children_categories": []}, "A2": {"children_categories": []},
        "B": {"children_categories": []}}
NOS = {"A": [{"id": "A1"}], "A1": [], "B": []}


def rodar(handler, fn, limiter=None):
    """Cria o coletor com transporte falso, roda fn(coletor) e devolve o resultado."""
    async def run():
        with tempfile.TemporaryDirectory() as d:
            tok = Path(d) / "tok.json"
            tok.write_text(json.dumps({"access_token": "OK", "refresh_token": "R",
                                       "expires_at": time.time() + 3600}))
            c = mlmod.MercadoLivreCollector("id", "secret", tok, limiter=limiter)
            c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            orig = mlmod.API
            mlmod.API = "https://api.test"
            try:
                return await fn(c)
            finally:
                mlmod.API = orig
                await c.close()
    return asyncio.run(run())


class CategoriasTests(unittest.TestCase):
    def test_folhas_pelo_dump(self):
        calls = []

        def h(req):
            calls.append(req.url.path)
            if req.url.path == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if req.url.path == "/sites/MLB/categories/all":
                return httpx.Response(200, json=DUMP)
            return httpx.Response(404)

        leaves = rodar(h, lambda c: c.sweep_units(Watch(name="v", store="mercadolivre", kind="varrer")))
        self.assertEqual(leaves, ["A1", "A2", "B"])
        self.assertFalse(any(p.startswith("/categories/") for p in calls))

    def test_sem_dump_le_no_a_no(self):
        def h(req):
            p = req.url.path
            if p == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if p == "/sites/MLB/categories/all":
                return httpx.Response(404)
            if p.startswith("/categories/"):
                return httpx.Response(200, json={"children_categories": NOS[p.rsplit("/", 1)[1]]})
            return httpx.Response(404)

        leaves = rodar(h, lambda c: c.sweep_units(Watch(name="v", store="mercadolivre", kind="varrer")))
        self.assertEqual(leaves, ["A1", "B"])

    def test_categorias_escolhidas(self):
        calls = []

        def h(req):
            calls.append(req.url.path)
            if req.url.path == "/sites/MLB/categories/all":
                return httpx.Response(200, json=DUMP)
            return httpx.Response(404)

        w = Watch(name="v", store="mercadolivre", kind="varrer", sweep_categories=["A"])
        self.assertEqual(rodar(h, lambda c: c.sweep_units(w)), ["A1", "A2"])
        self.assertNotIn("/sites/MLB/categories", calls)


class SweepRefreshTests(unittest.TestCase):
    def test_sweep_busca_do_mais_barato(self):
        params = []

        def h(req):
            params.append(dict(req.url.params))
            return httpx.Response(200, json={"results": [
                {"id": "MLB1", "title": "TV", "price": 99.0, "permalink": "https://ml/1", "shipping": {}}]})

        w = Watch(name="v", store="mercadolivre", kind="varrer", max_pages=1)
        offers = rodar(h, lambda c: c.sweep("A1", w))
        self.assertEqual([o.item_id for o in offers], ["MLB1"])
        self.assertEqual((params[0]["category"], params[0]["sort"], params[0]["limit"]), ("A1", "price_asc", "50"))

    def test_refresh_em_lotes_de_20_na_fila_rapida(self):
        lotes = []

        def h(req):
            ids = req.url.params["ids"].split(",")
            lotes.append(len(ids))
            return httpx.Response(200, json=[
                {"code": 200, "body": {"id": i, "title": "X", "price": 10.0, "permalink": "https://ml/x",
                                       "status": "active", "shipping": {}}} for i in ids])

        lim = RateLimiter(1000)
        ids = [f"MLB{i}" for i in range(45)]
        offers = rodar(h, lambda c: c.refresh(ids), limiter=lim)
        self.assertEqual(lotes, [20, 20, 5])
        self.assertEqual(len(offers), 45)
        self.assertEqual({o.watch for o in offers}, {"Fila rápida"})
        self.assertEqual({f for _, f in lim._usos}, {"rapida"})


if __name__ == "__main__":
    unittest.main()
