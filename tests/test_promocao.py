"""Promoção comum (de/por da loja) e bug de preço aparecem separados."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, NotificadorFalso, oferta  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.notify import format_text  # noqa: E402

HIST = [1000.0, 1000.0, 1000.0]


class DetectorPromoTests(unittest.TestCase):
    def test_de_por_de_40_por_cento_e_promocao(self):
        v = evaluate(oferta("A", 600.0, original_price=1000.0), [])
        self.assertEqual((v.level, v.tipo), ("PROMO", "PROMO"))
        self.assertTrue(v.is_alert)
        self.assertEqual((v.ref_price, round(v.drop_pct, 2)), (1000.0, 0.40))
        self.assertIn("Promoção da loja", v.reasons[0])

    def test_desconto_pequeno_nao_e_nada(self):
        v = evaluate(oferta("A", 800.0, original_price=1000.0), [])
        self.assertEqual((v.level, v.tipo), ("NENHUM", ""))

    def test_sem_preco_de_nao_e_promocao(self):
        self.assertEqual(evaluate(oferta("A", 100.0), []).level, "NENHUM")

    def test_queda_forte_no_historico_continua_sendo_bug_mesmo_com_de_por(self):
        v = evaluate(oferta("A", 100.0, original_price=1000.0), HIST)
        self.assertEqual(v.tipo, "BUG")
        self.assertNotEqual(v.level, "PROMO")

    def test_bug_tem_tipo_bug(self):
        self.assertEqual(evaluate(oferta("A", 0.5), []).tipo, "BUG")


class AlertaPromoTests(unittest.TestCase):
    def test_texto_de_promocao_nao_diz_bug(self):
        a = {"level": "PROMO", "score": 40, "title": "Tênis", "price": 600.0, "ref_price": 1000.0,
             "drop_pct": 0.4, "reasons": ["Promoção da loja: 40% abaixo do preço \"de\""], "url": "https://l/p"}
        t = format_text(a)
        self.assertIn("PROMOÇÃO", t.splitlines()[0])
        self.assertNotIn("BUG DE PREÇO", t)

    def test_motor_grava_promocao_com_tipo_e_nao_notifica(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            n = NotificadorFalso()
            enviados = []

            async def send(a):
                enviados.append(a)
            n.send = send
            m.engine.notifiers.append(n)
            col = FakeCollector()
            m.engine.collectors["t"] = col

            async def roda():
                r = await m.engine._process(w, col, [oferta("P", 600.0, catalog="", original_price=1000.0)])
                await asyncio.sleep(0)
                return r
            r = asyncio.run(roda())
            self.assertEqual(r["alertas"], 1)
            a = m.engine.db.list_alerts()[0]
            self.assertEqual((a["tipo"], a["level"], a["bug"]), ("PROMO", "PROMO", ""))
            self.assertEqual(enviados, [])  # promoção só aparece no painel

    def test_motor_marca_bug_com_tipo_bug(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            m.engine.collectors["t"] = col
            asyncio.run(m.engine._process(w, col, [oferta("A", 4900), oferta("B", 5000), oferta("C", 4950),
                                                   oferta("D", 490)]))
            self.assertEqual(m.engine.db.list_alerts()[0]["tipo"], "BUG")

    def test_limpar_alertas_apaga_so_os_alertas(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            m.engine.collectors["t"] = col
            asyncio.run(m.engine._process(w, col, [oferta("P", 600.0, catalog="", original_price=1000.0)]))
            self.assertEqual(m.engine.db.limpar_alertas(), 1)
            self.assertEqual(m.engine.db.list_alerts(), [])
            self.assertEqual(m.engine.db.history("t", "P"), [600.0])  # histórico de preço fica


if __name__ == "__main__":
    unittest.main()
