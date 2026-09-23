"""Notificadores: Telegram (celular) e notificação nativa do Windows."""
from __future__ import annotations

import asyncio
import logging
import sys

import httpx

log = logging.getLogger("sniper.notify")

EMOJI = {"GRATIS": "🎁", "CRITICO": "🚨", "ALTO": "🔥", "MEDIO": "💡"}


def _brl(v: float | None) -> str:
    if v is None:
        return "-"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_text(a: dict) -> str:
    head = f"{EMOJI.get(a['level'], '')} {a['level']} · nota {a['score']}"
    lines = [head, a["title"], f"Agora: {_brl(a['price'])}"]
    if a.get("ref_price"):
        lines.append(f"Referência: {_brl(a['ref_price'])} (-{(a.get('drop_pct') or 0):.0%})")
    if a.get("reasons"):
        lines.append("• " + "\n• ".join(a["reasons"]))
    lines.append(a["url"])
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, min_score: int):
        self.token, self.chat_id, self.min_score = token, chat_id, min_score
        self.client = httpx.AsyncClient(timeout=10)

    async def send(self, alert: dict) -> None:
        if alert["score"] < self.min_score:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = await self.client.post(url, json={
                "chat_id": self.chat_id, "text": format_text(alert),
                "disable_web_page_preview": False,
            })
            if r.status_code != 200:
                log.warning("Telegram respondeu %s: %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("Falha ao enviar Telegram: %s", e)


class WindowsNotifier:
    """Usa a biblioteca `winotify` (só no Windows). Em outros sistemas não faz nada."""

    def __init__(self, min_score: int):
        self.min_score = min_score
        self.ok = False
        if sys.platform == "win32":
            try:
                from winotify import Notification, audio  # noqa: F401
                self.ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("Notificação do Windows indisponível (%s: %s) — python usado: %s",
                            type(e).__name__, e, sys.executable)

    async def send(self, alert: dict) -> None:
        if not self.ok or alert["score"] < self.min_score:
            return
        from winotify import Notification, audio

        def _show():
            n = Notification(
                app_id="Sniper de Ofertas",
                title=f"{EMOJI.get(alert['level'], '')} {alert['level']} · {_brl(alert['price'])}",
                msg=alert["title"][:180],
                duration="long" if alert["level"] in ("GRATIS", "CRITICO") else "short",
            )
            n.set_audio(audio.LoopingAlarm if alert["level"] in ("GRATIS", "CRITICO") else audio.Default,
                        loop=False)
            n.add_actions(label="Abrir oferta", launch=alert["url"])
            n.show()

        await asyncio.to_thread(_show)
