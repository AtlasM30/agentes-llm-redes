"""Modulo RAG: base documental tecnica, indexacao anti-vazamento e recuperacao."""
from rag.indexador import (
    ARQUIVO_CATALOGO_PADRAO,
    ARQUIVO_INDICE_PADRAO,
    PASTA_CORPUS_PADRAO,
    ViolacaoSeparacaoDadosError,
    construir_indice,
    fatiar_markdown,
    tokenizar_tecnico,
    verificar_caminho_seguro,
)
from rag.recuperador import RecuperadorRAG

__all__ = [
    "ARQUIVO_CATALOGO_PADRAO",
    "ARQUIVO_INDICE_PADRAO",
    "PASTA_CORPUS_PADRAO",
    "RecuperadorRAG",
    "ViolacaoSeparacaoDadosError",
    "construir_indice",
    "fatiar_markdown",
    "tokenizar_tecnico",
    "verificar_caminho_seguro",
]
