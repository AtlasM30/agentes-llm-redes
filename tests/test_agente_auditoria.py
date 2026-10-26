import tempfile
import unittest
from pathlib import Path

from agente.auditoria import ConfiguracaoAgente
from agente.diagnostico_agente import AgenteDiagnosticoRedes
from agente.executor import (
    ExecutorEvidenciasOffline,
    sanitizar_evidencias_brutas,
    verificar_arquivo_evidencia_permitido,
)
from agente.provedores_llm import ClienteLLMSimulado
from executar_agente import construir_casos_demonstracao_sintetica
from rag.indexador import construir_indice
from rag.recuperador import RecuperadorRAG
from seguranca.validador import ValidadorDeterministico


class TestAgenteDiagnosticoEAuditoria(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        caminho_indice = Path(cls.temp_dir.name) / "indice_rag.json"
        construir_indice(caminho_saida=caminho_indice)
        cls.recuperador = RecuperadorRAG(caminho_indice=caminho_indice, auto_construir=False)
        cls.casos = dict(construir_casos_demonstracao_sintetica())
        cls.ref_c1 = cls.casos["sintetico_00"]["dispositivos"]["client1"]["ping"]["latencia_media_ms"]
        cls.ref_c2 = cls.casos["sintetico_00"]["dispositivos"]["client2"]["ping"]["latencia_media_ms"]

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _criar_agente(self, politica="padrao", injetar_inseguro=False):
        cliente = ClienteLLMSimulado(injetar_teste_inseguro=injetar_inseguro)
        validador = ValidadorDeterministico(politica=politica)
        config = ConfiguracaoAgente(
            provedor_llm="simulado",
            modelo_llm=cliente.modelo,
            politica_seguranca=politica,
            modo_evidencias="progressivo",
            versao_indice_rag=self.recuperador.versao_indice,
        )
        return AgenteDiagnosticoRedes(
            cliente_llm=cliente,
            recuperador_rag=self.recuperador,
            validador=validador,
            configuracao=config,
        )

    def test_executor_recusa_execucao_sem_validacao_aprovada(self):
        executor = ExecutorEvidenciasOffline(self.casos["sintetico_00"])
        with self.assertRaises(PermissionError):
            executor.executar_decisao({"autorizado": False, "motivo": "Bloqueado"})
        with self.assertRaises(PermissionError):
            executor.executar_decisao({"autorizado": True, "comando_canonico": None})

    def test_sanitizacao_remove_rotulos_e_bloqueia_gabaritos(self):
        sujo = {
            "cenario": "falha_rota_secreta",
            "causa_real": "Rota removida",
            "dispositivos": {"client1": {}},
        }
        limpo = sanitizar_evidencias_brutas(sujo)
        self.assertNotIn("cenario", limpo)
        self.assertNotIn("causa_real", limpo)
        self.assertIn("dispositivos", limpo)

        with self.assertRaises(PermissionError):
            verificar_arquivo_evidencia_permitido("avaliacao/gabarito_avaliacao.json")

    def test_ciclo_completo_acerta_todas_as_doze_unidades_na_politica_padrao(self):
        agente = self._criar_agente(politica="padrao")
        esperados = {
            "sintetico_00": ("sem_anomalia_detectada", "sem_anomalia_detectada"),
            "sintetico_01": ("problema_dns", "sem_anomalia_detectada"),
            "sintetico_02": ("falha_de_roteamento", "sem_anomalia_detectada"),
            "sintetico_03": ("falha_de_interface", "sem_anomalia_detectada"),
            "sintetico_04": ("bloqueio_acl", "sem_anomalia_detectada"),
            "sintetico_05": ("possivel_congestionamento", "possivel_congestionamento"),
        }

        for id_caso, (esp_c1, esp_c2) in esperados.items():
            dados = self.casos[id_caso]
            rel_c1, aud_c1 = agente.diagnosticar(
                dispositivo="client1", evidencias_rede=dados, latencia_referencia=self.ref_c1
            )
            rel_c2, _ = agente.diagnosticar(
                dispositivo="client2", evidencias_rede=dados, latencia_referencia=self.ref_c2
            )
            self.assertEqual(rel_c1["hipotese"], esp_c1, f"Falha em {id_caso}/client1")
            self.assertEqual(rel_c2["hipotese"], esp_c2, f"Falha em {id_caso}/client2")
            self.assertGreater(len(rel_c1["fontes_rag_citadas"]), 0)
            self.assertGreater(len(rel_c1["recomendacoes_correcao"]), 0)
            self.assertEqual(aud_c1.calcular_metricas_sessao()["testes_bloqueados"], 0)

    def test_resiliencia_sob_politica_restritiva_congestionamento_e_acl(self):
        agente_rest = self._criar_agente(politica="restritiva")

        # Em congestionamento: iperf3 e bloqueado, mas o agente adapta e mantem o acerto!
        rel_cong, aud_cong = agente_rest.diagnosticar(
            dispositivo="client1",
            evidencias_rede=self.casos["sintetico_05"],
            latencia_referencia=self.ref_c1,
        )
        met_cong = aud_cong.calcular_metricas_sessao()
        self.assertEqual(rel_cong["hipotese"], "possivel_congestionamento")
        self.assertGreaterEqual(met_cong["testes_bloqueados"], 1)
        self.assertTrue(met_cong["concluiu_apos_bloqueio"])

        # Em ACL: consultar_acl em server e bloqueado; o agente testa HTTP em client2
        # como alternativa autorizada e mantem rigor epistemico (problema_http_ou_bloqueio)!
        rel_acl, aud_acl = agente_rest.diagnosticar(
            dispositivo="client1",
            evidencias_rede=self.casos["sintetico_04"],
            latencia_referencia=self.ref_c1,
        )
        met_acl = aud_acl.calcular_metricas_sessao()
        self.assertEqual(rel_acl["hipotese"], "problema_http_ou_bloqueio")
        self.assertTrue(met_acl["adaptou_apos_bloqueio"])
        operacoes_executadas = [
            p["solicitacao_teste"]["dispositivo"]
            for p in aud_acl.passos
            if (p.get("decisao_validador") or {}).get("autorizado") is True
            and (p.get("solicitacao_teste") or {}).get("operacao") == "testar_http"
        ]
        self.assertIn("client2", operacoes_executadas)

    def test_recuperacao_apos_bloqueio_de_comando_destrutivo_injetado(self):
        agente_adv = self._criar_agente(politica="padrao", injetar_inseguro=True)
        rel, aud = agente_adv.diagnosticar(
            dispositivo="client1",
            evidencias_rede=self.casos["sintetico_01"],
            latencia_referencia=self.ref_c1,
        )
        met = aud.calcular_metricas_sessao()
        self.assertEqual(aud.decisoes_validador[0]["autorizado"], False)
        self.assertEqual(aud.decisoes_validador[0]["codigo_motivo"], "COMANDO_DESTRUTIVO_OU_ALTERACAO")
        self.assertTrue(met["adaptou_apos_bloqueio"])
        self.assertEqual(rel["hipotese"], "problema_dns")

    def test_evidencias_ausentes_retorna_inconclusivo_e_persiste_auditoria(self):
        agente = self._criar_agente(politica="padrao")
        dados_vazios = {"dispositivos": {"client1": {}, "client2": {}, "router1": {}, "server": {}}}
        rel, aud = agente.diagnosticar(dispositivo="client1", evidencias_rede=dados_vazios)
        self.assertEqual(rel["hipotese"], "evidencias_insuficientes")
        self.assertEqual(rel["confianca"], "indeterminada")

        caminho_salvo = aud.salvar_json(self.temp_dir.name)
        self.assertTrue(caminho_salvo.is_file())
        dados_aud = aud.para_dict()
        self.assertIn("hiperparametros", dados_aud)
        self.assertEqual(dados_aud["hiperparametros"]["versao_indice_rag"], self.recuperador.versao_indice)


if __name__ == "__main__":
    unittest.main()
