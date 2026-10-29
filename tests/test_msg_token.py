"""Mensagens de erro do token do ML orientam pelo app, não por script de desenvolvedor."""
import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from sniper.collectors.base import CollectorError
from sniper.collectors.mercadolivre import TokenStore


class MsgTokenTest(unittest.TestCase):
    def _store(self, dados):
        t = TokenStore(Path(tempfile.mkdtemp()) / "t.json", "id", "seg")
        t.data = dados
        return t

    def test_sem_token_manda_conectar_ml(self):
        async def go():
            async with httpx.AsyncClient() as c:
                await self._store({}).access_token(c)
        with self.assertRaises(CollectorError) as e:
            asyncio.run(go())
        self.assertIn("Conectar ML", str(e.exception))
        self.assertNotIn("auth_ml", str(e.exception))

    def test_falha_ao_renovar_manda_conectar_ml(self):
        transp = httpx.MockTransport(lambda r: httpx.Response(400, text="invalid_client"))
        async def go():
            async with httpx.AsyncClient(transport=transp) as c:
                await self._store({"refresh_token": "x"}).access_token(c)
        with self.assertRaises(CollectorError) as e:
            asyncio.run(go())
        self.assertIn("Conectar ML", str(e.exception))
        self.assertNotIn("auth_ml", str(e.exception))


if __name__ == "__main__":
    unittest.main()
