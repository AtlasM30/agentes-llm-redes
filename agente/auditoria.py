"""Mecanismos de Auditoria, Registro de Hiperparametros e Explicabilidade (Etapa 7).

Registra todas as decisoes de inferencia, consultas RAG, validacoes de
seguranca, tempo, consumo de tokens e resiliencia pos-bloqueio para
reconstrucao integral dos experimentos (Secao 4.4 e 4.5 da monografia).
"""
import json
import platform
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ConfiguracaoAgente:
    """Hiperparametros explicitos e auditaveis da solucao proposta."""

    provedor_llm: str = "simulado"
    modelo_llm: str = "simulado-react-rede-v1"
    temperatura: float = 0.0
    max_tokens_resposta: int = 1200
    max_iteracoes: int = 8
    top_k_rag: int = 4
    score_minimo_rag: float = 0.05
    politica_seguranca: str = "padrao"
    modo_evidencias: str = "progressivo"  # 'progressivo' ou 'completo'
    versao_indice_rag: str = ""
    versao_python: str = field(default_factory=platform.python_version)

    def para_dict(self):
        return asdict(self)


class RegistroAuditoria:
    """Rastreador imutavel por sessao de diagnostico."""

    def __init__(self, dispositivo_alvo, configuracao: ConfiguracaoAgente, identificador_sessao=None):
        self.execucao_id = identificador_sessao or str(uuid.uuid4())[:12]
        self.dispositivo_alvo = dispositivo_alvo
        self.configuracao = configuracao
        self.iniciado_em_utc = datetime.now(timezone.utc).isoformat()
        self.finalizado_em_utc = None
        self.duracao_total_s = 0.0

        self.consultas_rag = []
        self.passos = []
        self.decisoes_validador = []
        self.resultado_final = None

        self.tokens_prompt_total = 0
        self.tokens_completion_total = 0
        self.tokens_total = 0
        self.chamadas_llm = 0

    def registrar_consulta_rag(self, iteracao, consulta, trechos):
        self.consultas_rag.append({
            "iteracao": iteracao,
            "consulta": consulta,
            "quantidade_recuperada": len(trechos),
            "trechos": [
                {
                    "chunk_id": t["chunk_id"],
                    "fonte_id": t["fonte_id"],
                    "titulo": t["titulo"],
                    "tema": t["tema"],
                    "score": t["score"],
                }
                for t in trechos
            ],
        })

    def registrar_passo(
        self,
        iteracao,
        acao_modelo,
        resposta_modelo,
        uso_tokens,
        latencia_llm_ms,
        decisao_validador=None,
        resultado_execucao=None,
    ):
        self.chamadas_llm += 1
        p_tok = int((uso_tokens or {}).get("prompt_tokens", 0))
        c_tok = int((uso_tokens or {}).get("completion_tokens", 0))
        t_tok = int((uso_tokens or {}).get("total_tokens", p_tok + c_tok))
        self.tokens_prompt_total += p_tok
        self.tokens_completion_total += c_tok
        self.tokens_total += t_tok

        if decisao_validador is not None:
            self.decisoes_validador.append(decisao_validador)

        resumo_exec = None
        if isinstance(resultado_execucao, dict):
            resumo_exec = {
                "sucesso_execucao": resultado_execucao.get("sucesso_execucao"),
                "operacao": resultado_execucao.get("operacao"),
                "aviso": resultado_execucao.get("aviso"),
            }

        self.passos.append({
            "iteracao": iteracao,
            "acao_modelo": acao_modelo,
            "raciocinio": resposta_modelo.get("raciocinio_atual") or resposta_modelo.get("diagnostico_fundamentado", "")[:240],
            "hipoteses_em_aberto": resposta_modelo.get("hipoteses_em_aberto"),
            "solicitacao_teste": resposta_modelo.get("solicitacao_teste"),
            "decisao_validador": decisao_validador,
            "resumo_execucao": resumo_exec,
            "uso_tokens": {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": t_tok},
            "latencia_llm_ms": latencia_llm_ms,
        })

    def finalizar(self, relatorio_final, duracao_s):
        self.finalizado_em_utc = datetime.now(timezone.utc).isoformat()
        self.duracao_total_s = round(float(duracao_s), 4)
        self.resultado_final = {
            k: v for k, v in (relatorio_final or {}).items() if k != "auditoria"
        }

    def calcular_metricas_sessao(self):
        propostos = len(self.decisoes_validador)
        autorizados = sum(1 for d in self.decisoes_validador if d.get("autorizado") is True)
        bloqueados = propostos - autorizados
        concluiu_com_bloqueio = bool(
            bloqueados > 0
            and self.resultado_final is not None
            and self.resultado_final.get("hipotese") not in (None, "erro_execucao")
        )
        # Verifica se apos um bloqueio o agente propos outro teste autorizado ou concluiu de forma segura
        prosseguiu_apos_bloqueio = False
        if bloqueados > 0:
            indices_bloqueio = [
                i for i, p in enumerate(self.passos)
                if (p.get("decisao_validador") or {}).get("autorizado") is False
            ]
            if indices_bloqueio and indices_bloqueio[0] < len(self.passos) - 1:
                prosseguiu_apos_bloqueio = True

        return {
            "total_iteracoes": len(self.passos),
            "chamadas_llm": self.chamadas_llm,
            "testes_propostos": propostos,
            "testes_autorizados_executados": autorizados,
            "testes_bloqueados": bloqueados,
            "houve_bloqueio": bloqueados > 0,
            "adaptou_apos_bloqueio": prosseguiu_apos_bloqueio,
            "concluiu_apos_bloqueio": concluiu_com_bloqueio,
            "consultas_rag_realizadas": len(self.consultas_rag),
            "tokens_prompt": self.tokens_prompt_total,
            "tokens_completion": self.tokens_completion_total,
            "tokens_total": self.tokens_total,
            "tempo_diagnostico_s": self.duracao_total_s,
        }

    def para_dict(self):
        return {
            "execucao_id": self.execucao_id,
            "dispositivo_alvo": self.dispositivo_alvo,
            "iniciado_em_utc": self.iniciado_em_utc,
            "finalizado_em_utc": self.finalizado_em_utc,
            "hiperparametros": self.configuracao.para_dict(),
            "metricas_sessao": self.calcular_metricas_sessao(),
            "consultas_rag": self.consultas_rag,
            "passos_investigacao": self.passos,
            "resultado_final": self.resultado_final,
        }

    def salvar_json(self, pasta_destino):
        pasta = Path(pasta_destino)
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"auditoria_{self.execucao_id}_{self.dispositivo_alvo}.json"
        caminho.write_text(
            json.dumps(self.para_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return caminho

    def formatar_relatorio_legivel(self):
        res = self.resultado_final or {}
        met = self.calcular_metricas_sessao()
        linhas = [
            f"Dispositivo analisado : {self.dispositivo_alvo}",
            f"Hipotese final        : {res.get('hipotese', 'indefinida')}",
            f"Confianca             : {res.get('confianca', 'indeterminada')}",
            f"Politica de seguranca : {self.configuracao.politica_seguranca}",
            f"Modelo / Provedor     : {self.configuracao.provedor_llm} ({self.configuracao.modelo_llm})",
            f"Testes (prop/aut/bloq): {met['testes_propostos']} / {met['testes_autorizados_executados']} / {met['testes_bloqueados']}",
            f"Tokens / Tempo        : {met['tokens_total']} tokens / {met['tempo_diagnostico_s']:.3f} s",
            "Evidencias utilizadas :",
        ]
        for ev in res.get("evidencias", []):
            linhas.append(f"  - {ev}")
        linhas.append(f"Justificativa         : {res.get('diagnostico_fundamentado', '')}")
        if res.get("fontes_rag_citadas"):
            linhas.append(f"Fontes RAG citadas    : {', '.join(res['fontes_rag_citadas'])}")
        if res.get("recomendacoes_correcao"):
            linhas.append("Recomendacoes (admin) :")
            for rec in res["recomendacoes_correcao"]:
                linhas.append(f"  * {rec}")
        return "\n".join(linhas)
