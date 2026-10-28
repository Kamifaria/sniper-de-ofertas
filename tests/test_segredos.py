"""Segredos no cofre do sistema (Credential Manager), nunca em texto puro."""
import sys
import unittest
from pathlib import Path

import keyring
from keyring.backend import KeyringBackend

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import segredos  # noqa: E402


class CofreFalso(KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, servico, usuario):
        return self.d.get((servico, usuario))

    def set_password(self, servico, usuario, senha):
        self.d[(servico, usuario)] = senha

    def delete_password(self, servico, usuario):
        self.d.pop((servico, usuario), None)


class SegredosTests(unittest.TestCase):
    def setUp(self):
        self.antes = keyring.get_keyring()
        self.cofre = CofreFalso()
        keyring.set_keyring(self.cofre)

    def tearDown(self):
        keyring.set_keyring(self.antes)

    def test_guarda_e_le(self):
        segredos.guardar("ml_client_secret", "abc")
        self.assertEqual(segredos.ler("ml_client_secret"), "abc")
        self.assertEqual(list(self.cofre.d)[0][0], "SniperOferta")

    def test_ausente_devolve_vazio(self):
        self.assertEqual(segredos.ler("nao_existe"), "")

    def test_apagar(self):
        segredos.guardar("x", "1")
        segredos.apagar("x")
        self.assertEqual(segredos.ler("x"), "")
        segredos.apagar("x")  # apagar o que não existe não quebra

    def test_cofre_indisponivel_nao_grava_em_texto_puro(self):
        class Quebrado(CofreFalso):
            def set_password(self, *a):
                raise keyring.errors.KeyringError("sem cofre")
        keyring.set_keyring(Quebrado())
        with self.assertRaises(segredos.CofreIndisponivel):
            segredos.guardar("x", "1")
        self.assertEqual(segredos.ler("x"), "")  # leitura nunca levanta


if __name__ == "__main__":
    unittest.main()
