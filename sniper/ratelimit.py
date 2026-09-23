"""Limite de consultas por loja: fichas por minuto + pausa em degraus quando a loja bloqueia."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable, Optional

DEGRAUS_S = (60, 300, 900, 3600)   # pausa de 1, 5, 15 e 60 minutos
COTA_RAPIDA = 0.5                  # a fila rápida usa no máximo metade das consultas da loja
JANELA_S = 60.0
MAX_ESPERA_S = 5.0                 # reavalia a cada 5 s enquanto espera


class RateLimiter:
    def __init__(self, por_minuto: int, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.por_minuto = max(1, int(por_minuto))
        self.clock = clock
        self.sleep = sleep
        self._usos: deque[tuple[float, str]] = deque()  # (instante, fila) das consultas no último minuto
        self._lock = asyncio.Lock()
        self.pausada_ate: Optional[float] = None
        self.degrau = 0
        self.motivo = ""

    def _limpa(self, agora: float) -> None:
        while self._usos and agora - self._usos[0][0] >= JANELA_S:
            self._usos.popleft()

    def _espera(self, fila: str, agora: float) -> float:
        if self.pausada_ate is not None and agora < self.pausada_ate:
            return self.pausada_ate - agora
        self._limpa(agora)
        if len(self._usos) >= self.por_minuto:
            return JANELA_S - (agora - self._usos[0][0])
        if fila == "rapida":
            rapidas = [t for t, f in self._usos if f == "rapida"]
            if len(rapidas) >= max(1, int(self.por_minuto * COTA_RAPIDA)):
                return JANELA_S - (agora - rapidas[0])
        return 0.0

    async def acquire(self, fila: str = "normal") -> None:
        """Espera até poder fazer uma consulta. fila="rapida" respeita o teto da fila rápida."""
        while True:
            async with self._lock:
                agora = self.clock()
                espera = self._espera(fila, agora)
                if espera <= 0:
                    self._usos.append((agora, fila))
                    return
            await self.sleep(min(espera, MAX_ESPERA_S))

    def penalize(self, motivo: str = "") -> float:
        """A loja bloqueou (429/403): pausa por um degrau maior a cada vez. Retorna os segundos de pausa."""
        dur = DEGRAUS_S[min(self.degrau, len(DEGRAUS_S) - 1)]
        self.degrau += 1
        self.pausada_ate = self.clock() + dur
        self.motivo = motivo
        return dur

    def success(self) -> None:
        self.degrau = 0

    @property
    def pausada(self) -> bool:
        return self.pausada_ate is not None and self.clock() < self.pausada_ate

    def estado(self) -> dict:
        self._limpa(self.clock())
        pausada = self.pausada
        return {"pausada_ate": self.pausada_ate if pausada else None, "degrau": self.degrau,
                "ultimo_minuto": len(self._usos), "limite": self.por_minuto,
                "motivo": self.motivo if pausada else ""}
