"""Coletor do Mercado Livre usando a API oficial (api.mercadolibre.com).

Autenticação: OAuth2. Rode `python auth_ml.py` uma vez para gerar o token;
depois o coletor renova sozinho com o refresh_token.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from datetime import datetime, timezone

from ..models import Offer, SellerInfo, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.ml")

API = "https://api.mercadolibre.com"
SITE = "MLB"  # Brasil
ITEM_FIELDS = ("id,title,price,original_price,permalink,thumbnail,category_id,shipping,available_quantity,"
               "status,seller_id,condition,catalog_product_id")


class TokenStore:
    def __init__(self, path: Path, client_id: str, client_secret: str):
        self.path = path
        self.client_id = client_id
        self.client_secret = client_secret
        self.data: dict = json.loads(path.read_text()) if path.exists() else {}
        self._lock = asyncio.Lock()

    @property
    def has_token(self) -> bool:
        return bool(self.data.get("refresh_token") or self.data.get("access_token"))

    def save(self, payload: dict) -> None:
        self.data = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", self.data.get("refresh_token")),
            "expires_at": time.time() + int(payload.get("expires_in", 21600)) - 120,
            "user_id": payload.get("user_id", self.data.get("user_id")),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    async def access_token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self.data.get("access_token") and time.time() < self.data.get("expires_at", 0):
                return self.data["access_token"]
            if not self.data.get("refresh_token"):
                raise CollectorError("Mercado Livre sem token. Rode: python auth_ml.py")
            r = await client.post(f"{API}/oauth/token", data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.data["refresh_token"],
            }, headers={"accept": "application/json"})
            if r.status_code != 200:
                raise CollectorError(f"Falha ao renovar token do ML ({r.status_code}): {r.text[:200]}. "
                                     "Rode python auth_ml.py de novo.")
            self.save(r.json())
            log.info("Token do Mercado Livre renovado")
            return self.data["access_token"]


def _to_offer(it: dict, watch: Watch) -> Optional[Offer]:
    if not it or it.get("price") is None:
        return None
    if it.get("status") and it["status"] != "active":
        return None
    thumb = (it.get("thumbnail") or "").replace("http://", "https://")
    seller = it.get("seller") or {}
    return Offer(
        store="mercadolivre",
        item_id=it["id"],
        title=it.get("title", ""),
        price=float(it["price"]),
        original_price=float(it["original_price"]) if it.get("original_price") else None,
        url=it.get("permalink", f"https://produto.mercadolivre.com.br/{it['id']}"),
        thumbnail=thumb,
        category=it.get("category_id", ""),
        free_shipping=bool((it.get("shipping") or {}).get("free_shipping")),
        available_qty=it.get("available_quantity"),
        watch=watch.name,
        seller_id=str(seller.get("id") or it.get("seller_id") or ""),
        seller_name=seller.get("nickname") or "",
        condition=it.get("condition") or "",
        catalog_id=it.get("catalog_product_id") or "",
    )


class MercadoLivreCollector(Collector):
    store = "mercadolivre"

    def __init__(self, client_id: str, client_secret: str, token_path: Path, max_concurrency: int = 4,
                 limiter: Optional[RateLimiter] = None):
        self.tokens = TokenStore(token_path, client_id, client_secret)
        self.client = httpx.AsyncClient(timeout=15, headers={"user-agent": "sniper-ofertas/0.1"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade

    async def _get(self, path: str, params: dict | None = None, fila: str = "normal",
                   timeout: float | None = None) -> dict | list:
        token = await self.tokens.access_token(self.client)
        extra = {"timeout": timeout} if timeout else {}
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{API}{path}", params=params,
                                          headers={"Authorization": f"Bearer {token}"}, **extra)
            status = r.status_code
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 401:
                self.tokens.data["expires_at"] = 0
                token = await self.tokens.access_token(self.client)
                continue
            if status == 403:
                self._penalize(f"ML recusou {path} (403)")
                raise CollectorError(f"ML recusou {path} (403). Confira se o app tem permissão "
                                     f"para esse recurso. Resposta: {r.text[:160]}")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429:
            self._penalize("ML: muitas requisições (429)")
        raise CollectorError(f"ML não respondeu em {path} após várias tentativas")

    def _penalize(self, motivo: str) -> None:
        if self.limiter:
            dur = self.limiter.penalize(motivo)
            log.warning("Mercado Livre pausado por %d min: %s", dur // 60, motivo)

    async def search(self, watch: Watch) -> list[Offer]:
        offers: list[Offer] = []
        for page in range(max(1, watch.max_pages)):
            params = {"limit": 50, "offset": page * 50}
            if watch.query:
                params["q"] = watch.query
            if watch.category:
                params["category"] = watch.category
            data = await self._get(f"/sites/{SITE}/search", params)
            results = data.get("results", [])
            offers += [o for o in (_to_offer(it, watch) for it in results) if o]
            if len(results) < 50:
                break
        return offers

    async def items(self, watch: Watch) -> list[Offer]:
        offers: list[Offer] = []
        ids = watch.item_ids
        for i in range(0, len(ids), 20):
            chunk = ",".join(ids[i:i + 20])
            data = await self._get("/items", {"ids": chunk, "attributes": ITEM_FIELDS})
            for entry in data:
                if entry.get("code") == 200:
                    o = _to_offer(entry.get("body", {}), watch)
                    if o:
                        offers.append(o)
        return offers

    async def collect(self, watch: Watch) -> list[Offer]:
        out: list[Offer] = []
        if watch.item_ids:
            out += await self.items(watch)
        if watch.query or watch.category:
            out += await self.search(watch)
        return out

    async def seller_info(self, offer: Offer) -> Optional[SellerInfo]:
        if not offer.seller_id:
            return None
        u = await self._get(f"/users/{offer.seller_id}")
        rep = u.get("seller_reputation") or {}
        tx = rep.get("transactions") or {}
        days = None
        if u.get("registration_date"):
            try:
                reg = datetime.fromisoformat(u["registration_date"].replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - reg).days
            except ValueError:
                pass
        site_status = (u.get("status") or {}).get("site_status", "active")
        return SellerInfo(seller_id=offer.seller_id, nickname=u.get("nickname", ""),
                          sales=tx.get("completed", tx.get("total")), level=rep.get("level_id"),
                          registered_days=days, status=site_status)

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        it = await self._get(f"/items/{offer.item_id}", {"attributes": ITEM_FIELDS})
        w = Watch(name=offer.watch, store=self.store)
        fresh = _to_offer(it, w)
        if fresh:
            fresh.seller_name = fresh.seller_name or offer.seller_name
            fresh.confirmed = True
        return fresh

    async def close(self) -> None:
        await self.client.aclose()
