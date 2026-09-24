from __future__ import annotations

from abc import ABC, abstractmethod

from typing import Optional

from ..models import Offer, SellerInfo, Watch


class CollectorError(Exception):
    """Erro de coleta que deve aparecer no painel (credencial, bloqueio, etc.)."""


class Collector(ABC):
    store: str = ""
    supports_sweep: bool = False     # implementa sweep_units() + sweep()
    supports_refresh: bool = False   # implementa refresh() (fila rápida)
    refresh_por_catalogo: bool = False  # refresh() recebe ids de produto do catálogo em vez de anúncio (ML)
    peers_mesma_loja: bool = True    # compara vendedores do mesmo produto na própria loja (ML)
    precos_simbolicos: bool = False  # loja mostra R$ 0,00/0,01 em item sem preço: só alerta se CAIU para isso

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

    async def sweep_units(self, watch: Watch) -> list[str]:
        """Unidades de varredura (ex.: categorias finais), em ordem estável."""
        raise NotImplementedError

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        """Lê uma unidade de varredura."""
        raise NotImplementedError

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        """Relê vários itens de uma vez (fila rápida)."""
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover
        pass
