"""Coletor genérico para lojas Shopify, pela lista pública de produtos (/products.json, sem login).

Endpoint não oficial para terceiros: a loja pode bloquear ou mudar sem aviso.
Uma instância por loja (chave + domínio), registrada em sniper/stores.py. Cada variante (tom, tamanho) é
uma oferta própria; os catálogos de maquiagem são pequenos, então a varredura lê tudo.
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..models import Offer, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.shopify")

POR_PAGINA = 250  # máximo da Shopify
MAX_PAGINAS = 12  # 3.000 produtos: sobra para qualquer loja de beleza


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def _preco(v) -> Optional[float]:
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    return p if p >= 0 else None


def _to_offers(prod: dict, store: str, watch: Watch, base: str) -> list[Offer]:
    handle = prod.get("handle") or ""
    if not handle:
        return []
    imgs = prod.get("images") or []
    offers = []
    for v in prod.get("variants") or []:
        preco = _preco(v.get("price"))
        if preco is None or not v.get("available", True):
            continue
        vid = str(v.get("id") or "")
        if not vid:
            continue
        de = _preco(v.get("compare_at_price"))
        nome_var = (v.get("title") or "").strip()
        titulo = prod.get("title") or ""
        if nome_var and nome_var != "Default Title":
            titulo = f"{titulo} - {nome_var}"
        offers.append(Offer(
            store=store,
            item_id=vid,
            title=titulo,
            price=preco,
            original_price=de if de and de > preco else None,
            url=f"{base}/products/{handle}?variant={vid}",
            thumbnail=(imgs[0].get("src") or "") if imgs else "",
            category=prod.get("product_type") or "",
            watch=watch.name,
            condition="new",
            brand=prod.get("vendor") or "",
            official_seller=True,  # a própria marca vende
            cart_url=f"{base}/cart/{vid}:1",
        ))
    return offers


class ShopifyCollector(Collector):
    supports_sweep = True
    supports_refresh = False  # a Shopify não deixa ler uma variante pelo id; a releitura vai pelo confirm()
    peers_mesma_loja = False  # sem código de barras público: a referência é o histórico do item
    precos_simbolicos = True  # brindes e cartões de amostra aparecem a R$ 0,00/0,01: só alerta se CAIU para isso

    def __init__(self, chave: str, dominio: str, limiter: Optional[RateLimiter] = None, max_concurrency: int = 2):
        self.store = chave
        self.base = f"https://{dominio}"
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=True,
                                        headers={"user-agent": "Mozilla/5.0 (sniper-ofertas)"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade

    async def _get(self, path: str, params=None, fila: str = "normal") -> Optional[dict]:
        """None = 404 (produto que saiu do ar)."""
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{self.base}{path}", params=params)
            status = r.status_code
            if status == 404:
                return None
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status in (401, 403):
                if self.limiter:
                    self.limiter.penalize(f"{self.store} recusou {path} ({status})")
                raise CollectorError(f"{self.store} bloqueou a consulta ({status})")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429 and self.limiter:
            self.limiter.penalize(f"{self.store}: muitas requisições (429)")
        raise CollectorError(f"{self.store} não respondeu em {path} após várias tentativas (HTTP {status})")

    async def _catalogo(self, watch: Watch) -> list[Offer]:
        offers: list[Offer] = []
        for pagina in range(1, MAX_PAGINAS + 1):
            data = await self._get("/products.json", {"limit": POR_PAGINA, "page": pagina})
            prods = (data or {}).get("products") or []
            for p in prods:
                offers += _to_offers(p, self.store, watch, self.base)
            if len(prods) < POR_PAGINA:
                break
        return offers

    async def sweep_units(self, watch: Watch) -> list[str]:
        return ["all"]

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        return await self._catalogo(watch)

    async def collect(self, watch: Watch) -> list[Offer]:
        termos = _sem_acento(watch.query).split()
        if not termos:
            return []
        achados = []
        for o in await self._catalogo(watch):
            texto = _sem_acento(o.title)
            if all(t in texto for t in termos):
                achados.append(o)
        return achados

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        """Relê o produto (/products/{handle}.js, preço em centavos) e acha a variante. None se esgotou."""
        handle = urlparse(offer.url).path.rsplit("/", 1)[-1]
        data = await self._get(f"/products/{handle}.js")
        v = next((x for x in (data or {}).get("variants") or [] if str(x.get("id")) == offer.item_id), None)
        if not v or not v.get("available", True) or v.get("price") is None:
            return None
        preco = v["price"] / 100
        de = (v.get("compare_at_price") or 0) / 100
        fresh = Offer(**offer.__dict__)
        fresh.price = preco
        fresh.original_price = de if de > preco else None
        fresh.confirmed = True
        return fresh

    async def close(self) -> None:
        await self.client.aclose()
