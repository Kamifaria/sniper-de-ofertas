"""Limite de consultas por loja."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.ratelimit import RateLimiter  # noqa: E402


class Relogio:
    """Relógio falso: sleep() só avança o tempo."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.r = Relogio()

    def lim(self, n):
        return RateLimiter(n, clock=self.r, sleep=self.r.sleep)

    def test_respeita_limite_por_minuto(self):
        lim = self.lim(3)

        async def go():
            for _ in range(3):
                await lim.acquire()
            self.assertEqual(self.r.t, 1000.0)
            await lim.acquire()

        asyncio.run(go())
        self.assertGreaterEqual(self.r.t, 1060.0)
        self.assertLess(self.r.t, 1061.0)

    def test_fila_rapida_usa_no_maximo_metade(self):
        lim = self.lim(4)

        async def go():
            await lim.acquire("rapida")
            await lim.acquire("rapida")
            await lim.acquire("normal")        # a fila normal não espera
            self.assertEqual(self.r.t, 1000.0)
            await lim.acquire("rapida")        # 3ª rápida no mesmo minuto: espera

        asyncio.run(go())
        self.assertGreaterEqual(self.r.t, 1060.0)

    def test_pausa_em_degraus(self):
        lim = self.lim(60)
        self.assertEqual([lim.penalize("429") for _ in range(5)], [60, 300, 900, 3600, 3600])

    def test_acquire_espera_o_fim_da_pausa(self):
        lim = self.lim(60)
        lim.penalize("bloqueio")
        e = lim.estado()
        self.assertEqual((e["pausada_ate"], e["motivo"]), (1060.0, "bloqueio"))
        self.assertTrue(lim.pausada)
        asyncio.run(lim.acquire())
        self.assertGreaterEqual(self.r.t, 1060.0)
        self.assertIsNone(lim.estado()["pausada_ate"])
        self.assertEqual(lim.estado()["motivo"], "")

    def test_sucesso_zera_degrau(self):
        lim = self.lim(60)
        lim.penalize()
        lim.penalize()
        lim.success()
        self.assertEqual(lim.degrau, 0)
        self.assertEqual(lim.penalize(), 60)

    def test_estado_conta_ultimo_minuto(self):
        lim = self.lim(10)

        async def go():
            await lim.acquire()
            await lim.acquire()

        asyncio.run(go())
        e = lim.estado()
        self.assertEqual((e["ultimo_minuto"], e["limite"], e["degrau"]), (2, 10, 0))
        self.r.t += 61
        self.assertEqual(lim.estado()["ultimo_minuto"], 0)


if __name__ == "__main__":
    unittest.main()
