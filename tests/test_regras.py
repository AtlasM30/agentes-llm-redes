import unittest

from diagnostico.regras import (
    diagnosticar_cliente,
    interface_desativada,
    rota_padrao_ausente,
)


class TestRegras(unittest.TestCase):

    def test_interface_down(self):
        dados = {
            "interfaces": {
                "estado": {
                    "sucesso": True,
                    "saida": (
                        "client1-eth0@if48 DOWN "
                        "00:00:00:00:00:01 <BROADCAST>"
                    )
                }
            }
        }

        self.assertTrue(
            interface_desativada(dados, "client1")
        )

    def test_rota_ausente(self):
        dados = {
            "rotas": {
                "sucesso": True,
                "saida": (
                    "192.168.10.0/24 dev client1-eth0"
                )
            }
        }

        self.assertTrue(rota_padrao_ausente(dados))

    def test_rota_presente(self):
        dados = {
            "rotas": {
                "sucesso": True,
                "saida": (
                    "default via 192.168.10.1 "
                    "dev client1-eth0"
                )
            }
        }

        self.assertFalse(rota_padrao_ausente(dados))

    def test_dns(self):
        dados = {
            "ping": {"sucesso": True},
            "dns": {"resolucao_correta": False},
            "http": {"servico_disponivel": True},
        }

        resposta = diagnosticar_cliente(dados)

        self.assertEqual(
            resposta["hipotese"],
            "problema_dns"
        )

    def test_interface_tem_prioridade_sobre_rota(self):
        dados = {
            "interfaces": {
                "estado": {
                    "sucesso": True,
                    "saida": "client1-eth0@if48 DOWN <BROADCAST>",
                }
            },
            "rotas": {
                "sucesso": True,
                "saida": "",
            },
            "ping": {"sucesso": False},
            "dns": {"resolucao_correta": False},
            "http": {"servico_disponivel": False},
        }

        resposta = diagnosticar_cliente(dados)

        self.assertEqual(
            resposta["hipotese"],
            "falha_de_interface"
        )


if __name__ == "__main__":
    unittest.main()
