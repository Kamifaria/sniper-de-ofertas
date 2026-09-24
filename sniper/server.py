"""API local + painel (Starlette). Só escuta em 127.0.0.1."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import time
import webbrowser
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .config import Settings
from .engine import Engine

WEB = Path(__file__).parent / "web"
STATUS_OK = {"novo", "visto", "comprado", "ignorado", "cancelado_loja", "loja_teste"}


def create_app(settings: Settings) -> Starlette:
    engine = Engine(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        await engine.start()
        yield
        await engine.stop()

    async def index(_: Request):
        return FileResponse(WEB / "index.html")

    async def alerts(req: Request):
        q = req.query_params
        return JSONResponse(engine.db.list_alerts(
            limit=int(q.get("limit", 100)), min_score=int(q.get("min_score", 0)),
            status=q.get("status") or None, since=float(q["since"]) if q.get("since") else None))

    async def alerts_csv(req: Request):
        """Log de bugs do período em CSV (abre no Excel: separador ';' e UTF-8 com BOM)."""
        q = req.query_params
        since = float(q["since"]) if q.get("since") else None
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerow(["data", "loja", "nivel", "nota", "produto", "preco", "referencia", "queda_%",
                    "motivos", "status", "link"])
        for a in engine.db.list_alerts(limit=100000, since=since):
            w.writerow([time.strftime("%d/%m/%Y %H:%M", time.localtime(a["ts"])), a["store"], a["level"],
                        a["score"], a["title"], f"{a['price']:.2f}".replace(".", ","),
                        f"{a['ref_price']:.2f}".replace(".", ",") if a["ref_price"] else "",
                        round((a["drop_pct"] or 0) * 100), " | ".join(a["reasons"]), a["status"], a["url"]])
        nome = time.strftime("bugs-%Y%m%d-%H%M.csv")
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    async def set_status(req: Request):
        body = await req.json()
        status = body.get("status")
        if status not in STATUS_OK:
            return JSONResponse({"erro": "status inválido"}, status_code=400)
        alert_id = int(req.path_params["id"])
        engine.db.set_alert_status(alert_id, status)
        if status == "loja_teste":  # marca a loja e para de ler os anúncios dela
            a = engine.db.get_alert(alert_id)
            if a.get("seller_id"):
                engine.db.block_seller(a["store"], a["seller_id"], a.get("seller_name") or "",
                                       "marcada por você como loja de teste")
                engine.log("info", f"Loja bloqueada: {a.get('seller_name') or a['seller_id']}")
        return JSONResponse({"ok": True})

    async def discards(req: Request):
        return JSONResponse(engine.db.list_discards(int(req.query_params.get("limit", 100))))

    async def blocked(_: Request):
        return JSONResponse(engine.db.list_blocked())

    async def block(req: Request):
        b = await req.json()
        if not b.get("store") or not b.get("seller_id"):
            return JSONResponse({"erro": "store e seller_id obrigatórios"}, status_code=400)
        engine.db.block_seller(b["store"], str(b["seller_id"]), b.get("nickname", ""),
                               b.get("reason", "manual"), bool(b.get("blocked", True)))
        engine.log("info", ("Loja bloqueada: " if b.get("blocked", True) else "Loja liberada: ")
                   + (b.get("nickname") or str(b["seller_id"])))
        return JSONResponse({"ok": True})

    async def stats(_: Request):
        return JSONResponse({**engine.db.stats(), "pausado": engine.paused,
                             "notificadores": [type(n).__name__ for n in engine.notifiers]})

    async def watches(_: Request):
        return JSONResponse(engine.watch_status)

    async def lojas(_: Request):
        return JSONResponse(engine.lojas_info())

    async def set_loja(req: Request):
        body = await req.json()
        try:
            await engine.set_store_active(req.path_params["chave"], bool(body.get("ativo")))
        except KeyError:
            return JSONResponse({"erro": "loja não existe"}, status_code=404)
        return JSONResponse(engine.lojas_info())

    async def events(_: Request):
        return JSONResponse(list(engine.events))

    async def history(req: Request):
        p = req.path_params
        return JSONResponse(engine.db.history_points(p["store"], p["item_id"]))

    async def pause(req: Request):
        body = await req.json()
        engine.paused = bool(body.get("paused"))
        engine.log("info", "Monitoramento pausado" if engine.paused else "Monitoramento retomado")
        return JSONResponse({"pausado": engine.paused})

    async def open_url(req: Request):
        """Abre o link no navegador padrão (onde você está logado nas lojas)."""
        url = (await req.json()).get("url", "")
        if url.startswith("https://"):
            await asyncio.to_thread(webbrowser.open, url)
            return JSONResponse({"ok": True})
        return JSONResponse({"erro": "url inválida"}, status_code=400)

    async def stream(req: Request):
        q = engine.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                while True:
                    if await req.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                engine.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    routes = [
        Route("/", index),
        Route("/api/alerts", alerts),
        Route("/api/alerts.csv", alerts_csv),
        Route("/api/alerts/{id:int}/status", set_status, methods=["POST"]),
        Route("/api/stats", stats),
        Route("/api/discards", discards),
        Route("/api/sellers/blocked", blocked),
        Route("/api/sellers/block", block, methods=["POST"]),
        Route("/api/watches", watches),
        Route("/api/lojas", lojas),
        Route("/api/lojas/{chave}", set_loja, methods=["POST"]),
        Route("/api/events", events),
        Route("/api/history/{store}/{item_id}", history),
        Route("/api/pause", pause, methods=["POST"]),
        Route("/api/open", open_url, methods=["POST"]),
        Route("/api/stream", stream),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.engine = engine
    return app
