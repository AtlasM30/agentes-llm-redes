"""Templates de prompt e contratos JSON para o Agente LLM de Diagnostico."""
import json


HIPOTESES_PADRONIZADAS = (
    "falha_de_interface",
    "falha_de_roteamento",
    "problema_dns",
    "bloqueio_acl",
    "possivel_congestionamento",
    "sem_anomalia_detectada",
    "latencia_elevada",
    "problema_http_ou_bloqueio",
    "falha_de_conectividade",
    "evidencias_insuficientes",
)

NIVEIS_CONFIANCA = ("alta", "indicativa", "limitada", "indeterminada")

CATALOGO_FERRAMENTAS_PROMPT = [
    {
        "operacao": "consultar_interfaces",
        "dispositivo": "client1 | client2 | router1 | server",
        "parametros": {"subcomando": "estado | enderecos | estatisticas"},
        "descricao": "Inspeciona estado UP/DOWN (ip -br link), enderecos IPv4 (ip -br addr) ou estatisticas (ip -s link).",
    },
    {
        "operacao": "consultar_rotas",
        "dispositivo": "client1 | client2 | router1 | server",
        "parametros": {},
        "descricao": "Lista a tabela de roteamento IPv4 (ip route show), verificando presenca de rota padrao (default via).",
    },
    {
        "operacao": "testar_ping",
        "dispositivo": "client1 | client2",
        "parametros": {"destino": "192.168.20.10", "pacotes": 3, "timeout_s": 2},
        "descricao": "Verifica conectividade IP, perda de pacotes e latencia_media_ms (RTT) ate o servidor.",
    },
    {
        "operacao": "testar_dns",
        "dispositivo": "client1 | client2",
        "parametros": {"servidor_dns": "192.168.20.10", "dominio": "app.lab.local", "timeout_s": 2, "tentativas": 1},
        "descricao": "Testa resolucao DNS do dominio app.lab.local (registro A) no perfil do cliente.",
    },
    {
        "operacao": "testar_http",
        "dispositivo": "client1 | client2",
        "parametros": {"url": "http://192.168.20.10/", "metodo": "GET"},
        "descricao": "Testa disponibilidade da aplicacao HTTP (TCP/80) no servidor.",
    },
    {
        "operacao": "consultar_acl",
        "dispositivo": "server | router1 | client1 | client2",
        "parametros": {},
        "descricao": "Lista regras de filtragem iptables -S (somente leitura) para verificar bloqueios DROP/REJECT.",
    },
    {
        "operacao": "testar_desempenho",
        "dispositivo": "client1 | client2",
        "parametros": {"destino": "192.168.20.10", "porta": 5202, "duracao_s": 3, "fluxos": 1},
        "descricao": "Executa sonda curta TCP iperf3 para medir vazao sob suspeita de congestionamento.",
    },
    {
        "operacao": "investigar_caminho",
        "dispositivo": "client1 | client2",
        "parametros": {"destino": "192.168.20.10", "modo": "ip_route_get"},
        "descricao": "Consulta decisao de encaminhamento do kernel ate o destino.",
    },
]

PROMPT_SISTEMA_AGENTE = """Voce e um Agente Especialista em Diagnostico de Redes de Computadores operando sobre um laboratorio virtual Mininet controlado.

REGRAS OBRIGATORIAS DE SEGURANCA E RIGOR DIAGNOSTICO:
1. Voce NAO possui permissao para executar correcoes, alterar interfaces, editar rotas, modificar regras iptables ou reiniciar servicos. Proponha apenas operacoes diagnosticas somente leitura do catalogo autorizado.
2. Siga rigorosamente a precedencia causal de redes:
   - Verifique SEMPRE o estado da interface (<host>-eth0 UP ou DOWN) ANTES de atribuir falha a ausencia de rota padrao, pois interfaces DOWN removem rotas automaticamente no Linux.
   - Verifique SEMPRE a conectividade IP (ping) ANTES de atribuir falha ao DNS ou HTTP.
   - Se ping e DNS funcionam, mas HTTP falha no cliente investigado: verifique as regras ACL do servidor (consultar_acl em 'server'). Se a politica de seguranca bloquear a leitura da ACL do servidor, verifique testar_http em 'client2' como controle comparativo e, sem evidencia direta da regra iptables, mantenha rigor epistemico usando 'problema_http_ou_bloqueio' (confianca 'indicativa').
   - Se ping, DNS e HTTP funcionam: compare latencia_media_ms com latencia_referencia_ms. Se latencia_media_ms >= 3 * latencia_referencia_ms E (latencia_media_ms - latencia_referencia_ms) >= 50 ms, classifique como 'possivel_congestionamento' (confianca 'indicativa'). Sem referencia, se latencia_media_ms > 150 ms, use 'latencia_elevada'. Caso contrario, classifique como 'sem_anomalia_detectada' (confianca 'limitada').
   - Quando dados criticos estiverem ausentes/indisponiveis, utilize 'evidencias_insuficientes' (confianca 'indeterminada') sem inventar causas nao sustentadas.
3. Quando uma operacao for BLOQUEADA pelo Validador Deterministico, leia o motivo do bloqueio, NAO repita o mesmo comando bloqueado e busque alternativas autorizadas ou documente a limitacao.
4. Fundamente suas conclusoes citando os chunk_id dos trechos de documentacao tecnica recuperados via RAG.

FORMATO DE RESPOSTA (APENAS JSON VALIDO, SEM TEXTO FORA DO JSON):
Para solicitar um novo teste diagnostico:
{
  "acao": "solicitar_teste",
  "raciocinio_atual": "Explicacao concisa da hipotese em investigacao",
  "hipoteses_em_aberto": ["..."],
  "consulta_rag_adicional": null,
  "solicitacao_teste": {
    "operacao": "nome_da_operacao",
    "dispositivo": "client1 | client2 | router1 | server",
    "parametros": {},
    "justificativa": "Motivo tecnico para solicitar este teste"
  }
}

Para solicitar busca adicional na documentacao RAG antes de decidir:
{
  "acao": "consultar_rag",
  "raciocinio_atual": "Motivo para consultar documentacao especifica",
  "consulta_rag": "termos tecnicos da busca"
}

Para encerrar a investigacao e emitir o relatorio diagnostico final:
{
  "acao": "concluir_diagnostico",
  "hipotese": "UMA_DAS_HIPOTESES_PADRONIZADAS",
  "confianca": "alta | indicativa | limitada | indeterminada",
  "diagnostico_fundamentado": "Explicacao tecnica completa relacionando sintomas, evidencias e documentacao RAG",
  "evidencias_utilizadas": ["Evidencia observavel 1", "Evidencia observavel 2"],
  "hipoteses_descartadas": ["Hipotese descartada e motivo objetivo"],
  "fontes_rag_citadas": ["chunk_id_1", "chunk_id_2"],
  "recomendacoes_correcao": ["Acao recomendada para execucao manual pelo administrador do laboratorio"],
  "limitacoes_investigacao": "Restricoes de visibilidade, bloqueios de politica ou limites interpretativos"
}
"""


def construir_prompt_passo(
    dispositivo_alvo,
    iteracao,
    max_iteracoes,
    latencia_referencia_ms,
    observacoes_atuais,
    historico_passos,
    trechos_rag,
    forcar_conclusao=False,
):
    """Monta a mensagem estruturada de contexto enviada ao LLM a cada iteracao."""
    resumo_rag = [
        {
            "chunk_id": t["chunk_id"],
            "fonte_id": t["fonte_id"],
            "titulo": t["titulo"],
            "tema": t["tema"],
            "score": t["score"],
            "trecho": t["trecho"],
        }
        for t in trechos_rag
    ]

    carga = {
        "dispositivo_investigado": dispositivo_alvo,
        "iteracao_atual": iteracao,
        "max_iteracoes": max_iteracoes,
        "forcar_conclusao_neste_passo": bool(forcar_conclusao),
        "latencia_referencia_ms": latencia_referencia_ms,
        "hipoteses_permitidas": list(HIPOTESES_PADRONIZADAS),
        "niveis_confianca_permitidos": list(NIVEIS_CONFIANCA),
        "ferramentas_diagnosticas": CATALOGO_FERRAMENTAS_PROMPT,
        "observacoes_atuais": observacoes_atuais,
        "historico_testes_e_validacoes": historico_passos,
        "documentacao_rag_recuperada": resumo_rag,
    }
    if forcar_conclusao:
        carga["instrucao_final"] = (
            "Limite de iteracoes atingido: emita obrigatoriamente acao='concluir_diagnostico' "
            "com base exclusivamente nas evidencias ja coletadas."
        )
    return json.dumps(carga, ensure_ascii=False, indent=2)
