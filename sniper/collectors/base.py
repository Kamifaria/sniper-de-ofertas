from __future__ import annotations

from abc import ABC, abstractmethod

from typing import Optional

from ..models import Offer, SellerInfo, Watch


class CollectorError(Exception):
    """Erro de coleta que deve aparecer no painel (credencial, bloqueio, etc.)."""


class Collector(ABC):
    store: str = ""

    @abstractmethod
    async def collect(self, watch: Watch) -> list[Offer]:
        ...

    async def seller_info(self, offer: Offer) -> Optional[SellerInfo]:
        """Dados do vendedor (vendas, idade da conta). None = loja não informa."""
        return None

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        """Relê o anúncio direto na loja. Retorna a oferta atualizada, ou None se sumiu/esgotou.
        Por padrão devolve a mesma oferta (loja sem suporte a reconfirmação)."""
        return offer

    async def close(self) -> None:  # pragma: no cover
        pass
