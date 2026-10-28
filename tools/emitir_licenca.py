"""Emite uma chave de licença.   Uso: python tools/emitir_licenca.py "Maria Silva" 30
Imprime a chave e o id (para revogar depois, colocando o id em "revogadas" no JSON online)."""
import sys
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sniper import licenca  # noqa: E402

if len(sys.argv) != 3 or not sys.argv[2].isdigit():
    sys.exit('Uso: python tools/emitir_licenca.py "Nome do cliente" DIAS')
priv = load_pem_private_key((Path.home() / "SniperOferta-chaves" / "privada.pem").read_bytes(), None)
chave = licenca.emitir(priv, sys.argv[1], int(sys.argv[2]))
l = licenca.validar(chave, licenca.publica_b64(priv))
print(f"Cliente: {l.cliente}\nId (para revogar): {l.id}\nVence: {l.expira:%d/%m/%Y}\n\nCHAVE:\n{chave}")
