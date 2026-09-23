"""Registro de lojas: nome, etiqueta oficial/não oficial, limite padrão e como criar o coletor.

Para ligar uma loja nova: escreva o coletor em sniper/collectors/ e acrescente uma LojaInfo em LOJAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .collectors import Collector, MercadoLivreCollector
from .config import Settings
from .ratelimit import RateLimiter


@dataclass
class LojaInfo:
    chave: str
    nome: str
    oficial: bool                                                   # API oficial (True) ou endpoint público (False)
    criar: Callable[[Settings, RateLimiter], Optional[Collector]]   # None = falta credencial
    por_minuto: int                                                 # limite padrão de consultas
    motivo_sem_config: str = ""                                     # mostrado quando criar() devolve None


def _mercadolivre(s: Settings, lim: RateLimiter) -> Optional[Collector]:
    if not s.ml_client_id:
        return None
    return MercadoLivreCollector(s.ml_client_id, s.ml_client_secret,
                                 s.base_dir / "data" / "ml_token.json", limiter=lim)


LOJAS: dict[str, LojaInfo] = {i.chave: i for i in [
    LojaInfo("mercadolivre", "Mercado Livre", True, _mercadolivre, 60,
             "Preencha [mercadolivre] no config.toml e rode python auth_ml.py"),
]}
