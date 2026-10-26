"""Modulo RAG: base documental tecnica, indexacao anti-vazamento e recuperacao."""
from rag.indexador import (
    ARQUIVO_CATALOGO_PADRAO,
    ARQUIVO_INDICE_PADRAO,
    PASTA_CORPUS_PADRAO,
    ViolacaoSegurancaCorpusError,
    ViolacaoSeparacaoDadosError,
    construir_indice,
    fatiar_markdown,
    tokenizar_tecnico,
    verificar_caminho_seguro,
    verificar_documento_sem_injecao_prompt,
)
from rag.recuperador import (
    MAPA_HIPOTESE_FONTES_ESPERADAS,
    RecuperadorRAG,
    avaliar_aderencia_citacoes,
)

__all__ = [
    "ARQUIVO_CATALOGO_PADRAO",
    "ARQUIVO_INDICE_PADRAO",
    "MAPA_HIPOTESE_FONTES_ESPERADAS",
    "PASTA_CORPUS_PADRAO",
    "RecuperadorRAG",
    "ViolacaoSegurancaCorpusError",
    "ViolacaoSeparacaoDadosError",
    "avaliar_aderencia_citacoes",
    "construir_indice",
    "fatiar_markdown",
    "tokenizar_tecnico",
    "verificar_caminho_seguro",
    "verificar_documento_sem_injecao_prompt",
]
