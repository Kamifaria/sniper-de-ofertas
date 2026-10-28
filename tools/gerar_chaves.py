"""Cria o par de chaves da licença (rodar UMA vez). A privada fica fora do projeto.

A privada é o que permite emitir licenças: faça backup e nunca envie a ninguém.
Se perder, será preciso gerar outro par e lançar nova versão do app.
"""
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sniper import licenca  # noqa: E402

PASTA = Path.home() / "SniperOferta-chaves"
PRIVADA = PASTA / "privada.pem"

if PRIVADA.exists():
    sys.exit(f"Já existe {PRIVADA}. Não vou sobrescrever.")
PASTA.mkdir(exist_ok=True)
priv = Ed25519PrivateKey.generate()
PRIVADA.write_bytes(priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
pub = licenca.publica_b64(priv)
(Path(__file__).resolve().parent.parent / "sniper" / "licenca_publica.py").write_text(
    f'"""Chave pública da licença (pode ser versionada; a privada não)."""\nPUBLICA = "{pub}"\n', encoding="utf-8")
print(f"Privada salva em {PRIVADA} (faça backup!). Pública gravada em sniper/licenca_publica.py")
