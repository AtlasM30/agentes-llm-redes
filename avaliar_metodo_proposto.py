#!/usr/bin/env python3
"""Avaliador completo do Metodo Proposto — Etapa 7 / preparacao Etapa 8.

Avalia separadamente as duas frentes previstas na Secao 4.4 e 4.5 da monografia,
mantendo o gabarito restrito exclusivamente ao modulo avaliador:
  1. Frente de Seguranca: ValidadorDeterministico sob politicas 'padrao' e
     'restritiva' (taxa de bloqueio correto, autorizacao indevida e bloqueio indevido).
  2. Frente de Qualidade Diagnostica, Resiliencia e Custo: Agente LLM + RAG +
     Validador comparado com o gabarito e com o baseline tradicional (Etapa 6).

Exemplos:
    python3 avaliar_metodo_proposto.py --apenas-seguranca
    python3 avaliar_metodo_proposto.py --provedor simulado --comparar-politicas
    python3 avaliar_metodo_proposto.py --provedor gemini --modelo gemini-2.5-flash
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agente.auditoria import ConfiguracaoAgente
from agente.diagnostico_agente import AgenteDiagnosticoRedes
from agente.provedores_llm import criar_cliente_llm
from diagnostico.pipeline import carregar_evidencias
from diagnostico.regras import diagnosticar_cliente
from rag.recuperador import RecuperadorRAG
from seguranca.catalogo_solicitacoes import avaliar_validador
from seguranca.validador import ValidadorDeterministico


def _latencia_ref(dados, nome):
    return dados["dispositivos"][nome].get("ping", {}).get("latencia_media_ms")


def avaliar_frente_seguranca():
    """Executa o benchmark de seguranca nas politicas 'padrao' e 'restritiva'."""
    return {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "politicas": {
            "padrao": avaliar_validador("padrao"),
            "restritiva": avaliar_validador("restritiva"),
        },
    }


def avaliar_agente_nos_casos(
    pasta_logs,
    arquivo_gabarito,
    provedor="simulado",
    modelo=None,
    temperatura=0.0,
    top_k=4,
    max_iteracoes=8,
    politica="padrao",
    modo_evidencias="progressivo",
):
    """Confronta previsoes do Agente LLM com o gabarito e com o baseline tradicional."""
    with Path(arquivo_gabarito).open("r", encoding="utf-8") as arq:
        gabarito = json.load(arq)
    if not isinstance(gabarito, dict) or not isinstance(gabarito.get("casos"), dict):
        raise ValueError("O gabarito deve conter um objeto 'casos'.")

    recuperador = RecuperadorRAG()
    validador = ValidadorDeterministico(politica=politica)
    cliente = criar_cliente_llm(provedor=provedor, modelo=modelo, temperatura=temperatura)
    config = ConfiguracaoAgente(
        provedor_llm=cliente.provedor,
        modelo_llm=cliente.modelo,
        temperatura=temperatura,
        max_iteracoes=max_iteracoes,
        top_k_rag=top_k,
        politica_seguranca=politica,
        modo_evidencias=modo_evidencias,
        versao_indice_rag=recuperador.versao_indice,
    )
    agente = AgenteDiagnosticoRedes(
        cliente_llm=cliente,
        recuperador_rag=recuperador,
        validador=validador,
        configuracao=config,
    )

    normal = carregar_evidencias(Path(pasta_logs) / "evidencias_caso_00.json")
    referencias = {nome: _latencia_ref(normal, nome) for nome in ("client1", "client2")}

    resultados = []
    erros = []

    for identificador, rotulos in sorted(gabarito["casos"].items()):
        arquivo_caso = Path(pasta_logs) / f"evidencias_{identificador}.json"
        if not arquivo_caso.is_file():
            erros.append(f"Evidencia ausente: {arquivo_caso}")
            continue
        try:
            dados = carregar_evidencias(arquivo_caso)
            servidor = dados["dispositivos"]["server"]
            for nome in ("client1", "client2"):
                esperado = rotulos.get(nome)
                if not isinstance(esperado, str):
                    erros.append(f"Rotulo ausente: {identificador}/{nome}")
                    continue

                relatorio_agente, auditoria = agente.diagnosticar(
                    dispositivo=nome,
                    evidencias_rede=dados,
                    latencia_referencia=referencias[nome],
                    identificador_sessao=f"{identificador}_{politica}",
                )
                baseline = diagnosticar_cliente(
                    dados["dispositivos"][nome],
                    nome=nome,
                    servidor=servidor,
                    latencia_referencia=referencias[nome],
                )
                met_sessao = auditoria.calcular_metricas_sessao()
                previsto = relatorio_agente["hipotese"]

                resultados.append({
                    "caso": identificador,
                    "dispositivo": nome,
                    "politica": politica,
                    "esperado": esperado,
                    "previsto_agente": previsto,
                    "previsto_baseline_regras": baseline["hipotese"],
                    "acerto_agente": previsto == esperado,
                    "concordancia_com_baseline": previsto == baseline["hipotese"],
                    "confianca": relatorio_agente["confianca"],
                    "testes_propostos": met_sessao["testes_propostos"],
                    "testes_autorizados": met_sessao["testes_autorizados_executados"],
                    "testes_bloqueados": met_sessao["testes_bloqueados"],
                    "houve_bloqueio": met_sessao["houve_bloqueio"],
                    "tokens_total": met_sessao["tokens_total"],
                    "tempo_diagnostico_s": met_sessao["tempo_diagnostico_s"],
                    "fontes_rag_citadas": relatorio_agente["fontes_rag_citadas"],
                    "evidencias_utilizadas": relatorio_agente["evidencias"],
                    "recomendacoes_correcao": relatorio_agente["recomendacoes_correcao"],
                })
        except Exception as exc:
            erros.append(f"{identificador}: {type(exc).__name__}: {exc}")

    total = len(resultados)
    acertos = sum(r["acerto_agente"] for r in resultados)
    normais_esperados = [r for r in resultados if r["esperado"] == "sem_anomalia_detectada"]
    normais_corretos = sum(r["acerto_agente"] for r in normais_esperados)
    com_bloqueio = [r for r in resultados if r["houve_bloqueio"]]
    resilientes_corretos = sum(r["acerto_agente"] for r in com_bloqueio)
    matriz = Counter((r["esperado"], r["previsto_agente"]) for r in resultados)

    return {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "hiperparametros": config.para_dict(),
        "total_avaliado": total,
        "acertos": acertos,
        "erros_classificacao": total - acertos,
        "acuracia_diagnostica": round(acertos / total, 4) if total else None,
        "reconhecimento_funcionamento_normal": (
            round(normais_corretos / len(normais_esperados), 4)
            if normais_esperados else None
        ),
        "sessoes_com_bloqueio": len(com_bloqueio),
        "resiliencia_acerto_apos_bloqueio": (
            round(resilientes_corretos / len(com_bloqueio), 4)
            if com_bloqueio else None
        ),
        "media_testes_por_diagnostico": (
            round(sum(r["testes_autorizados"] for r in resultados) / total, 2)
            if total else None
        ),
        "tokens_consumidos_total": sum(r["tokens_total"] for r in resultados),
        "tempo_total_s": round(sum(r["tempo_diagnostico_s"] for r in resultados), 4),
        "matriz_confusao": [
            {"esperado": esp, "previsto": prev, "quantidade": qtd}
            for (esp, prev), qtd in sorted(matriz.items())
        ],
        "resultados": resultados,
        "problemas_leitura": erros,
        "nota": (
            "O gabarito e lido exclusivamente neste avaliador apos a inferencia; "
            "evidencias sao sanitizadas antes de entrarem no Agente LLM."
        ),
    }


def salvar_seguranca(relatorio_seg, pasta_saida):
    pasta_saida.mkdir(parents=True, exist_ok=True)
    arq_json = pasta_saida / "avaliacao_seguranca_validador.json"
    arq_csv = pasta_saida / "avaliacao_seguranca_validador.csv"
    arq_json.write_text(json.dumps(relatorio_seg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    linhas = []
    for pol in ("padrao", "restritiva"):
        linhas.extend(relatorio_seg["politicas"][pol]["resultados"])

    with arq_csv.open("w", newline="", encoding="utf-8") as arq:
        campos = [
            "id", "categoria", "politica", "esperado_autorizado",
            "obtido_autorizado", "concordante", "codigo_motivo",
            "aspecto_verificado", "motivo",
        ]
        writer = csv.DictWriter(arq, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)
    return arq_json, arq_csv


def salvar_diagnostico(relatorio_diag, pasta_saida, sufixo="padrao"):
    pasta_saida.mkdir(parents=True, exist_ok=True)
    arq_json = pasta_saida / f"avaliacao_agente_{sufixo}.json"
    arq_csv = pasta_saida / f"avaliacao_agente_{sufixo}.csv"
    arq_json.write_text(json.dumps(relatorio_diag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with arq_csv.open("w", newline="", encoding="utf-8") as arq:
        campos = [
            "caso", "dispositivo", "politica", "esperado", "previsto_agente",
            "previsto_baseline_regras", "acerto_agente", "concordancia_com_baseline",
            "confianca", "testes_propostos", "testes_autorizados", "testes_bloqueados",
            "tokens_total", "tempo_diagnostico_s", "fontes_rag_citadas",
        ]
        writer = csv.DictWriter(arq, fieldnames=campos)
        writer.writeheader()
        for r in relatorio_diag["resultados"]:
            linha = {k: r[k] for k in campos}
            linha["fontes_rag_citadas"] = " | ".join(r["fontes_rag_citadas"])
            writer.writerow(linha)
    return arq_json, arq_csv


def main():
    parser = argparse.ArgumentParser(description="Avaliacao do Metodo Proposto (Etapa 7/8)")
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    parser.add_argument("--gabarito", type=Path, default=Path("avaliacao/gabarito_avaliacao.json"))
    parser.add_argument("--saida", type=Path, default=Path("resultados_agente"))
    parser.add_argument("--provedor", default="simulado", choices=("simulado", "gemini", "openai", "groq", "ollama"))
    parser.add_argument("--modelo", default=None)
    parser.add_argument("--temperatura", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-iteracoes", type=int, default=8)
    parser.add_argument("--politica", default="padrao", choices=("padrao", "restritiva"))
    parser.add_argument("--modo-evidencias", default="progressivo", choices=("progressivo", "completo"))
    parser.add_argument("--comparar-politicas", action="store_true", help="Avalia 'padrao' e 'restritiva' lado a lado")
    parser.add_argument("--apenas-seguranca", action="store_true", help="Executa somente a avaliacao do Validador Deterministico")
    args = parser.parse_args()

    # 1. Frente de Seguranca (sempre executavel)
    rel_seg = avaliar_frente_seguranca()
    json_seg, csv_seg = salvar_seguranca(rel_seg, args.saida)
    print("=== FRENTE DE SEGURANCA — VALIDADOR DETERMINISTICO ===")
    for pol in ("padrao", "restritiva"):
        dados_pol = rel_seg["politicas"][pol]
        print(
            f"Politica '{pol}': "
            f"Bloqueio correto={dados_pol['taxa_bloqueio_correto'] * 100:.1f}% "
            f"({dados_pol['bloqueios_corretos']}/{dados_pol['total_nao_autorizadas_esperadas']}) | "
            f"Autorizacao indevida={dados_pol['taxa_autorizacao_indevida'] * 100:.1f}% | "
            f"Bloqueio indevido={dados_pol['taxa_bloqueio_indevido'] * 100:.1f}%"
        )
    print(f"Relatorios salvos em: {json_seg} e {csv_seg}")

    if args.apenas_seguranca:
        return

    if not args.gabarito.is_file() or not (args.logs / "evidencias_caso_00.json").is_file():
        print(
            "\n[AVISO] Arquivos locais restritos (logs/ ou avaliacao/gabarito_avaliacao.json) "
            "nao estao presentes neste clone. Execute na VM Ubuntu apos a coleta ou "
            "disponibilize os arquivos para rodar a Frente 1 completa."
        )
        return

    politicas = ("padrao", "restritiva") if args.comparar_politicas else (args.politica,)
    for pol in politicas:
        rel_diag = avaliar_agente_nos_casos(
            pasta_logs=args.logs,
            arquivo_gabarito=args.gabarito,
            provedor=args.provedor,
            modelo=args.modelo,
            temperatura=args.temperatura,
            top_k=args.top_k,
            max_iteracoes=args.max_iteracoes,
            politica=pol,
            modo_evidencias=args.modo_evidencias,
        )
        json_d, csv_d = salvar_diagnostico(rel_diag, args.saida, sufixo=pol)
        print(f"\n=== FRENTE DIAGNOSTICA — POLITICA '{pol.upper()}' ===")
        print(
            f"Avaliados: {rel_diag['total_avaliado']} | "
            f"Acertos: {rel_diag['acertos']} | "
            f"Acuracia: {(rel_diag['acuracia_diagnostica'] or 0) * 100:.1f}% | "
            f"Media testes: {rel_diag['media_testes_por_diagnostico']} | "
            f"Tokens: {rel_diag['tokens_consumidos_total']}"
        )
        if rel_diag["resiliencia_acerto_apos_bloqueio"] is not None:
            print(
                f"Sessoes com bloqueio: {rel_diag['sessoes_com_bloqueio']} | "
                f"Acerto pos-bloqueio: {rel_diag['resiliencia_acerto_apos_bloqueio'] * 100:.1f}%"
            )
        print(f"JSON: {json_d}\nCSV : {csv_d}")


if __name__ == "__main__":
    main()
