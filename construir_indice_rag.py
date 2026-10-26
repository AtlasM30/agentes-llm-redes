#!/usr/bin/env python3
"""Constroi e verifica o indice da base de conhecimento RAG (Etapa 7).

Uso:
    python3 construir_indice_rag.py
    python3 construir_indice_rag.py --coletar-manpages --top-k 3
"""
import argparse
from pathlib import Path

from rag.coletor_manpages import coletar_manpages_locais
from rag.indexador import (
    ARQUIVO_CATALOGO_PADRAO,
    ARQUIVO_INDICE_PADRAO,
    PASTA_CORPUS_PADRAO,
    construir_indice,
)
from rag.recuperador import RecuperadorRAG


CONSULTAS_VERIFICACAO = (
    ("Interface DOWN vs Rota", "client1-eth0 DOWN ip -br link precedencia rota ausente"),
    ("Falha de Roteamento", "ip route show default via 192.168.10.1 ausente network unreachable"),
    ("Problema DNS", "dig @192.168.20.99 app.lab.local timeout dnsmasq resolucao"),
    ("Bloqueio por ACL", "iptables -S INPUT -s 192.168.10.2 -p tcp --dport 80 -j DROP"),
    ("Congestionamento", "latencia ping alta rtt bufferbloat tc qdisc 10 Mbps iperf3"),
)


def main():
    parser = argparse.ArgumentParser(description="Indexador reproduzivel do corpus tecnico RAG")
    parser.add_argument("--corpus", type=Path, default=PASTA_CORPUS_PADRAO)
    parser.add_argument("--catalogo", type=Path, default=ARQUIVO_CATALOGO_PADRAO)
    parser.add_argument("--saida", type=Path, default=ARQUIVO_INDICE_PADRAO)
    parser.add_argument("--tamanho-chunk", type=int, default=900)
    parser.add_argument("--sobreposicao", type=int, default=120)
    parser.add_argument(
        "--coletar-manpages",
        action="store_true",
        help="Extrai tambem sinopses das manpages locais instaladas no Ubuntu",
    )
    parser.add_argument("--top-k", type=int, default=2)
    args = parser.parse_args()

    if args.coletar_manpages:
        coletadas = coletar_manpages_locais(destino_dir=args.corpus)
        print(f"Manpages locais extraidas: {len(coletadas)}")

    indice = construir_indice(
        pasta_corpus=args.corpus,
        caminho_catalogo=args.catalogo,
        caminho_saida=args.saida,
        tamanho_max_chars=args.tamanho_chunk,
        sobreposicao_chars=args.sobreposicao,
    )

    print("=== INDICE RAG CONSTRUIDO COM SUCESSO ===")
    print(f"Arquivo gerado        : {args.saida}")
    print(f"Versao SHA-256 corpus : {indice['versao_indice']}")
    print(f"Fontes catalogadas    : {indice['total_fontes']}")
    print(f"Total de trechos      : {indice['total_chunks']}")
    print(f"Media tokens/trecho   : {indice['comprimento_medio_tokens']}")

    recuperador = RecuperadorRAG(caminho_indice=args.saida, auto_construir=False)
    print("\n=== VERIFICACAO DE RECUPERACAO POR DOMINIO DE FALHA ===")
    for rotulo, consulta in CONSULTAS_VERIFICACAO:
        resultados = recuperador.recuperar(consulta, top_k=args.top_k)
        print(f"\n[{rotulo}] Consulta: {consulta}")
        for r in resultados:
            print(f"  -> {r['chunk_id']} (score={r['score']:.4f} | tema={r['tema']}): {r['secao']}")


if __name__ == "__main__":
    main()
