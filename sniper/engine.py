"""Motor: roda cada regra de vigilância no seu intervalo, avalia e dispara alertas."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections import defaultdict

import httpx

from . import detector, filters
from .collectors import Collector, CollectorError
from .config import Settings
from .db import Database
from .models import Offer, SellerInfo, Verdict, Watch
from .notify import TelegramNotifier, WindowsNotifier
from .ratelimit import RateLimiter
from .stores import LOJAS

log = logging.getLogger("sniper.engine")

UNIDADES_TTL_S = 86400  # relê a lista de unidades de varredura (ex.: categorias) uma vez por dia

FILA_RAPIDA = "Fila rápida"


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
        self.restart_delay = 30.0  # segundos até recriar um loop que caiu

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

        self.store_errors: dict[str, dict] = {}   # loja → {"desde", "avisado", "msg"}
        # Se já passou do horário do resumo hoje, o primeiro resumo sai amanhã.
        self._last_summary = self._summary_due_day(time.time())

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

    def lojas_info(self) -> list[dict]:
        out = []
        for chave, info in LOJAS.items():
            lc = self.s.lojas.get(chave)
            st = self.store_status.get(chave, {})
            lim = self.limiters.get(chave)
            err = self.store_errors.get(chave)
            out.append({"chave": chave, "nome": info.nome, "oficial": info.oficial,
                        "ativa": bool(lc and lc.ativo), "configurada": st.get("configurada", False),
                        "motivo": st.get("motivo") or (self._motivo_sem_coletor(chave) if not st else ""),
                        "limite": lim.estado() if lim else None,
                        "erro": err["msg"] if err else None})
        return out

    # ---------- saúde das lojas ----------
    def _nome(self, store: str) -> str:
        info = LOJAS.get(store)
        return info.nome if info else store

    def _store_fail(self, store: str, msg: str, now: float | None = None) -> None:
        e = self.store_errors.setdefault(store, {"desde": now or time.time(), "avisado": False})
        e["msg"] = msg

    async def _store_ok(self, store: str) -> None:
        e = self.store_errors.pop(store, None)
        if e and e["avisado"]:
            await self._notify_text(f"✅ {self._nome(store)} voltou a funcionar.")

    async def _notify_text(self, text: str) -> None:
        for n in self.notifiers:
            if hasattr(n, "send_text"):
                await n.send_text(text)

    def _summary_due_day(self, now: float) -> str | None:
        """Data (AAAA-MM-DD) se já passou do horário do resumo nesse dia; None se não passou ou está desligado."""
        if not self.s.telegram_resumo:
            return None
        hh, mm = (int(x) for x in self.s.telegram_resumo.split(":"))
        lt = time.localtime(now)
        return time.strftime("%Y-%m-%d", lt) if (lt.tm_hour, lt.tm_min) >= (hh, mm) else None

    def _summary_text(self) -> str:
        s = self.db.stats()
        prob = "; ".join(f"{self._nome(k)} ({v['msg']})" for k, v in self.store_errors.items()) or "nenhuma"
        leituras = f"{s['leituras_24h']:,}".replace(",", ".")
        return ("📊 Sniper de Ofertas: últimas 24 h\n"
                f"Leituras: {leituras}\n"
                f"Alertas: {s['alertas_24h']} (críticos: {s['criticos_24h']}, grátis: {s['gratis_24h']})\n"
                f"Descartados: {s['descartados_24h']}\n"
                f"Lojas com problema: {prob}")

    async def health_check(self, now: float | None = None) -> None:
        now = now or time.time()
        for store, lim in self.limiters.items():
            est = lim.estado()
            if est["pausada_ate"]:
                ate = time.strftime("%H:%M", time.localtime(est["pausada_ate"]))
                self._store_fail(store, f"pausada por bloqueio até {ate} ({est['motivo']})", now)
        limite = self.s.telegram_travada_min * 60
        for store, e in list(self.store_errors.items()):
            if not e["avisado"] and now - e["desde"] >= limite:
                e["avisado"] = True
                await self._notify_text(f"⚠️ {self._nome(store)} com problema há "
                                        f"{round((now - e['desde']) / 60)} min: {e['msg']}")
        day = self._summary_due_day(now)
        if day and day != self._last_summary:
            self._last_summary = day
            await self._notify_text(self._summary_text())

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.health_check()

    # ---------- ciclo ----------
    async def start(self) -> None:
        for w in self.s.watches:
            if w.store not in self.collectors:
                self.watch_status[w.name] = {"store": w.store, "kind": w.kind, "state": "sem coletor",
                                             "error": self._motivo_sem_coletor(w.store),
                                             "count": 0, "interval": w.interval}
                continue
            self.watch_status[w.name] = {"store": w.store, "kind": w.kind, "state": "aguardando",
                                         "last_run": None, "count": 0, "error": None,
                                         "interval": w.interval if w.kind == "vigiar" else None,
                                         "duration": None}
            loop = self._sweep_loop if w.kind == "varrer" else self._loop
            self._tasks.append(asyncio.create_task(
                self._supervise(w.name, lambda w=w, loop=loop: loop(w))))
        if any(c.supports_refresh for c in self.collectors.values()):
            self.watch_status[FILA_RAPIDA] = {"store": "", "kind": "rapida", "state": "aguardando",
                                              "count": 0, "error": None, "last_run": None,
                                              "interval": self.s.intervalo_rapido}
            self._tasks.append(asyncio.create_task(self._supervise(FILA_RAPIDA, self._fast_loop)))
        self._tasks.append(asyncio.create_task(self._supervise("saúde", self._health_loop)))
        self._tasks.append(asyncio.create_task(self._housekeeping()))
        ativas = sum(1 for w in self.s.watches if w.store in self.collectors)
        self.log("info", f"Motor iniciado com {ativas} regra(s) ativa(s)")

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

    async def _sweep_loop(self, w: Watch) -> None:
        while True:
            if self.paused:
                await asyncio.sleep(5)
                continue
            await self.sweep_step(w)
            await asyncio.sleep(self._sweep_gap(w))

    def _sweep_gap(self, w: Watch) -> float:
        sw = self.db.get_sweep(w.name)
        n = len(sw["units"]) if sw and sw["units"] else 0
        return w.cycle_min * 60 / n if n else 60.0

    async def _sweep_state(self, w: Watch, col: Collector) -> dict:
        sw = self.db.get_sweep(w.name)
        if sw and sw["units"] and time.time() - sw["units_ts"] < UNIDADES_TTL_S:
            return sw
        units = await col.sweep_units(w)
        cursor, started = 0, time.time()
        if sw and sw["units"]:
            atual = sw["units"][sw["cursor"] % len(sw["units"])]
            if atual in units:  # lista recarregada: continua na mesma unidade
                cursor, started = units.index(atual), sw["cycle_started"]
        self.db.save_sweep(w.name, units, time.time(), cursor, started)
        return self.db.get_sweep(w.name)

    async def sweep_step(self, w: Watch) -> int:
        """Lê a próxima unidade da varredura (ex.: uma categoria) e avança o cursor salvo no banco."""
        st = self.watch_status[w.name]
        col = self.collectors[w.store]
        if not col.supports_sweep:
            st.update(state="loja não suporta varredura", error=None, last_run=time.time())
            return 0
        st["state"] = "coletando"
        t0 = time.time()
        try:
            sw = await self._sweep_state(w, col)
        except Exception as e:  # noqa: BLE001
            msg = str(e) if isinstance(e, CollectorError) else f"{type(e).__name__}: {e}"
            st.update(state="erro", error=f"Não consegui listar as unidades: {msg}", last_run=time.time())
            self.log("erro", f"[{w.name}] {st['error']}")
            self._store_fail(w.store, st["error"])
            return 0
        units = sw["units"]
        if not units:
            st.update(state="erro", error="A loja não informou unidades de varredura", last_run=time.time())
            return 0

        cursor = sw["cursor"] % len(units)
        unit = units[cursor]
        offers: list[Offer] = []
        alerts, err, avancar = 0, None, True
        try:
            offers = await col.sweep(unit, w)
            alerts = (await self._process(w, col, offers))["alertas"]
        except (CollectorError, httpx.TransportError) as e:
            err, avancar = f"{unit}: {e}", False  # loja bloqueou ou sem internet: tenta a mesma unidade depois
        except Exception as e:  # noqa: BLE001
            err = f"{unit} pulada: {type(e).__name__}: {e}"  # ex.: categoria sumiu
        if err:
            self.log("erro", f"[{w.name}] {err}")
        if err and not avancar:
            self._store_fail(w.store, err)
        else:
            await self._store_ok(w.store)

        nxt, started = cursor, sw["cycle_started"]
        if avancar:
            nxt = cursor + 1
            if nxt >= len(units):
                self.log("info", f"[{w.name}] volta completa: {len(units)} unidade(s) em "
                                 f"{round((time.time() - started) / 60)} min")
                nxt, started = 0, time.time()
            self.db.save_sweep_cursor(w.name, nxt, started)

        gap = w.cycle_min * 60 / len(units)
        st.update(state="erro" if err else "ok", error=err, last_run=time.time(), count=len(offers),
                  duration=round(time.time() - t0, 2), unidade=nxt, total=len(units),
                  fim_estimado=time.time() + (len(units) - nxt) * gap)
        self.emit("watch", name=w.name, status=st)
        return alerts

    async def _fast_loop(self) -> None:
        while True:
            if not self.paused:
                await self.fast_lane_step()
            await asyncio.sleep(self.s.intervalo_rapido)

    async def fast_lane_step(self) -> int:
        """Relê em lote os itens caros de cada loja com refresh e passa pelo pipeline."""
        st = self.watch_status.setdefault(FILA_RAPIDA, {"store": "", "kind": "rapida",
                                                        "interval": self.s.intervalo_rapido})
        st["state"] = "coletando"
        t0 = time.time()
        alerts, itens, erros = 0, 0, []
        for store, col in list(self.collectors.items()):
            if not col.supports_refresh:
                continue
            ids = self.db.fast_lane_items(store, self.s.valor_alto, self.s.max_itens_rapida)
            if not ids:
                continue
            itens += len(ids)
            try:
                offers = await col.refresh(ids)
            except Exception as e:  # noqa: BLE001
                msg = str(e) if isinstance(e, CollectorError) else f"{type(e).__name__}: {e}"
                erros.append(f"{store}: {msg}")
                self.log("erro", f"[{FILA_RAPIDA}] {store}: {msg}")
                self._store_fail(store, msg)
                continue
            alerts += (await self._process(Watch(name=FILA_RAPIDA, store=store), col, offers))["alertas"]
            await self._store_ok(store)
        st.update(state="erro" if erros else "ok", error="; ".join(erros) or None, count=itens,
                  last_run=time.time(), duration=round(time.time() - t0, 2))
        self.emit("watch", name=FILA_RAPIDA, status=st)
        return alerts

    async def _supervise(self, nome: str, factory) -> None:
        """Roda factory(); se cair com erro inesperado, registra e recria depois de restart_delay."""
        while True:
            try:
                await factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("Loop %s caiu", nome)
                self.log("erro", f"[{nome}] loop caiu ({type(e).__name__}: {e}); "
                                 f"reiniciando em {int(self.restart_delay)}s")
                await asyncio.sleep(self.restart_delay)

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
            self._store_fail(w.store, st["error"])
            return 0
        except Exception as e:  # noqa: BLE001
            st.update(state="erro", error=f"{type(e).__name__}: {e}", last_run=time.time())
            self.log("erro", f"[{w.name}] falha inesperada: {e}")
            self._store_fail(w.store, st["error"])
            return 0

        r = await self._process(w, col, offers)
        await self._store_ok(w.store)
        st.update(state="ok", error=None, last_run=time.time(), count=len(offers),
                  duration=round(time.time() - t0, 2), descartados=r["rejeitados"])
        self.emit("watch", name=w.name, status=st)
        if r["alertas"] or r["descartes"]:
            self.log("info", f"[{w.name}] {len(offers)} lidos · {r['alertas']} alerta(s) · "
                             f"{r['descartes']} descartado(s)")
        return r["alertas"]

    async def _process(self, w: Watch, col: Collector, offers: list[Offer]) -> dict:
        """Filtra, avalia, confere vendedor e preço e dispara alertas. Usado por vigiar, varrer e fila rápida."""
        for o in offers:
            o.watch = w.name
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
        return {"alertas": alerts, "descartes": discards, "rejeitados": len(rejected)}

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
