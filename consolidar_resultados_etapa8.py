from pathlib import Path
from collections import Counter, defaultdict
from statistics import mean, median, stdev
import csv
import json

RAIZ = Path(__file__).resolve().parent

BASE = RAIZ / "experimentos_etapa8"
BATERIA = BASE / "baterias" / "20261026T061113Z"
RECUPERACOES = BASE / "recuperacoes"
GABARITO = RAIZ / "avaliacao" / "gabarito_avaliacao.json"
SAIDA = BASE / "consolidados"

POLITICAS = ("padrao", "restritiva")
CLIENTES = ("client1", "client2")
REPETICOES = range(1, 4)
CASOS = range(6)


def salvar_json(caminho, dados):
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def estatisticas(valores):
    numeros = [
        float(v) for v in valores
        if isinstance(v, (int, float))
        and not isinstance(v, bool)
    ]

    if not numeros:
        return {
            "n": 0,
            "media": None,
            "mediana": None,
            "desvio_padrao": None
        }

    return {
        "n": len(numeros),
        "media": round(mean(numeros), 4),
        "mediana": round(median(numeros), 4),
        "desvio_padrao": (
            round(stdev(numeros), 4)
            if len(numeros) > 1 else None
        )
    }


def localizar_auditoria(politica, repeticao, caso, cliente):
    nome = (
        f"auditoria_caso_{caso:02d}_"
        f"{politica}_{cliente}.json"
    )

    original = (
        BATERIA / politica
        / f"repeticao_{repeticao:02d}"
        / f"caso_{caso:02d}"
        / "auditoria" / nome
    )

    candidatos = []

    if original.is_file():
        candidatos.append(("original", original))

    if RECUPERACOES.exists():
        for lote in sorted(RECUPERACOES.iterdir()):
            if not lote.is_dir():
                continue

            pasta = (
                lote / politica
                / f"repeticao_{repeticao:02d}"
                / f"caso_{caso:02d}"
                / cliente
            )

            arquivo = pasta / "auditoria" / nome
            status = pasta / "status.json"

            if not arquivo.is_file() or not status.is_file():
                continue

            dados_status = json.loads(
                status.read_text(encoding="utf-8")
            )

            identidade_correta = (
                dados_status.get("politica") == politica
                and dados_status.get("repeticao") == repeticao
                and dados_status.get("caso") == caso
                and dados_status.get("cliente") == cliente
            )

            if (
                dados_status.get("concluido") is True
                and identidade_correta
            ):
                candidatos.append(("recuperacao", arquivo))

    if len(candidatos) != 1:
        raise ValueError(
            f"Esperada uma auditoria para "
            f"{politica}/rep{repeticao}/caso{caso}/{cliente}; "
            f"encontradas {len(candidatos)}."
        )

    return candidatos[0]


def avaliar():
    SAIDA.mkdir(parents=True, exist_ok=True)

    gabarito = json.loads(
        GABARITO.read_text(encoding="utf-8")
    )["casos"]

    registros = []

    for politica in POLITICAS:
        for repeticao in REPETICOES:
            for caso in CASOS:
                identificador = f"caso_{caso:02d}"

                for cliente in CLIENTES:
                    origem, arquivo = localizar_auditoria(
                        politica, repeticao, caso, cliente
                    )

                    auditoria = json.loads(
                        arquivo.read_text(encoding="utf-8")
                    )

                    final = auditoria["resultado_final"]
                    metricas = auditoria["metricas_sessao"]
                    config = auditoria["hiperparametros"]

                    hipotese = final["hipotese"]
                    esperado = gabarito[identificador][cliente]

                    if auditoria["dispositivo_alvo"] != cliente:
                        raise ValueError(
                            f"Cliente incorreto: {arquivo}"
                        )

                    if config["politica_seguranca"] != politica:
                        raise ValueError(
                            f"Politica incorreta: {arquivo}"
                        )

                    if (
                        config.get("provedor_llm") != "gemini"
                        or config.get("eh_llm_real") is not True
                    ):
                        raise ValueError(
                            f"Provedor inesperado: {arquivo}"
                        )

                    registro = {
                        "politica": politica,
                        "repeticao": repeticao,
                        "caso": identificador,
                        "cliente": cliente,
                        "origem": origem,
                        "arquivo_auditoria": str(
                            arquivo.relative_to(RAIZ)
                        ),
                        "modelo": config["modelo_llm"],
                        "hipotese_esperada": esperado,
                        "hipotese_obtida": hipotese,
                        "acertou": int(hipotese == esperado),
                        "confianca": final.get("confianca"),
                        "tempo_s": metricas.get(
                            "tempo_diagnostico_s"
                        ),
                        "tokens_prompt": metricas.get(
                            "tokens_prompt"
                        ),
                        "tokens_completion": metricas.get(
                            "tokens_completion"
                        ),
                        "tokens_total": metricas.get(
                            "tokens_total"
                        ),
                        "chamadas_llm": metricas.get(
                            "chamadas_llm"
                        ),
                        "testes_propostos": metricas.get(
                            "testes_propostos"
                        ),
                        "testes_autorizados": metricas.get(
                            "testes_autorizados_executados"
                        ),
                        "testes_bloqueados": metricas.get(
                            "testes_bloqueados"
                        ),
                        "erros_formato_recuperados": metricas.get(
                            "erros_formato_recuperados"
                        ),
                        "aderencia_rag": metricas.get(
                            "taxa_aderencia_citacoes_rag"
                        ),
                    }

                    registros.append(registro)

    if len(registros) != 72:
        raise ValueError(
            f"Esperados 72 registros; encontrados {len(registros)}."
        )

    # Salvar todas as classificacoes individuais.
    csv_detalhado = SAIDA / "diagnosticos_detalhados.csv"

    with csv_detalhado.open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(registros[0].keys())
        )
        writer.writeheader()
        writer.writerows(registros)

    salvar_json(
        SAIDA / "diagnosticos_detalhados.json",
        registros
    )

    # Resumir cada politica separadamente.
    resumos = {}

    for politica in POLITICAS:
        dados = [
            r for r in registros
            if r["politica"] == politica
        ]

        acertos = sum(r["acertou"] for r in dados)

        resumo = {
            "total": len(dados),
            "acertos": acertos,
            "erros": len(dados) - acertos,
            "acuracia_percentual": round(
                100 * acertos / len(dados), 2
            ),
            "origem_registros": dict(
                Counter(r["origem"] for r in dados)
            ),
            "tempo_s": estatisticas(
                [r["tempo_s"] for r in dados]
            ),
            "tokens_total": estatisticas(
                [r["tokens_total"] for r in dados]
            ),
            "testes_propostos_total": sum(
                r["testes_propostos"] or 0 for r in dados
            ),
            "testes_autorizados_total": sum(
                r["testes_autorizados"] or 0 for r in dados
            ),
            "testes_bloqueados_total": sum(
                r["testes_bloqueados"] or 0 for r in dados
            ),
            "aderencia_rag": estatisticas(
                [r["aderencia_rag"] for r in dados]
            ),
            "acuracia_por_repeticao": {},
            "acuracia_por_caso": {},
            "matriz_confusao": {}
        }

        for repeticao in REPETICOES:
            sub = [
                r for r in dados
                if r["repeticao"] == repeticao
            ]
            resumo["acuracia_por_repeticao"][
                str(repeticao)
            ] = round(
                100 * sum(r["acertou"] for r in sub)
                / len(sub), 2
            )

        for caso in CASOS:
            chave = f"caso_{caso:02d}"
            sub = [
                r for r in dados if r["caso"] == chave
            ]
            resumo["acuracia_por_caso"][chave] = {
                "total": len(sub),
                "acertos": sum(r["acertou"] for r in sub)
            }

        matriz = defaultdict(Counter)

        for r in dados:
            matriz[r["hipotese_esperada"]][
                r["hipotese_obtida"]
            ] += 1

        resumo["matriz_confusao"] = {
            esperado: dict(obtidos)
            for esperado, obtidos in matriz.items()
        }

        resumos[politica] = resumo

    salvar_json(
        SAIDA / "resumo_comparativo.json",
        {
            "total_diagnosticos": len(registros),
            "metodologia": (
                "Bateria original mais recuperacoes; "
                "falhas operacionais originais preservadas."
            ),
            "politicas": resumos
        }
    )

    with (SAIDA / "resumo_comparativo.csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow([
            "politica", "total", "acertos", "erros",
            "acuracia_percentual",
            "tempo_medio_s", "tokens_medios",
            "testes_bloqueados"
        ])

        for politica, r in resumos.items():
            writer.writerow([
                politica,
                r["total"],
                r["acertos"],
                r["erros"],
                r["acuracia_percentual"],
                r["tempo_s"]["media"],
                r["tokens_total"]["media"],
                r["testes_bloqueados_total"]
            ])

    print("=== CONSOLIDACAO DA ETAPA 8 ===")
    print(f"Diagnosticos processados: {len(registros)}")

    for politica, r in resumos.items():
        print(
            f"{politica}: {r['acertos']}/{r['total']} "
            f"acertos ({r['acuracia_percentual']}%)"
        )
        print(
            f"  Tempo medio: {r['tempo_s']['media']} s"
        )
        print(
            f"  Tokens medios: {r['tokens_total']['media']}"
        )
        print(
            f"  Testes bloqueados: "
            f"{r['testes_bloqueados_total']}"
        )

    print(f"Arquivos gerados em: {SAIDA}")


if __name__ == "__main__":
    avaliar()
