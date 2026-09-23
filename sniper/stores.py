"""Registro de lojas: nome, etiqueta oficial/não oficial, limite padrão e como criar o coletor.

Para ligar uma loja nova: escreva o coletor em sniper/collectors/ e acrescente uma LojaInfo em LOJAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .collectors import Collector, MercadoLivreCollector, VtexCollector
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


def _vtex(chave: str, dominio: str) -> Callable[[Settings, RateLimiter], Optional[Collector]]:
    return lambda s, lim: VtexCollector(chave, dominio, limiter=lim)


# Lojas VTEX cuja busca pública respondeu sem login (conferido em 2026-09-23).
# Fora: Farm Rio (busca passa de 45 s); Riachuelo, Centauro, Carrefour, Casas Bahia, Magalu etc. bloqueiam (403).
VTEX = [
    ("cea", "C&A", "www.cea.com.br"),
    ("tokstok", "Tok&Stok", "www.tokstok.com.br"),
    ("cobasi", "Cobasi", "www.cobasi.com.br"),
    ("paguemenos", "Pague Menos", "www.paguemenos.com.br"),
    ("americanas", "Americanas", "www.americanas.com.br"),
    ("telhanorte", "Telhanorte", "www.telhanorte.com.br"),
    ("samsclub", "Sam's Club", "www.samsclub.com.br"),
    ("drogariasaopaulo", "Drogaria São Paulo", "www.drogariasaopaulo.com.br"),
    ("pacheco", "Drogarias Pacheco", "www.drogariaspacheco.com.br"),
    ("atacadao", "Atacadão", "www.atacadao.com.br"),
]

LOJAS: dict[str, LojaInfo] = {i.chave: i for i in [
    LojaInfo("mercadolivre", "Mercado Livre", True, _mercadolivre, 60,
             "Preencha [mercadolivre] no config.toml e rode python auth_ml.py"),
    *(LojaInfo(chave, nome, False, _vtex(chave, dominio), 30) for chave, nome, dominio in VTEX),
]}
