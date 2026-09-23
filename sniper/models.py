"""Estruturas de dados compartilhadas pelo motor."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Offer:
    """Uma leitura de preço de um item em uma loja."""
    store: str                      # chave da loja em sniper/stores.py (ex.: "mercadolivre")
    item_id: str
    title: str
    price: float
    url: str
    original_price: Optional[float] = None   # preço "de" que a loja mostra
    thumbnail: str = ""
    category: str = ""
    free_shipping: bool = False
    available_qty: Optional[int] = None
    watch: str = ""                  # nome da regra de vigilância que achou o item
    seller_id: str = ""
    seller_name: str = ""
    condition: str = ""              # "new", "used", "" (desconhecido)
    catalog_id: str = ""             # id do produto de catálogo (mesmo produto, vários vendedores)
    confirmed: bool = False          # preço reconfirmado direto no anúncio antes do alerta
    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SellerInfo:
    """Dados do vendedor usados para descartar lojas de teste."""
    seller_id: str
    nickname: str = ""
    sales: Optional[int] = None          # vendas concluídas
    level: Optional[str] = None          # termômetro de reputação (ex.: "5_green")
    registered_days: Optional[int] = None  # há quantos dias a conta existe
    status: str = "active"


@dataclass
class Watch:
    """Uma regra de vigilância vinda do config.toml."""
    name: str
    store: str
    query: str = ""
    category: str = ""
    item_ids: list[str] = field(default_factory=list)
    interval: int = 120              # segundos entre coletas
    floor: Optional[float] = None    # preço abaixo disso é suspeito
    max_pages: int = 1
    min_price: Optional[float] = None  # ignora itens baratos demais por natureza (capinhas etc.)
    exclude_words: list[str] = field(default_factory=list)  # palavras extras para descartar
    allow_used: bool = False         # aceitar produtos usados nesta regra


@dataclass
class Verdict:
    """Resultado do detector para uma oferta."""
    score: int
    level: str                       # GRATIS, CRITICO, ALTO, MEDIO, NENHUM
    reasons: list[str]
    ref_price: Optional[float]       # preço de referência (mediana do histórico, concorrentes ou "de")
    drop_pct: Optional[float]        # queda em relação à referência (0-1)

    @property
    def is_alert(self) -> bool:
        return self.level != "NENHUM"
