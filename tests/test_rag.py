import tempfile
import unittest
from pathlib import Path

from rag.indexador import (
    CAMPOS_METADADOS_OBRIGATORIOS,
    ViolacaoSeparacaoDadosError,
    construir_indice,
    verificar_caminho_seguro,
    verificar_conteudo_sem_gabarito,
)
from rag.recuperador import RecuperadorRAG


class TestBaseRecuperacaoRAG(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.caminho_indice = Path(cls.temp_dir.name) / "indice_teste.json"
        cls.indice = construir_indice(caminho_saida=cls.caminho_indice)
        cls.recuperador = RecuperadorRAG(caminho_indice=cls.caminho_indice, auto_construir=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_sete_fontes_catalogadas_e_metadados_completos(self):
        self.assertEqual(self.indice["total_fontes"], 7)
        self.assertGreaterEqual(self.indice["total_chunks"], 20)
        fontes_encontradas = {c["fonte_id"] for c in self.indice["chunks"]}
        esperadas = {
            "mininet_walkthrough",
            "iperf3_esnet",
            "dnsmasq_man",
            "bind9_dig",
            "iproute2_man",
            "iptables_man",
            "tc_man",
        }
        self.assertEqual(fontes_encontradas, esperadas)

        for chunk in self.indice["chunks"]:
            for campo in CAMPOS_METADADOS_OBRIGATORIOS:
                self.assertIn(campo, chunk)
                self.assertIsNotNone(chunk[campo])

    def test_protecao_anti_vazamento_bloqueia_gabaritos_e_logs(self):
        with self.assertRaises(ViolacaoSeparacaoDadosError):
            verificar_caminho_seguro("avaliacao/gabarito_avaliacao.json")

        with self.assertRaises(ViolacaoSeparacaoDadosError):
            verificar_caminho_seguro("dados/gabaritos/causas_reais.json")

        with self.assertRaises(ViolacaoSeparacaoDadosError):
            verificar_caminho_seguro("logs/evidencias_caso_01.json")

        with self.assertRaises(ViolacaoSeparacaoDadosError):
            verificar_conteudo_sem_gabarito(
                '{"caso_01": {"cenario": "dns", "causa_real": "DNS incorreto"}}'
            )

    def test_recuperacao_relevante_para_cada_categoria_de_falha(self):
        # 1. Interface / Rota -> iproute2_man
        res_iface = self.recuperador.recuperar("ip -br link client1-eth0 DOWN precedencia rota", top_k=2)
        self.assertTrue(any(r["fonte_id"] == "iproute2_man" for r in res_iface))

        # 2. DNS -> bind9_dig ou dnsmasq_man
        res_dns = self.recuperador.recuperar("dig @192.168.20.99 app.lab.local timeout dnsmasq", top_k=2)
        self.assertTrue(any(r["fonte_id"] in {"bind9_dig", "dnsmasq_man"} for r in res_dns))

        # 3. ACL -> iptables_man
        res_acl = self.recuperador.recuperar("iptables -S INPUT tcp --dport 80 DROP", top_k=2)
        self.assertEqual(res_acl[0]["fonte_id"], "iptables_man")

        # 4. Congestionamento -> tc_man ou iperf3_esnet
        res_cong = self.recuperador.recuperar("tc qdisc show bufferbloat latencia rtt 10 Mbps iperf3", top_k=3)
        self.assertTrue(any(r["fonte_id"] in {"tc_man", "iperf3_esnet"} for r in res_cong))


if __name__ == "__main__":
    unittest.main()
