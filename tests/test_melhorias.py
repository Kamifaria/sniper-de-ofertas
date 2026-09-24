"""Melhorias de caça a bugs: menos falso positivo, lojas escolhidas no painel, log/CSV, comparação entre lojas."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, oferta  # noqa: E402
from sniper import config, stores  # noqa: E402
from sniper.collectors.base import Collector  # noqa: E402
from sniper.config import LojaConfig, Settings  # noqa: E402
from sniper.db import ean_valido  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.detector import DetectorConfig  # noqa: E402
from sniper.models import Offer, Watch  # noqa: E402
from sniper.server import create_app  # noqa: E402
from sniper.stores import LojaInfo  # noqa: E402

EAN = "7891000100103"  # GTIN-13 válido


def o(price, **kw):
    return Offer(store="t", item_id="X", title="Produto", price=price, url="https://x", **kw)


class GratisTests(unittest.TestCase):
    def test_item_barato_que_ficou_mais_barato_nao_e_gratis(self):
        v = evaluate(o(0.78), [1.18] * 5)
        self.assertNotEqual(v.level, "GRATIS")
        self.assertEqual(v.level, "NENHUM")

    def test_item_caro_a_centavos_e_gratis(self):
        self.assertEqual(evaluate(o(0.50), [120.0] * 5).level, "GRATIS")

    def test_sem_historico_continua_gratis(self):
        self.assertEqual(evaluate(o(0.0), []).level, "GRATIS")

    def test_referencia_minima_configuravel(self):
        v = evaluate(o(0.9), [4.0] * 5, cfg=DetectorConfig(free_min_ref=3.0))
        self.assertEqual(v.level, "GRATIS")


class EanTests(unittest.TestCase):
    def test_ean_valido(self):
        self.assertTrue(ean_valido(EAN))
        self.assertTrue(ean_valido("7896779800711"))
        for ruim in ("", "123456789101112", "2000000000003", "0000000000000", "7891000100104", "abc", "12345"):
            self.assertFalse(ean_valido(ruim), ruim)


class RepeticaoTests(unittest.TestCase):
    def test_mesmo_preco_nao_repete_em_24h(self):
        with MotorDeTeste() as m:
            db = m.engine.db
            a = o(100.0, collected_at=time.time() - 5 * 3600)
            db.save_alert(a, evaluate(a, [1000.0] * 5))
            self.assertFalse(m.engine._should_alert("t", "X", 100.0))
            self.assertTrue(m.engine._should_alert("t", "X", 90.0))  # caiu mais 5%+

    def test_depois_de_24h_pode_repetir(self):
        with MotorDeTeste() as m:
            a = o(100.0, collected_at=time.time() - 25 * 3600)
            m.engine.db.save_alert(a, evaluate(a, [1000.0] * 5))
            self.assertTrue(m.engine._should_alert("t", "X", 100.0))

    def test_nota_minima_padrao_e_70(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("", encoding="utf-8")
            self.assertEqual(config.load(p).min_alert_score, 70)


class SemConcorrenteNaMesmaLoja(FakeCollector):
    peers_mesma_loja = False


class ConcorrentesTests(unittest.TestCase):
    def test_mesmo_ean_na_mesma_loja_nao_vira_referencia(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            col = SemConcorrenteNaMesmaLoja()
            offers = [oferta("A", 483.0, catalog=EAN), oferta("B", 480.0, catalog=EAN),
                      oferta("C", 470.0, catalog=EAN), oferta("D", 14.9, catalog=EAN)]
            self.assertEqual(asyncio.run(m.engine._process(w, col, offers))["alertas"], 0)

    def _outras_lojas(self, db, ean, precos=(100.0, 102.0)):
        for loja, p in zip(("loja1", "loja2"), precos):
            db.save_offer(Offer(store=loja, item_id="Z", title="Produto", price=p, url="https://x", catalog_id=ean))

    def test_muito_abaixo_de_outras_lojas_alerta(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            self._outras_lojas(m.engine.db, EAN)
            col = SemConcorrenteNaMesmaLoja()
            r = asyncio.run(m.engine._process(w, col, [oferta("D", 12.0, catalog=EAN)]))
            self.assertEqual(r["alertas"], 1)
            self.assertTrue(any("concorrentes" in x for x in m.engine.db.list_alerts()[0]["reasons"]))

    def test_ean_invalido_nao_compara_entre_lojas(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            self._outras_lojas(m.engine.db, "123456789101112")
            r = asyncio.run(m.engine._process(w, SemConcorrenteNaMesmaLoja(),
                                              [oferta("D", 12.0, catalog="123456789101112")]))
            self.assertEqual(r["alertas"], 0)

    def test_ean_repetido_na_outra_loja_nao_conta(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            db = m.engine.db
            self._outras_lojas(db, EAN)
            # loja1 usa o mesmo EAN em dois produtos (unidade x caixa): fica fora da comparação
            db.save_offer(Offer(store="loja1", item_id="Z2", title="Caixa", price=900.0, url="https://x",
                                catalog_id=EAN))
            r = asyncio.run(m.engine._process(w, SemConcorrenteNaMesmaLoja(), [oferta("D", 12.0, catalog=EAN)]))
            self.assertEqual(r["alertas"], 0)  # sobra só 1 loja de referência (< 2)


class LojaFalsa(Collector):
    supports_sweep = True

    def __init__(self, chave):
        self.store = chave
        self.fechado = False

    async def collect(self, watch):
        return []

    async def sweep_units(self, watch):
        return []

    async def close(self):
        self.fechado = True


def registro_falso():
    return {"falsa": LojaInfo("falsa", "Loja Falsa", False, lambda s, lim: LojaFalsa("falsa"), 30),
            "outra": LojaInfo("outra", "Outra", False, lambda s, lim: LojaFalsa("outra"), 30)}


class EscolherLojasTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(stores.LOJAS, registro_falso(), clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_liga_desliga_e_lembra(self):
        with MotorDeTeste(lojas={"falsa": LojaConfig(ativo=True)}) as m:
            eng = m.engine
            eng.paused = True

            async def go():
                await eng.start()
                self.assertIn("Varredura Loja Falsa", eng.watch_status)  # varredura automática
                col = eng.collectors["falsa"]
                await eng.set_store_active("falsa", False)
                self.assertNotIn("falsa", eng.collectors)
                self.assertTrue(col.fechado)
                self.assertEqual(eng.watch_status["Varredura Loja Falsa"]["state"], "loja desligada")
                await eng.set_store_active("outra", True)
                self.assertIn("outra", eng.collectors)
                self.assertIn("Varredura Outra", eng.watch_status)
                await eng.stop()
            asyncio.run(go())

            eng2 = m.reabrir()  # a escolha fica salva no banco
            self.assertNotIn("falsa", eng2.collectors)
            self.assertIn("outra", eng2.collectors)
            info = {x["chave"]: x["ativa"] for x in eng2.lojas_info()}
            self.assertEqual(info, {"falsa": False, "outra": True})

    def test_regra_do_config_nao_duplica_varredura(self):
        w = Watch(name="Minha varredura", store="falsa", kind="varrer")
        with MotorDeTeste(watches=[w], lojas={"falsa": LojaConfig(ativo=True)}) as m:
            eng = m.engine
            eng.paused = True

            async def go():
                await eng.start()
                self.assertIn("Minha varredura", eng.watch_status)
                self.assertNotIn("Varredura Loja Falsa", eng.watch_status)
                await eng.stop()
            asyncio.run(go())


class ApiTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(stores.LOJAS, registro_falso(), clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.app = create_app(Settings(base_dir=base, db_path=base / "t.db", windows_on=False))
        self.addCleanup(self.app.state.engine.db.conn.close)
        self.client = TestClient(self.app)

    def test_post_liga_loja(self):
        r = self.client.post("/api/lojas/outra", json={"ativo": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(next(x for x in r.json() if x["chave"] == "outra")["ativa"])
        self.assertEqual(self.client.post("/api/lojas/nao-existe", json={"ativo": True}).status_code, 404)

    def test_csv_do_periodo(self):
        db = self.app.state.engine.db
        velho = o(10.0, collected_at=time.time() - 3 * 86400)
        novo = Offer(store="t", item_id="N", title="TV 55, 4K", price=199.0, url="https://x/tv")
        db.save_alert(velho, evaluate(velho, [1000.0] * 5))
        db.save_alert(novo, evaluate(novo, [2000.0] * 5))
        r = self.client.get("/api/alerts.csv", params={"since": time.time() - 86400})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        linhas = r.text.strip().splitlines()
        self.assertEqual(len(linhas), 2)  # cabeçalho + o alerta de hoje
        self.assertIn('"TV 55, 4K"', linhas[1])
        self.assertIn("https://x/tv", linhas[1])


if __name__ == "__main__":
    unittest.main()
