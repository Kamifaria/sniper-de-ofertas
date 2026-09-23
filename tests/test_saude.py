"""Aviso de loja travada e resumo diário."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, NotificadorFalso, oferta  # noqa: E402
from sniper import config  # noqa: E402
from sniper.collectors import CollectorError  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402


def hoje_as(h, m):
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))


class TravadaTests(unittest.TestCase):
    def test_avisa_uma_vez_depois_de_30_min_e_avisa_a_volta(self):
        with MotorDeTeste(telegram_resumo="") as m:
            eng, n = m.engine, NotificadorFalso()
            eng.notifiers = [n]
            t0 = time.time()
            eng._store_fail("t", "sem internet", now=t0)
            asyncio.run(eng.health_check(now=t0 + 29 * 60))
            self.assertEqual(n.textos, [])
            asyncio.run(eng.health_check(now=t0 + 31 * 60))
            asyncio.run(eng.health_check(now=t0 + 40 * 60))
            self.assertEqual(len(n.textos), 1)
            self.assertIn("sem internet", n.textos[0])
            asyncio.run(eng._store_ok("t"))
            self.assertEqual(len(n.textos), 2)
            self.assertIn("voltou", n.textos[1])
            self.assertEqual(eng.store_errors, {})

    def test_volta_sem_aviso_previo_nao_manda_nada(self):
        with MotorDeTeste(telegram_resumo="") as m:
            n = NotificadorFalso()
            m.engine.notifiers = [n]
            m.engine._store_fail("t", "erro rápido")
            asyncio.run(m.engine._store_ok("t"))
            self.assertEqual(n.textos, [])

    def test_notificador_que_muda_store_errors_nao_derruba_health_check(self):
        with MotorDeTeste(telegram_resumo="") as m:
            eng = m.engine

            class NotificadorTraiçoeiro:
                def __init__(self, eng):
                    self.eng = eng
                    self.textos = []

                async def send_text(self, text):
                    self.textos.append(text)
                    self.eng._store_fail("outra", "x")

            n = NotificadorTraiçoeiro(eng)
            eng.notifiers = [n]
            t0 = time.time()
            eng._store_fail("t", "sem internet", now=t0)
            asyncio.run(eng.health_check(now=t0 + 31 * 60))
            self.assertEqual(len(n.textos), 1)
            self.assertIn("sem internet", n.textos[0])

    def test_loja_pausada_conta_como_problema(self):
        with MotorDeTeste(telegram_resumo="") as m:
            lim = RateLimiter(60)
            lim.penalize("429")
            m.engine.limiters["t"] = lim
            asyncio.run(m.engine.health_check())
            self.assertIn("pausada", m.engine.store_errors["t"]["msg"])

    def test_run_watch_registra_falha_e_sucesso(self):
        class Quebra(FakeCollector):
            quebrar = True

            async def collect(self, watch):
                if self.quebrar:
                    raise CollectorError("ML fora do ar")
                return [oferta("A", 100.0, title="Produto", catalog="")]

        w = Watch(name="w", store="t")
        with MotorDeTeste(watches=[w], telegram_resumo="") as m:
            col = Quebra()
            m.engine.collectors["t"] = col
            m.engine.watch_status["w"] = {}
            asyncio.run(m.engine.run_watch(w))
            self.assertEqual(m.engine.store_errors["t"]["msg"], "ML fora do ar")
            col.quebrar = False
            asyncio.run(m.engine.run_watch(w))
            self.assertEqual(m.engine.store_errors, {})


class ResumoTests(unittest.TestCase):
    def test_manda_um_resumo_por_dia_depois_do_horario(self):
        with MotorDeTeste(telegram_resumo="09:00") as m:
            eng, n = m.engine, NotificadorFalso()
            eng.notifiers = [n]
            eng._last_summary = None
            asyncio.run(eng.health_check(now=hoje_as(8, 59)))
            self.assertEqual(n.textos, [])
            asyncio.run(eng.health_check(now=hoje_as(9, 1)))
            asyncio.run(eng.health_check(now=hoje_as(15, 0)))
            self.assertEqual(len(n.textos), 1)
            self.assertIn("últimas 24 h", n.textos[0])

    def test_resumo_desligado(self):
        with MotorDeTeste(telegram_resumo="") as m:
            n = NotificadorFalso()
            m.engine.notifiers = [n]
            m.engine._last_summary = None
            asyncio.run(m.engine.health_check(now=hoje_as(9, 1)))
            self.assertEqual(n.textos, [])

    def test_config_telegram(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[telegram]\nresumo_diario = "08:30"\navisar_travada_minutos = 10\n', encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.telegram_resumo, s.telegram_travada_min), ("08:30", 10))

    def test_config_resumo_invalido_da_erro_claro(self):
        for valor in ("9h", "25:00", "09:60", "09"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "config.toml"
                p.write_text(f'[telegram]\nresumo_diario = "{valor}"\n', encoding="utf-8")
                with self.assertRaises(ValueError) as ctx:
                    config.load(p)
                self.assertIn("resumo_diario", str(ctx.exception))

    def test_config_resumo_aceita_hora_de_um_digito(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[telegram]\nresumo_diario = "9:05"\n', encoding="utf-8")
            s = config.load(p)
        self.assertEqual(s.telegram_resumo, "09:05")


if __name__ == "__main__":
    unittest.main()
