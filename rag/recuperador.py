"""Recuperador hibrido (Okapi BM25 + TF-IDF Cosseno + Boost de Metadados).

Opera 100% em Python padrao sobre rag/indice_rag.json, garantindo baixa
pegada de memoria (<10 MB) compativel com a VM Ubuntu Server de 1,5 GB RAM
e rastreabilidade deterministica dos trechos recuperados para auditoria.
"""
import json
import math
from collections import Counter
from pathlib import Path

from rag.indexador import (
    ARQUIVO_INDICE_PADRAO,
    construir_indice,
    tokenizar_tecnico,
    verificar_caminho_seguro,
)


class RecuperadorRAG:
    """Motor de busca documental para fundamentacao tecnica do agente LLM."""

    def __init__(self, caminho_indice=ARQUIVO_INDICE_PADRAO, auto_construir=True, k1=1.5, b=0.75):
        self.caminho_indice = Path(caminho_indice)
        verificar_caminho_seguro(self.caminho_indice)
        self.k1 = float(k1)
        self.b = float(b)

        if not self.caminho_indice.is_file():
            if not auto_construir:
                raise FileNotFoundError(f"Indice RAG nao encontrado: {self.caminho_indice}")
            self._indice = construir_indice(caminho_saida=self.caminho_indice)
        else:
            with self.caminho_indice.open("r", encoding="utf-8") as arq:
                self._indice = json.load(arq)

        self.versao_indice = self._indice.get("versao_indice", "desconhecida")
        self.total_chunks = int(self._indice.get("total_chunks", 0))
        self.avgdl = float(self._indice.get("comprimento_medio_tokens", 1.0)) or 1.0
        self.df = self._indice.get("df", {})
        self.chunks = self._indice.get("chunks", [])
        self._idf = self._calcular_idf()
        self._normas_tfidf = [self._calcular_norma_chunk(c) for c in self.chunks]

    def _calcular_idf(self):
        idf = {}
        n = max(1, self.total_chunks)
        for termo, freq_doc in self.df.items():
            # Formula BM25/Robertson-Sparck Jones suavizada (sempre positiva)
            idf[termo] = math.log(1.0 + (n - freq_doc + 0.5) / (freq_doc + 0.5))
        return idf

    def _calcular_norma_chunk(self, chunk):
        soma = 0.0
        for termo, freq in chunk.get("tf", {}).items():
            peso = (1.0 + math.log(freq)) * self._idf.get(termo, 0.0)
            soma += peso * peso
        return math.sqrt(soma) if soma > 0 else 1.0

    def recuperar(self, consulta, top_k=4, score_minimo=0.05, filtro_tema=None):
        """Recupera os top_k trechos mais pertinentes com pontuacao e metadados."""
        tokens_q = tokenizar_tecnico(consulta)
        if not tokens_q or not self.chunks:
            return []

        tf_q = Counter(tokens_q)
        pesos_q = {}
        soma_q = 0.0
        for termo, freq in tf_q.items():
            idf_t = self._idf.get(termo, 0.0)
            if idf_t > 0:
                w = (1.0 + math.log(freq)) * idf_t
                pesos_q[termo] = w
                soma_q += w * w
        norma_q = math.sqrt(soma_q) if soma_q > 0 else 1.0
        consulta_lower = consulta.lower()

        avaliados = []
        for idx, chunk in enumerate(self.chunks):
            if filtro_tema and chunk.get("tema") != filtro_tema:
                continue

            tf_doc = chunk.get("tf", {})
            dl = max(1, chunk.get("comprimento_tokens", 1))
            bm25 = 0.0
            produto_interno = 0.0

            for termo, freq_q in tf_q.items():
                freq_d = tf_doc.get(termo, 0)
                if freq_d <= 0:
                    continue
                idf_t = self._idf.get(termo, 0.0)
                numerador = freq_d * (self.k1 + 1.0)
                denominador = freq_d + self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl))
                bm25 += idf_t * (numerador / denominador) * (1.0 + 0.1 * (freq_q - 1))

                peso_d = (1.0 + math.log(freq_d)) * idf_t
                produto_interno += pesos_q.get(termo, 0.0) * peso_d

            if bm25 <= 0.0 and produto_interno <= 0.0:
                continue

            cosseno = produto_interno / (norma_q * self._normas_tfidf[idx])

            # Boost leve quando comandos relevantes ou tema aparecem na consulta
            boost = 0.0
            for cmd in chunk.get("comandos_relevantes", []):
                cmd_base = cmd.split()[0].lower()
                if cmd_base and cmd_base in consulta_lower:
                    boost += 0.25
                    break
            tema_palavras = chunk.get("tema", "").split("_")
            if any(p in tokens_q for p in tema_palavras if len(p) > 2):
                boost += 0.20

            # Score combinado estavel (BM25 normalizado + cosseno TF-IDF + boost)
            score_final = round((bm25 * 0.65) + (cosseno * 2.0) + boost, 4)
            if score_final < score_minimo:
                continue

            avaliados.append({
                "chunk_id": chunk["chunk_id"],
                "fonte_id": chunk["fonte_id"],
                "titulo": chunk["titulo"],
                "secao": chunk["secao"],
                "tema": chunk["tema"],
                "url": chunk["url"],
                "versao": chunk["versao"],
                "licenca": chunk["licenca"],
                "comandos_relevantes": chunk["comandos_relevantes"],
                "escopo_de_uso": chunk["escopo_de_uso"],
                "score": score_final,
                "trecho": chunk["trecho"],
            })

        avaliados.sort(key=lambda item: (-item["score"], item["chunk_id"]))
        return avaliados[: max(1, int(top_k))]

    @staticmethod
    def construir_consulta_por_evidencias(observacoes, dispositivo="client1"):
        """Gera consulta inicial orientada pelos sintomas observados nas evidencias."""
        termos = ["diagnostico rede mininet"]
        disp = observacoes.get(dispositivo, observacoes) if isinstance(observacoes, dict) else {}

        interfaces = disp.get("interfaces", {})
        estado_txt = interfaces.get("estado", {}).get("saida", "") if isinstance(interfaces, dict) else ""
        if "DOWN" in estado_txt:
            termos.append("ip -br link interface DOWN precedencia rota iproute2")

        rotas = disp.get("rotas", {})
        saida_rotas = rotas.get("saida", "") if isinstance(rotas, dict) else ""
        if isinstance(rotas, dict) and rotas.get("sucesso") is True and "default " not in saida_rotas:
            termos.append("ip route show rota padrao default via ausente")

        ping = disp.get("ping", {})
        if isinstance(ping, dict):
            if ping.get("sucesso") is False:
                termos.append("falha ping conectividade ip interface link route")
            latencia = ping.get("latencia_media_ms")
            if isinstance(latencia, (int, float)) and latencia > 80:
                termos.append("latencia alta rtt bufferbloat congestionamento tc qdisc iperf3")

        dns = disp.get("dns", {})
        if isinstance(dns, dict) and dns.get("resolucao_correta") is False:
            termos.append("dig resolucao dns falhou dnsmasq servidor dns incorreto")

        http = disp.get("http", {})
        if isinstance(http, dict) and http.get("servico_disponivel") is False:
            termos.append("http indisponivel curl iptables -S INPUT tcp dport 80 DROP REJECT acl")

        if len(termos) == 1:
            termos.append("operacao normal conectividade ping dig http latencia referencia")

        return " ".join(termos)
