"""Orquestrador do Agente LLM de Diagnostico com RAG e Validacao Deterministica.

Integra os quatro pilares da Etapa 7 (Metodo Proposto):
  1. Recuperacao contextual de documentacao tecnica (RecuperadorRAG)
  2. Ciclo multi-etapa de raciocinio e formulacao de hipoteses (ClienteLLM)
  3. Interceptacao e validacao deterministica de seguranca (ValidadorDeterministico)
  4. Rastreabilidade, registro de hiperparametros e explicacao (RegistroAuditoria)
"""
import copy
import time

from agente.auditoria import ConfiguracaoAgente, RegistroAuditoria
from agente.executor import (
    ExecutorEvidenciasOffline,
    sanitizar_evidencias_brutas,
)
from agente.prompts import (
    HIPOTESES_PADRONIZADAS,
    NIVEIS_CONFIANCA,
    PROMPT_SISTEMA_AGENTE,
    construir_prompt_passo,
)
from agente.provedores_llm import criar_cliente_llm
from rag.recuperador import RecuperadorRAG
from seguranca.politicas import DISPOSITIVOS_AUTORIZADOS
from seguranca.validador import ValidadorDeterministico


class AgenteDiagnosticoRedes:
    """Agente de diagnostico de falhas em redes com controle deterministico."""

    def __init__(
        self,
        cliente_llm=None,
        recuperador_rag=None,
        validador=None,
        configuracao: ConfiguracaoAgente | None = None,
    ):
        self.config = configuracao or ConfiguracaoAgente()
        self.recuperador = recuperador_rag or RecuperadorRAG()
        self.validador = validador or ValidadorDeterministico(politica=self.config.politica_seguranca)
        self.cliente_llm = cliente_llm or criar_cliente_llm(
            provedor=self.config.provedor_llm,
            modelo=self.config.modelo_llm,
            temperatura=self.config.temperatura,
            max_tokens=self.config.max_tokens_resposta,
        )

        # Sincroniza hiperparametros efetivos para auditoria fiel
        self.config.provedor_llm = getattr(self.cliente_llm, "provedor", self.config.provedor_llm)
        self.config.modelo_llm = getattr(self.cliente_llm, "modelo", self.config.modelo_llm)
        self.config.politica_seguranca = self.validador.nome_politica
        self.config.versao_indice_rag = self.recuperador.versao_indice

    @staticmethod
    def _incorporar_resultado_observacao(observacoes, decisao, resultado_exec):
        disp = decisao["dispositivo"]
        op = decisao["operacao"]
        params = decisao.get("parametros_normalizados", {})
        obs_disp = observacoes.setdefault(disp, {})
        sucesso_exec = bool(resultado_exec.get("sucesso_execucao"))
        dados = resultado_exec.get("dados")

        if op == "consultar_interfaces":
            sub = params.get("subcomando", "estado")
            obs_disp.setdefault("interfaces", {})[sub] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "consultar_rotas":
            obs_disp["rotas"] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "consultar_acl":
            obs_disp["acl"] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "consultar_tc":
            obs_disp["tc"] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "testar_ping":
            obs_disp["ping"] = (
                dados if (sucesso_exec and isinstance(dados, dict))
                else {"sucesso": None, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "testar_dns":
            obs_disp["dns"] = (
                dados if (sucesso_exec and isinstance(dados, dict))
                else {"resolucao_correta": None, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "testar_http":
            obs_disp["http"] = (
                dados if (sucesso_exec and isinstance(dados, dict))
                else {"servico_disponivel": None, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "investigar_caminho":
            obs_disp["caminho"] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "aviso": resultado_exec.get("aviso", "")}
            )
        elif op == "testar_desempenho":
            obs_disp["desempenho"] = (
                dados if isinstance(dados, dict)
                else {"sucesso": False, "vazao_mbps": None, "aviso": resultado_exec.get("aviso", "")}
            )

    @staticmethod
    def _normalizar_relatorio_final(resposta, trechos_rag_acumulados):
        hipotese = str(resposta.get("hipotese", "evidencias_insuficientes")).strip()
        if hipotese not in HIPOTESES_PADRONIZADAS:
            hipotese = "evidencias_insuficientes"

        confianca = str(resposta.get("confianca", "indeterminada")).strip()
        if confianca not in NIVEIS_CONFIANCA:
            confianca = "indeterminada"

        evidencias = resposta.get("evidencias_utilizadas") or resposta.get("evidencias") or []
        if isinstance(evidencias, str):
            evidencias = [evidencias]

        recomendacoes = resposta.get("recomendacoes_correcao") or []
        if isinstance(recomendacoes, str):
            recomendacoes = [recomendacoes]

        ids_validos_rag = {t["chunk_id"] for t in trechos_rag_acumulados}
        citadas = [
            cid for cid in (resposta.get("fontes_rag_citadas") or [])
            if isinstance(cid, str) and (not ids_validos_rag or cid in ids_validos_rag)
        ]

        # Mantem compatibilidade direta com as chaves esperadas por avaliar_diagnostico.py
        # ('hipotese', 'confianca', 'evidencias') + campos estendidos da Etapa 7!
        return {
            "hipotese": hipotese,
            "confianca": confianca,
            "evidencias": list(evidencias),
            "diagnostico_fundamentado": str(resposta.get("diagnostico_fundamentado", "")),
            "hipoteses_descartadas": list(resposta.get("hipoteses_descartadas") or []),
            "fontes_rag_citadas": citadas,
            "recomendacoes_correcao": list(recomendacoes),
            "limitacoes_investigacao": str(resposta.get("limitacoes_investigacao", "")),
        }

    def diagnosticar(
        self,
        dispositivo="client1",
        evidencias_rede=None,
        executor=None,
        latencia_referencia=None,
        identificador_sessao=None,
    ):
        """Executa o ciclo completo de diagnostico para um dispositivo alvo.

        Pode receber:
          - `evidencias_rede` (dict carregado de evidencias_caso_XX.json) para
            execucao offline reproduzivel (cria ExecutorEvidenciasOffline), OU
          - `executor` explicito (ex.: ExecutorMininetAtivo conectado a topologia).
        """
        inicio_total = time.monotonic()
        auditoria = RegistroAuditoria(
            dispositivo_alvo=dispositivo,
            configuracao=copy.deepcopy(self.config),
            identificador_sessao=identificador_sessao,
        )

        if executor is None:
            if evidencias_rede is None:
                raise ValueError("Forneca 'evidencias_rede' ou um 'executor' controlado.")
            executor = ExecutorEvidenciasOffline(evidencias_rede)

        # Inicializa estado de observacoes conforme modo ('progressivo' vs 'completo')
        observacoes = {nome: {} for nome in DISPOSITIVOS_AUTORIZADOS}
        if self.config.modo_evidencias == "completo" and evidencias_rede is not None:
            limpas = sanitizar_evidencias_brutas(evidencias_rede)
            for nome_d, dados_d in limpas.get("dispositivos", {}).items():
                if nome_d in observacoes and isinstance(dados_d, dict):
                    # Em politica restritiva, preserva o isolamento de ACL de server/router1
                    copia_d = copy.deepcopy(dados_d)
                    if self.validador.nome_politica == "restritiva" and nome_d in ("server", "router1"):
                        copia_d.pop("acl", None)
                    observacoes[nome_d] = copia_d

        # Recuperacao RAG inicial
        consulta_inicial = RecuperadorRAG.construir_consulta_por_evidencias(
            observacoes, dispositivo=dispositivo
        )
        trechos_rag = self.recuperador.recuperar(
            consulta_inicial,
            top_k=self.config.top_k_rag,
            score_minimo=self.config.score_minimo_rag,
        )
        auditoria.registrar_consulta_rag(0, consulta_inicial, trechos_rag)
        mapa_rag = {t["chunk_id"]: t for t in trechos_rag}

        historico_passos = []
        relatorio_final = None
        max_it = max(1, int(self.config.max_iteracoes))

        for iteracao in range(1, max_it + 2):
            forcar_conclusao = iteracao > max_it
            prompt_passo = construir_prompt_passo(
                dispositivo_alvo=dispositivo,
                iteracao=min(iteracao, max_it),
                max_iteracoes=max_it,
                latencia_referencia_ms=latencia_referencia,
                observacoes_atuais=observacoes,
                historico_passos=historico_passos,
                trechos_rag=list(mapa_rag.values()),
                forcar_conclusao=forcar_conclusao,
            )

            saida_llm = self.cliente_llm.gerar_decisao(PROMPT_SISTEMA_AGENTE, prompt_passo)
            resposta = saida_llm["resposta"]
            uso_tokens = saida_llm.get("uso_tokens", {})
            latencia_ms = saida_llm.get("latencia_ms", 0.0)
            acao = resposta.get("acao", "concluir_diagnostico")

            # Busca RAG complementar solicitada no passo
            consulta_extra = resposta.get("consulta_rag") or resposta.get("consulta_rag_adicional")
            if isinstance(consulta_extra, str) and consulta_extra.strip():
                novos_trechos = self.recuperador.recuperar(
                    consulta_extra,
                    top_k=self.config.top_k_rag,
                    score_minimo=self.config.score_minimo_rag,
                )
                auditoria.registrar_consulta_rag(iteracao, consulta_extra, novos_trechos)
                for nt in novos_trechos:
                    mapa_rag[nt["chunk_id"]] = nt

            if acao == "consultar_rag" and not forcar_conclusao:
                auditoria.registrar_passo(
                    iteracao=iteracao,
                    acao_modelo="consultar_rag",
                    resposta_modelo=resposta,
                    uso_tokens=uso_tokens,
                    latencia_llm_ms=latencia_ms,
                )
                historico_passos.append({
                    "iteracao": iteracao,
                    "acao": "consultar_rag",
                    "consulta_rag": consulta_extra,
                })
                continue

            if acao == "solicitar_teste" and not forcar_conclusao:
                solicitacao = resposta.get("solicitacao_teste") or {}
                decisao = self.validador.validar_solicitacao(solicitacao)
                resultado_exec = None

                if decisao["autorizado"]:
                    resultado_exec = executor.executar_decisao(decisao)
                    self._incorporar_resultado_observacao(observacoes, decisao, resultado_exec)

                auditoria.registrar_passo(
                    iteracao=iteracao,
                    acao_modelo="solicitar_teste",
                    resposta_modelo=resposta,
                    uso_tokens=uso_tokens,
                    latencia_llm_ms=latencia_ms,
                    decisao_validador=decisao,
                    resultado_execucao=resultado_exec,
                )
                historico_passos.append({
                    "iteracao": iteracao,
                    "acao": "solicitar_teste",
                    "solicitacao_teste": solicitacao,
                    "decisao_validador": {
                        "autorizado": decisao["autorizado"],
                        "codigo_motivo": decisao["codigo_motivo"],
                        "motivo": decisao["motivo"],
                    },
                    "sucesso_execucao": (
                        resultado_exec.get("sucesso_execucao")
                        if isinstance(resultado_exec, dict) else False
                    ),
                })
                continue

            # Conclusao do diagnostico (ou encerramento no teto de iteracoes)
            relatorio_final = self._normalizar_relatorio_final(
                resposta, list(mapa_rag.values())
            )
            auditoria.registrar_passo(
                iteracao=iteracao,
                acao_modelo="concluir_diagnostico",
                resposta_modelo=resposta,
                uso_tokens=uso_tokens,
                latencia_llm_ms=latencia_ms,
            )
            break

        if relatorio_final is None:
            relatorio_final = {
                "hipotese": "evidencias_insuficientes",
                "confianca": "indeterminada",
                "evidencias": ["Limite maximo de iteracoes atingido sem conclusao estruturada."],
                "diagnostico_fundamentado": "A investigacao atingiu o limite de iteracoes sem convergir.",
                "hipoteses_descartadas": [],
                "fontes_rag_citadas": [],
                "recomendacoes_correcao": ["Revisar manualmente os logs dos dispositivos no laboratorio."],
                "limitacoes_investigacao": "Encerramento por limite de iteracoes.",
            }

        duracao_total = time.monotonic() - inicio_total
        auditoria.finalizar(relatorio_final, duracao_total)
        relatorio_final["auditoria"] = auditoria.para_dict()
        return relatorio_final, auditoria
