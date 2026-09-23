"""Motor: roda cada regra de vigilância no seu intervalo, avalia e dispara alertas."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections import defaultdict

from . import detector, filters
from .collectors import Collector, CollectorError
from .config import Settings
from .db import Database
from .models import Offer, SellerInfo, Verdict, Watch
from .notify import TelegramNotifier, WindowsNotifier
from .ratelimit import RateLimiter
from .stores import LOJAS

log = logging.getLogger("sniper.engine")


class Engine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.db = Database(settings.db_path)
        self.collectors: dict[str, Collector] = {}
        self.notifiers: list = []
        self.subscribers: set[asyncio.Queue] = set()
        self.events: deque[dict] = deque(maxlen=300)
        self.watch_status: dict[str, dict] = {}
        self.paused = False
        self._tasks: list[asyncio.Task] = []

        self.limiters: dict[str, RateLimiter] = {}
        self.store_status: dict[str, dict] = {}
        for chave, info in LOJAS.items():
            lc = settings.lojas.get(chave)
            if not lc or not lc.ativo:
                continue
            lim = RateLimiter(lc.por_minuto or info.por_minuto)
            self.limiters[chave] = lim
            col = info.criar(settings, lim)
            if col is None:
                self.store_status[chave] = {"configurada": False, "motivo": info.motivo_sem_config}
                continue
            self.collectors[chave] = col
            self.store_status[chave] = {"configurada": True, "motivo": ""}
        if settings.telegram_on and settings.telegram_token:
            self.notifiers.append(TelegramNotifier(settings.telegram_token, settings.telegram_chat_id,
                                                   settings.telegram_min_score))
        if settings.windows_on:
            self.notifiers.append(WindowsNotifier(settings.windows_min_score))

    # ---------- eventos para o painel ----------
    def emit(self, kind: str, **data) -> None:
        ev = {"type": kind, "ts": time.time(), **data}
        if kind != "alert":
            self.events.append(ev)
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    def log(self, level: str, msg: str) -> None:
        getattr(log, level if level != "erro" else "error", log.info)(msg)
        self.emit("log", level=level, msg=msg)

    def _motivo_sem_coletor(self, store: str) -> str:
        info = LOJAS.get(store)
        if info is None:
            return f"Loja '{store}' não existe"
        lc = self.s.lojas.get(store)
        if lc is not None and not lc.ativo:
            return f"Loja '{store}' desligada. Use [lojas.{store}] ativo = true no config.toml"
        return info.motivo_sem_config

    # ---------- ciclo ----------
    async def start(self) -> None:
        for w in self.s.watches:
            if w.store not in self.collectors:
                self.watch_status[w.name] = {"store": w.store, "state": "sem coletor",
                                             "error": self._motivo_sem_coletor(w.store),
                                             "count": 0, "interval": w.interval}
                continue
            self.watch_status[w.name] = {"store": w.store, "state": "aguardando", "last_run": None,
                                         "count": 0, "error": None, "interval": w.interval,
                                         "duration": None}
            self._tasks.append(asyncio.create_task(self._loop(w)))
        self._tasks.append(asyncio.create_task(self._housekeeping()))
        self.log("info", f"Motor iniciado com {len(self._tasks) - 1} regra(s) de vigilância")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for c in self.collectors.values():
            await c.close()

    async def _loop(self, w: Watch) -> None:
        while True:
            if not self.paused:
                await self.run_watch(w)
            await asyncio.sleep(w.interval)

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(3600)
            self.db.prune()

    async def run_watch(self, w: Watch) -> int:
        st = self.watch_status[w.name]
        st["state"] = "coletando"
        t0 = time.time()
        col = self.collectors[w.store]
        try:
            offers = await col.collect(w)
        except CollectorError as e:
            st.update(state="erro", error=str(e), last_run=time.time())
            self.log("erro", f"[{w.name}] {e}")
            return 0
        except Exception as e:  # noqa: BLE001
            st.update(state="erro", error=f"{type(e).__name__}: {e}", last_run=time.time())
            self.log("erro", f"[{w.name}] falha inesperada: {e}")
            return 0

        fcfg, det = self.s.filters, self.s.detector
        blocked = self.db.blocked_sellers()

        # 1ª passada: filtro barato do anúncio. Lixo não entra no histórico nem vira referência.
        clean: list[Offer] = []
        rejected: list[tuple[Offer, str]] = []
        for o in offers:
            reason = filters.check_listing(o, w, fcfg, blocked)
            (rejected.append((o, reason)) if reason else clean.append(o))

        # Preços atuais de cada produto de catálogo (concorrentes na mesma coleta).
        by_catalog: dict[str, dict[str, float]] = defaultdict(dict)
        for o in clean:
            if o.catalog_id:
                by_catalog[o.catalog_id][o.item_id] = o.price

        def peers_for(o: Offer) -> list[float]:
            same = [p for iid, p in by_catalog.get(o.catalog_id, {}).items() if iid != o.item_id]
            return same if len(same) >= det.min_peers else self.db.peer_prices(o.store, o.catalog_id, o.item_id)

        discards = 0
        for o, reason in rejected:
            if reason.startswith("Vendedor bloqueado"):
                continue  # loja já bloqueada: ignora em silêncio
            v = detector.evaluate(o, self.db.history(o.store, o.item_id), w, det, peers_for(o))
            if self._alert_worthy(v):  # só registra o que teria virado alerta
                discards += self._discard(o, v.score, reason)

        candidates: list[tuple[Offer, Verdict, list[float], list[float]]] = []
        for o in clean:
            hist = self.db.history(o.store, o.item_id)
            peers = peers_for(o)
            v = detector.evaluate(o, hist, w, det, peers)
            self.db.save_offer(o)
            if self._alert_worthy(v) and self._should_alert(o.store, o.item_id, o.price):
                candidates.append((o, v, hist, peers))

        # 2ª passada, só nos candidatos: checa o vendedor e reconfirma o preço no anúncio.
        alerts = 0
        for o, v, hist, peers in candidates:
            vetted = await self._vet(col, w, o, v, hist, peers)
            if vetted is None:
                discards += 1
                continue
            o, v = vetted
            a = self.db.save_alert(o, v)
            alerts += 1
            self.emit("alert", alert=a)
            for n in self.notifiers:
                asyncio.create_task(n.send(a))

        st.update(state="ok", error=None, last_run=time.time(), count=len(offers),
                  duration=round(time.time() - t0, 2), descartados=len(rejected))
        self.emit("watch", name=w.name, status=st)
        if alerts or discards:
            self.log("info", f"[{w.name}] {len(offers)} lidos · {alerts} alerta(s) · {discards} descartado(s)")
        return alerts

    def _alert_worthy(self, v: Verdict) -> bool:
        return v.is_alert and v.score >= self.s.min_alert_score

    def _discard(self, o: Offer, score: int, reason: str) -> int:
        """Registra um descarte (uma vez por item por cooldown). Retorna 1 se registrou."""
        if self.db.recent_discard(o.store, o.item_id, self.s.cooldown_min * 60):
            return 0
        self.db.save_discard(o, score, reason)
        self.emit("discard", item=o.title, reason=reason, price=o.price, seller=o.seller_name)
        self.log("info", f"Descartado: {o.title[:60]} — {reason}")
        # Mesmo vendedor postando anúncio de teste várias vezes: bloqueia a loja.
        if o.seller_id and reason.startswith("Título contém") and \
                self.db.seller_discard_count(o.store, o.seller_id) >= 3:
            self.db.block_seller(o.store, o.seller_id, o.seller_name, "auto: 3+ anúncios de teste")
            self.log("info", f"Loja bloqueada automaticamente: {o.seller_name or o.seller_id}")
        return 1

    async def _seller(self, col: Collector, o: Offer) -> SellerInfo | None:
        row = self.db.get_seller(o.store, o.seller_id)
        if row and row["updated"] and time.time() - row["updated"] < 86400 and row["sales"] is not None:
            return SellerInfo(seller_id=o.seller_id, nickname=row["nickname"] or "", sales=row["sales"],
                              level=row["level"], registered_days=row["registered_days"],
                              status=row["status"] or "active")
        try:
            info = await col.seller_info(o)
        except Exception as e:  # noqa: BLE001
            log.warning("Não consegui ler o vendedor %s: %s", o.seller_id, e)
            return None
        if info:
            self.db.save_seller(o.store, info)
        return info

    async def _vet(self, col: Collector, w: Watch, o: Offer, v: Verdict,
                   hist: list[float], peers: list[float]) -> tuple[Offer, Verdict] | None:
        fcfg = self.s.filters
        # Loja de teste?
        if o.seller_id:
            info = await self._seller(col, o)
            if info and info.nickname and not o.seller_name:
                o.seller_name = info.nickname
            reason = filters.check_seller(info, fcfg)
            if reason:
                self.db.block_seller(o.store, o.seller_id, o.seller_name, f"auto: {reason}")
                self._discard(o, v.score, reason)
                return None
        # Reconfirma o preço direto no anúncio (evita cache velho e preço já corrigido).
        if fcfg.confirm_before_alert:
            try:
                fresh = await col.confirm(o)
            except Exception as e:  # noqa: BLE001
                log.warning("Reconfirmação falhou para %s: %s", o.item_id, e)
                fresh = o
            if fresh is None:
                self._discard(o, v.score, "Anúncio sumiu ou esgotou na reconfirmação")
                return None
            if fresh is not o:
                fresh.watch, fresh.seller_name = o.watch, fresh.seller_name or o.seller_name
                fresh.catalog_id = fresh.catalog_id or o.catalog_id
                reason = filters.check_listing(fresh, w, fcfg, set())
                if reason:
                    self._discard(fresh, v.score, reason)
                    return None
                if abs(fresh.price - o.price) > max(0.01, o.price * 0.02):
                    v = detector.evaluate(fresh, hist, w, self.s.detector, peers)
                    if not self._alert_worthy(v):
                        self._discard(fresh, v.score, f"Loja já corrigiu o preço (agora R$ {fresh.price:,.2f})")
                        return None
                o = fresh
        if o.confirmed:
            v.reasons.append("Preço reconfirmado no anúncio")
        return o, v

    def _should_alert(self, store: str, item_id: str, price: float) -> bool:
        last = self.db.last_alert(store, item_id)
        if not last:
            return True
        recent = time.time() - last["ts"] < self.s.cooldown_min * 60
        # dentro do cooldown só alerta de novo se o preço caiu mais 5%+
        return not recent or price < last["price"] * 0.95

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)
