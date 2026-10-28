"""Onde ficam os dados e os recursos, rodando do código ou empacotado (.exe)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import paths  # noqa: E402


class PathsTests(unittest.TestCase):
    def test_desenvolvimento_usa_a_pasta_do_projeto(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(paths.dados_dir(), Path(__file__).resolve().parents[1])

    def test_empacotado_usa_appdata(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\Fulana\AppData\Roaming"}):
            self.assertEqual(paths.dados_dir(), Path(r"C:\Users\Fulana\AppData\Roaming") / "SniperOferta")

    def test_empacotado_acha_recurso_em_meipass(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", r"C:\Temp\_MEI123", create=True):
            self.assertEqual(paths.recurso("sniper/web"), Path(r"C:\Temp\_MEI123") / "sniper" / "web")

    def test_desenvolvimento_acha_recurso_na_pasta_do_projeto(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertTrue((paths.recurso("sniper/web") / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
