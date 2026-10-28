"""Gera assets/icone.ico (alvo simples). Rodar uma vez; o .ico gerado é versionado."""
from pathlib import Path
from PIL import Image, ImageDraw

out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.ellipse((8, 8, 248, 248), fill=(24, 28, 38, 255))
for r, cor in ((100, (255, 204, 0, 255)), (70, (24, 28, 38, 255)), (42, (230, 50, 50, 255)), (14, (255, 255, 255, 255))):
    d.ellipse((128 - r, 128 - r, 128 + r, 128 + r), fill=cor)
im.save(out / "icone.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
