"""Indexador da base de conhecimento tecnico para RAG (Etapa 7).

Segmenta os documentos catalogados em rag/corpus/, anexa metadados
completos conforme documentacao/FONTES_RAG.md, bloqueia qualquer tentativa
de indexar gabaritos experimentais (anti-vazamento) e gera rag/indice_rag.json
com estatisticas lexicais/estatisticas pre-computadas (BM25 + TF-IDF).
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_RAG = Path(__file__).resolve().parent
PASTA_CORPUS_PADRAO = PASTA_RAG / "corpus"
ARQUIVO_CATALOGO_PADRAO = PASTA_RAG / "catalogo_fontes.json"
ARQUIVO_INDICE_PADRAO = PASTA_RAG / "indice_rag.json"

# Caminhos e nomes estritamente proibidos no corpus RAG (separacao obrigatoria)
PADROES_CAMINHO_PROIBIDOS = (
    "gabarito",
    "causas_reais",
    "resultados_avaliacao",
    "cenarios.py",
)

STOPWORDS_PT_EN = frozenset({
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "era", "essa", "esse", "esta", "este", "foi", "for",
    "ha", "isso", "isto", "ja", "mais", "mas", "na", "nas", "nem", "no",
    "nos", "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos", "por",
    "qual", "quando", "que", "se", "sem", "ser", "seu", "seus", "so", "sob",
    "sobre", "sua", "suas", "sao", "tambem", "tem", "ter", "um", "uma",
    "umas", "uns", "and", "are", "by", "from", "in", "is", "it", "of", "on",
    "or", "that", "the", "this", "to", "with",
})

CAMPOS_METADADOS_OBRIGATORIOS = (
    "chunk_id",
    "fonte_id",
    "titulo",
    "url",
    "versao",
    "data_acesso",
    "tema",
    "secao",
    "comandos_relevantes",
    "licenca",
    "trecho",
    "escopo_de_uso",
    "sha256",
)


class ViolacaoSeparacaoDadosError(ValueError):
    """Lancada ao detectar tentativa de ingerir gabarito ou log rotulado no RAG."""


def remover_acentos(texto):
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def tokenizar_tecnico(texto):
    """Tokeniza preservando termos tecnicos de rede, flags CLI, portas e IPs."""
    if not texto:
        return []
    limpo = remover_acentos(texto.lower())
    # Preserva tokens como --dport, -br, tcp/80, client1-eth0, 192.168.20.10
    brutos = re.findall(r"(?:--?[a-z0-9][a-z0-9_-]*|[a-z0-9]+(?:[._/-][a-z0-9]+)*)", limpo)
    tokens = []
    for tok in brutos:
        tok_sem_traco = tok.lstrip("-")
        if not tok_sem_traco:
            continue
        if len(tok_sem_traco) == 1 and tok not in ("-s", "-c", "-p", "-t", "-j", "-u", "a"):
            continue
        if tok in STOPWORDS_PT_EN:
            continue
        tokens.append(tok)
        # Adiciona tambem a forma sem prefixo de flag (--dport -> dport) para recall
        if tok.startswith("-") and tok_sem_traco not in STOPWORDS_PT_EN and len(tok_sem_traco) > 1:
            tokens.append(tok_sem_traco)
    return tokens


def verificar_caminho_seguro(caminho):
    """Garante que gabaritos experimentais jamais entrem no indice RAG."""
    caminho_str = str(Path(caminho).resolve()).lower().replace("\\", "/")
    for proibido in PADROES_CAMINHO_PROIBIDOS:
        if proibido in caminho_str:
            raise ViolacaoSeparacaoDadosError(
                f"Violacao de separacao de dados: '{caminho}' contem padrao proibido '{proibido}'."
            )
    if "/logs/" in caminho_str and "evidencias_" in caminho_str:
        raise ViolacaoSeparacaoDadosError(
            f"Violacao de separacao de dados: logs experimentais ('{caminho}') nao devem compor o corpus RAG."
        )


def verificar_conteudo_sem_gabarito(texto, origem=""):
    """Rejeita textos que exponham mapeamentos de casos para causas reais."""
    if re.search(r'"caso_0[0-5]"\s*:\s*\{[^}]*"causa_real"', texto):
        raise ViolacaoSeparacaoDadosError(
            f"Conteudo proibido detectado em '{origem}': estrutura de gabarito causas_reais."
        )
    if re.search(r'"gabarito"\s*:\s*\{|"casos"\s*:\s*\{\s*"caso_00"', texto):
        raise ViolacaoSeparacaoDadosError(
            f"Conteudo proibido detectado em '{origem}': estrutura de gabarito_avaliacao."
        )


def fatiar_markdown(texto, tamanho_max_chars=900, sobreposicao_chars=120):
    """Segmenta documento Markdown por secoes (##) e paragrafos com sobreposicao."""
    linhas = texto.splitlines()
    titulo_doc = ""
    secao_atual = "Introducao"
    buffer_linhas = []
    secoes = []

    for linha in linhas:
        if linha.startswith("# ") and not titulo_doc:
            titulo_doc = linha[2:].strip()
            continue
        if linha.startswith("## "):
            if buffer_linhas:
                conteudo = "\n".join(buffer_linhas).strip()
                if conteudo:
                    secoes.append((secao_atual, conteudo))
            secao_atual = linha[3:].strip()
            buffer_linhas = []
        else:
            buffer_linhas.append(linha)

    if buffer_linhas:
        conteudo = "\n".join(buffer_linhas).strip()
        if conteudo:
            secoes.append((secao_atual, conteudo))

    fatias = []
    for nome_secao, corpo in secoes:
        cabecalho = f"[{titulo_doc} — {nome_secao}]\n" if titulo_doc else f"[{nome_secao}]\n"
        limite_corpo = max(250, tamanho_max_chars - len(cabecalho))

        if len(corpo) <= limite_corpo:
            fatias.append((nome_secao, cabecalho + corpo))
            continue

        paragrafos = [p.strip() for p in re.split(r"\n\s*\n", corpo) if p.strip()]
        bloco_atual = ""

        for paragrafo in paragrafos:
            candidato = f"{bloco_atual}\n\n{paragrafo}".strip() if bloco_atual else paragrafo
            if len(candidato) <= limite_corpo:
                bloco_atual = candidato
            else:
                if bloco_atual:
                    fatias.append((nome_secao, cabecalho + bloco_atual))
                    cauda = bloco_atual[-sobreposicao_chars:] if sobreposicao_chars > 0 else ""
                    # Alinha a sobreposicao ao inicio de palavra
                    if cauda and " " in cauda:
                        cauda = cauda[cauda.find(" ") + 1:]
                    bloco_atual = f"{cauda}\n{paragrafo}".strip() if cauda else paragrafo
                else:
                    # Paragrafo isolado maior que limite_corpo: fatia por janela segura
                    inicio = 0
                    passo = max(150, limite_corpo - sobreposicao_chars)
                    while inicio < len(paragrafo):
                        trecho_p = paragrafo[inicio:inicio + limite_corpo].strip()
                        if trecho_p:
                            fatias.append((nome_secao, cabecalho + trecho_p))
                        inicio += passo
                    bloco_atual = ""

        if bloco_atual:
            fatias.append((nome_secao, cabecalho + bloco_atual))

    return fatias


def carregar_catalogo(caminho_catalogo=ARQUIVO_CATALOGO_PADRAO):
    verificar_caminho_seguro(caminho_catalogo)
    with Path(caminho_catalogo).open("r", encoding="utf-8") as arq:
        dados = json.load(arq)
    if not isinstance(dados, dict) or not isinstance(dados.get("fontes"), list):
        raise ValueError("Catalogo RAG invalido: campo 'fontes' ausente.")
    return dados


def construir_indice(
    pasta_corpus=PASTA_CORPUS_PADRAO,
    caminho_catalogo=ARQUIVO_CATALOGO_PADRAO,
    caminho_saida=ARQUIVO_INDICE_PADRAO,
    tamanho_max_chars=900,
    sobreposicao_chars=120,
):
    """Constroi e persiste o indice RAG versionado com estatisticas BM25/TF-IDF."""
    pasta_corpus = Path(pasta_corpus)
    verificar_caminho_seguro(pasta_corpus)
    catalogo = carregar_catalogo(caminho_catalogo)

    chunks = []
    df_counter = Counter()
    hash_global = hashlib.sha256()

    for fonte in catalogo["fontes"]:
        nome_arquivo = fonte["arquivo"]
        caminho_doc = pasta_corpus / nome_arquivo
        verificar_caminho_seguro(caminho_doc)
        if not caminho_doc.is_file():
            raise FileNotFoundError(f"Documento do corpus RAG ausente: {caminho_doc}")

        texto = caminho_doc.read_text(encoding="utf-8")
        verificar_conteudo_sem_gabarito(texto, origem=str(caminho_doc))
        hash_global.update(texto.encode("utf-8"))

        fatias = fatiar_markdown(
            texto,
            tamanho_max_chars=tamanho_max_chars,
            sobreposicao_chars=sobreposicao_chars,
        )

        for idx, (secao, trecho) in enumerate(fatias):
            chunk_id = f"{fonte['fonte_id']}#{idx:02d}"
            sha_trecho = hashlib.sha256(trecho.encode("utf-8")).hexdigest()[:16]

            # Enriquece representacao de busca com tema, secao e comandos relevantes
            texto_indexavel = " ".join([
                fonte["titulo"],
                secao,
                fonte["tema"].replace("_", " "),
                " ".join(fonte.get("comandos_relevantes", [])),
                trecho,
            ])
            tokens = tokenizar_tecnico(texto_indexavel)
            tf = dict(Counter(tokens))
            for termo in tf:
                df_counter[termo] += 1

            registro = {
                "chunk_id": chunk_id,
                "fonte_id": fonte["fonte_id"],
                "titulo": fonte["titulo"],
                "url": fonte["url"],
                "versao": fonte["versao"],
                "data_acesso": fonte["data_acesso"],
                "tema": fonte["tema"],
                "secao": secao,
                "comandos_relevantes": list(fonte.get("comandos_relevantes", [])),
                "licenca": fonte["licenca"],
                "escopo_de_uso": fonte["escopo_de_uso"],
                "trecho": trecho,
                "sha256": sha_trecho,
                "comprimento_tokens": len(tokens),
                "tf": tf,
            }

            for campo in CAMPOS_METADADOS_OBRIGATORIOS:
                if campo not in registro or registro[campo] is None:
                    raise ValueError(f"Metadado obrigatorio '{campo}' ausente em {chunk_id}")

            chunks.append(registro)

    # Inclui tambem arquivo opcional de manpages locais se houver na pasta_corpus
    extra_man = pasta_corpus / "08_manpages_sistema_local.md"
    if extra_man.is_file():
        verificar_caminho_seguro(extra_man)
        texto_extra = extra_man.read_text(encoding="utf-8")
        verificar_conteudo_sem_gabarito(texto_extra, origem=str(extra_man))
        hash_global.update(texto_extra.encode("utf-8"))
        for idx, (secao, trecho) in enumerate(
            fatiar_markdown(texto_extra, tamanho_max_chars, sobreposicao_chars)
        ):
            chunk_id = f"manpages_locais#{idx:02d}"
            sha_trecho = hashlib.sha256(trecho.encode("utf-8")).hexdigest()[:16]
            tokens = tokenizar_tecnico(f"{secao} {trecho}")
            tf = dict(Counter(tokens))
            for termo in tf:
                df_counter[termo] += 1
            chunks.append({
                "chunk_id": chunk_id,
                "fonte_id": "manpages_locais",
                "titulo": "Sinopses Extraidas das Manpages Locais do Sistema Linux",
                "url": "file:///usr/share/man",
                "versao": "Ubuntu 24.04 Local Manpages",
                "data_acesso": catalogo.get("data_compilacao", "2026-10-25"),
                "tema": "manuais_locais_sistema",
                "secao": secao,
                "comandos_relevantes": ["ip", "iptables", "dnsmasq", "dig", "tc"],
                "licenca": "GPL / MPL / BSD (System Manpages)",
                "escopo_de_uso": "Verificacao de sinopse exata das ferramentas locais.",
                "trecho": trecho,
                "sha256": sha_trecho,
                "comprimento_tokens": len(tokens),
                "tf": tf,
            })

    total_chunks = len(chunks)
    soma_comprimentos = sum(c["comprimento_tokens"] for c in chunks)
    avgdl = round(soma_comprimentos / total_chunks, 4) if total_chunks else 0.0
    versao_indice = hash_global.hexdigest()[:16]

    indice = {
        "versao_indice": versao_indice,
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "parametros_indexacao": {
            "tamanho_max_chars": tamanho_max_chars,
            "sobreposicao_chars": sobreposicao_chars,
            "metodo_recuperacao": "hibrido_bm25_tfidf_metadados",
        },
        "total_fontes": len(catalogo["fontes"]),
        "total_chunks": total_chunks,
        "comprimento_medio_tokens": avgdl,
        "df": dict(sorted(df_counter.items())),
        "chunks": chunks,
    }

    if caminho_saida is not None:
        destino = Path(caminho_saida)
        verificar_caminho_seguro(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(indice, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return indice
