# Relatório Técnico — Etapa 7: Método Proposto (Agente LLM + RAG + Validação Determinística)

**Projeto:** Agentes Baseados em Modelos de Linguagem para Diagnóstico de Redes com Validação Determinística de Segurança  
**Data de referência:** 25 de outubro de 2026  
**Situação:** Implementação completa da arquitetura proposta, indexação RAG, validador determinístico de segurança, mecanismos de auditoria/explicabilidade e suíte de testes automatizados.

---

## 1. Visão Geral da Solução Implementada

Em continuidade à linha de base determinística estabelecida na Etapa 6 (`diagnostico/regras.py`), a Etapa 7 implementa a arquitetura inteligente completa prevista no escopo do Projeto 8:

```text
Evidências Sanitizadas (Mininet) ──► Recuperador Híbrido RAG (BM25 + TF-IDF)
                                               │
                                               ▼
                                 Agente LLM Multi-Etapa (ReAct)
                                               │
                                 Proposta de Teste Estruturada
                                               │
                                               ▼
                           Validador Determinístico de Segurança (7 Portões)
                              ├── [BLOQUEADO] ─► Registra motivo e devolve ao Agente (Resiliência)
                              └── [AUTORIZADO] ─► Executor Controlado (shell=False) ─► Nova Evidência
                                               │
                                               ▼
                     Diagnóstico Fundamentado + Recomendações + Auditoria JSON
```

O agente permanece **estritamente analítico e investigativo**: jamais executa reparos automáticos nem comandos arbitrários de shell sobre o sistema hospedeiro ou sobre os hosts virtuais.

---

## 2. Organização dos Novos Módulos e Scripts

| Caminho | Responsabilidade |
|---|---|
| `rag/catalogo_fontes.json` | Manifesto com metadados completos, versões e licenças das 7 fontes técnicas de `FONTES_RAG.md`. |
| `rag/corpus/*.md` | Corpus técnico curado (`mininet`, `iperf3`, `dnsmasq`, `dig`, `iproute2`, `iptables`, `tc`). |
| `rag/coletor_manpages.py` | Extrator opcional de sinopses das manpages reais instaladas no Ubuntu. |
| `rag/indexador.py` | Fatiamento semântico com sobreposição, trava anti-vazamento de gabaritos e índice `rag/indice_rag.json`. |
| `rag/recuperador.py` | Recuperador híbrido (Okapi BM25 + Cosseno TF-IDF + Boost de metadados/comandos) sem dependências pesadas. |
| `seguranca/politicas.py` | Definição declarativa de escopo (IPs, sub-redes, domínios, origens) e das políticas `padrao` e `restritiva`. |
| `seguranca/validador.py` | `ValidadorDeterministico` com 7 portões de verificação e geração de `comando_canonico` (`shell=False`). |
| `seguranca/catalogo_solicitacoes.py` | Conjunto de 25 solicitações rotuladas para aferir bloqueio correto, autorização indevida e bloqueio indevido. |
| `agente/provedores_llm.py` | Clientes unificados para **Google Gemini**, **OpenAI/Groq**, **Ollama** e **Modo Simulado** determinístico. |
| `agente/prompts.py` | Prompt de sistema com precedência causal, rigor epistêmico e contrato JSON estruturado. |
| `agente/executor.py` | Sanitização anti-vazamento e executores condicionados (`ExecutorEvidenciasOffline` e `ExecutorMininetAtivo`). |
| `agente/auditoria.py` | Registro de hiperparâmetros (`ConfiguracaoAgente`), rastreabilidade passo a passo, tokens, tempo e resiliência. |
| `agente/diagnostico_agente.py` | Orquestrador `AgenteDiagnosticoRedes` integrando RAG, LLM, Validador, Executor e Auditoria. |
| `construir_indice_rag.py` | Script reproduzível para indexar e verificar a base RAG. |
| `executar_agente.py` | Script de linha de comando para executar diagnósticos com o Agente LLM e gravar auditorias. |
| `avaliar_metodo_proposto.py` | Avaliador das duas frentes experimentais (Segurança do Validador + Qualidade Diagnóstica vs. Baseline). |
| `exportar_pacote_revisao.py` | Gera pacote `.zip` limpo do código-fonte (excluindo `.env`, `.git`, `logs/` e gabaritos) para auditoria externa. |
| `tests/test_rag.py`, `test_validador.py`, `test_agente_auditoria.py`, `test_adversarial_seguranca_rag.py` | 33 testes automatizados (10 da Etapa 6 + 23 da Etapa 7 e suíte adversarial de segurança/RAG). |

---

## 3. Detalhamento Técnico dos Componentes

### 3.1 Base Documental e Recuperação RAG (`rag/`)
- Todas as sete referências de `documentacao/FONTES_RAG.md` foram documentadas, segmentadas por seções lógicas (`tamanho_max_chars=900`, `sobreposicao_chars=120`) e indexadas com metadados obrigatórios (`chunk_id`, `fonte_id`, `titulo`, `url`, `versao`, `data_acesso`, `tema`, `secao`, `comandos_relevantes`, `licenca`, `escopo_de_uso`, `sha256`).
- **Prevenção de vazamento (*Data Leakage*)**: `verificar_caminho_seguro` e `verificar_conteudo_sem_gabarito` lançam `ViolacaoSeparacaoDadosError` caso qualquer arquivo de `avaliacao/`, `dados/gabaritos/`, `resultados_avaliacao/` ou `logs/` tente ser ingerido no índice.
- **Compatibilidade com a VM (1,5 GB RAM)**: o motor híbrido BM25 + TF-IDF opera integralmente sobre a biblioteca padrão do Python, dispensando PyTorch/FAISS na máquina virtual do laboratório.

### 3.2 Validador Determinístico de Segurança (`seguranca/`)
Cada solicitação proposta pelo modelo passa por **sete portões determinísticos**, independentemente da justificativa textual do LLM (`justificativa_ignorada_na_decisao = True`):
1. **Sintaxe e Injeção de Shell**: rejeita metacaracteres (`;`, `&&`, `||`, `|`, `` ` ``, `$(`, `>`, `<`).
2. **Escopo Funcional**: bloqueia binários destrutivos (`rm`, `killall`, `reboot`, `sudo`, `sh`) e subcomandos de alteração (`ip link set`, `ip route add/del/replace`, `iptables -A/-I/-D/-F`, `tc qdisc add/del`).
3. **Permissões de Origem**: valida se o dispositivo existe e possui permissão para a operação solicitada.
4. **Escopo de Destino**: restringe alvos às sub-redes `192.168.10.0/24` e `192.168.20.0/24`, domínio `app.lab.local` e portas autorizadas (`53`, `80`, `5201`, `5202`).
5. **Parâmetros e Tipos**: valida flags, métodos HTTP (`GET`/`HEAD`) e tipos DNS (`A`/`AAAA`).
6. **Limites de Duração**: controla `timeout_s`, `max_time_s` e duração máxima de sonda `iperf3` ($\le 5\text{ s}$).
7. **Limites de Volume de Tráfego**: bloqueia `ping -f` (flood), excesso de pacotes ICMP, múltiplos fluxos `iperf3 -P > 1`, UDP flood (`-u`) e transferências de zona DNS (`AXFR`/`ANY`).

Conforme planejado na Seção 4.4 da monografia, duas políticas estão disponíveis:
- `padrao`: autoriza todas as consultas somente leitura e sondas controladas não destrutivas.
- `restritiva`: bloqueia adicionalmente `consultar_acl` em `server`/`router1` e `testar_desempenho` (`iperf3`), permitindo mensurar na Etapa 8 o impacto das restrições na acurácia e a **resiliência após bloqueio**.

### 3.3 Ciclo do Agente, Hiperparâmetros, Aderência RAG e Auditoria (`agente/`)
- Hiperparâmetros registrados por sessão em `ConfiguracaoAgente`: `provedor_llm`, `modelo_llm`, `eh_llm_real`, `temperatura`, `max_tokens_resposta`, `max_iteracoes`, `top_k_rag`, `score_minimo_rag`, `politica_seguranca`, `modo_evidencias` e `versao_indice_rag` (hash SHA-256 do corpus).
- **Distinção explícita Simulado vs. LLM Real**: o modo `--provedor simulado` (`ClienteLLMSimulado`) executa uma máquina de estados determinística alinhada à precedência causal da Etapa 6 exclusivamente para verificação de integração do pipeline sem chaves de API, marcando explicitamente `modo_inferencia = "simulado_deterministico"` e `origem_contagem_tokens = "estimativa_caracteres_simulada"`. A avaliação experimental da capacidade cognitiva de um LLM exige execução com provedor real (`gemini`, `openai`/`groq` ou `ollama`).
- **Robusteza para LLMs reais**: o orquestrador inclui compactação de contexto para economia de tokens (~50% menor), reparo automático e 1 retentativa corretiva para JSON malformado (`erros_formato_recuperados`), backoff exponencial para HTTP 429/503, guarda contra repetição infinita do mesmo comando (`tentativas_duplicadas_evitadas`), defesa contra *prompt injection* em documentos RAG (`verificar_documento_sem_injecao_prompt`) e aferição automática de **aderência temática das citações RAG** (`avaliar_aderencia_citacoes`).
- Cada execução gera um objeto `RegistroAuditoria` contendo todas as consultas RAG, hipóteses intermediárias, propostas de teste, decisões do validador, aderência das citações, consumo de tokens, tempo total e recomendações de correção destinadas exclusivamente ao administrador humano.

---

## 4. Procedimento de Reprodução

```bash
cd ~/agentes-llm-redes

# 1. Construir e verificar o índice RAG
python3 construir_indice_rag.py

# 2. Executar toda a suíte de testes unitários (Etapa 6 + Etapa 7)
python3 -m unittest discover -s tests -v

# 3. Avaliar o Validador Determinístico (Frente de Segurança)
python3 avaliar_metodo_proposto.py --apenas-seguranca

# 4. Executar o Agente LLM sobre os logs coletados na VM (ou demonstração offline)
python3 executar_agente.py --provedor simulado --politica padrao
python3 executar_agente.py --demonstracao-sintetica --politica restritiva

# 5. Avaliar Agente vs. Gabarito e Baseline nas duas políticas (na VM com logs/ e gabarito)
python3 avaliar_metodo_proposto.py --provedor simulado --comparar-politicas

# 6. Executar com LLM real via API (após configurar .env a partir de .env.example)
cp .env.example .env
# Editar GEMINI_API_KEY ou OPENAI_API_KEY / OLLAMA_BASE_URL em .env
python3 executar_agente.py --provedor gemini --modelo gemini-2.5-flash --politica padrao
```
