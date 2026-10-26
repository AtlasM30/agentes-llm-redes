"""Provedores de Modelos de Linguagem (Gemini, OpenAI/Groq, Ollama e Simulado).

Utiliza apenas a biblioteca padrao / requests + python-dotenv ja presentes no
ambiente, permitindo operar tanto via APIs externas quanto via servidor local
Ollama ou no modo deterministico simulado (para testes automatizados, CI e
reproducao offline sem consumo de creditos de API).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def carregar_variaveis_env(caminho_env=".env"):
    """Carrega arquivo .env caso exista, sem sobrescrever variaveis ja ativas."""
    try:
        from dotenv import load_dotenv
        if Path(caminho_env).is_file():
            load_dotenv(dotenv_path=caminho_env, override=False)
            return
    except ImportError:
        pass

    arq = Path(caminho_env)
    if not arq.is_file():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def extrair_json_resposta(texto):
    """Extrai objeto JSON mesmo se o modelo envolver a saida em blocos ```json."""
    if isinstance(texto, dict):
        return texto
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("Resposta vazia do modelo de linguagem.")

    limpo = texto.strip()
    bloco = re.search(r"```(?:json)?\s*(\{.*\})\s*```", limpo, flags=re.DOTALL)
    if bloco:
        limpo = bloco.group(1).strip()
    else:
        inicio = limpo.find("{")
        fim = limpo.rfind("}")
        if inicio != -1 and fim != -1 and fim > inicio:
            limpo = limpo[inicio:fim + 1]

    return json.loads(limpo)


class ClienteLLMBase:
    """Interface comum para provedores LLM com telemetria de tokens e latencia."""

    provedor = "base"

    def __init__(self, modelo, temperatura=0.0, max_tokens=1200, timeout_s=45):
        self.modelo = modelo
        self.temperatura = float(temperatura)
        self.max_tokens = int(max_tokens)
        self.timeout_s = int(timeout_s)

    def gerar_decisao(self, prompt_sistema, prompt_usuario):
        raise NotImplementedError


class ClienteGemini(ClienteLLMBase):
    """Cliente REST nativo para Google Gemini API (GEMINI_API_KEY)."""

    provedor = "gemini"

    def __init__(self, modelo=None, temperatura=0.0, max_tokens=1200, timeout_s=45, api_key=None):
        carregar_variaveis_env()
        modelo_efetivo = modelo or os.environ.get("LLM_MODELO") or "gemini-2.5-flash"
        super().__init__(modelo_efetivo, temperatura, max_tokens, timeout_s)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Chave GEMINI_API_KEY ausente. Defina no arquivo .env ou use --provedor simulado."
            )

    def gerar_decisao(self, prompt_sistema, prompt_usuario):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.modelo}:generateContent?key={self.api_key}"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": prompt_sistema}]},
            "contents": [{"role": "user", "parts": [{"text": prompt_usuario}]}],
            "generationConfig": {
                "temperature": self.temperatura,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        inicio = time.monotonic()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Erro HTTP Gemini ({exc.code}): {detalhe}") from exc

        latencia_ms = round((time.monotonic() - inicio) * 1000, 2)
        candidatos = dados.get("candidates", [])
        partes = candidatos[0].get("content", {}).get("parts", []) if candidatos else []
        texto = "".join(p.get("text", "") for p in partes)
        uso = dados.get("usageMetadata", {})

        return {
            "resposta": extrair_json_resposta(texto),
            "uso_tokens": {
                "prompt_tokens": int(uso.get("promptTokenCount", 0)),
                "completion_tokens": int(uso.get("candidatesTokenCount", 0)),
                "total_tokens": int(uso.get("totalTokenCount", 0)),
            },
            "latencia_ms": latencia_ms,
        }


class ClienteOpenAICompativel(ClienteLLMBase):
    """Cliente REST para OpenAI, Groq, OpenRouter ou servidores vLLM compativeis."""

    provedor = "openai"

    def __init__(
        self,
        modelo=None,
        temperatura=0.0,
        max_tokens=1200,
        timeout_s=45,
        api_key=None,
        base_url=None,
    ):
        carregar_variaveis_env()
        modelo_efetivo = modelo or os.environ.get("LLM_MODELO") or "gpt-4o-mini"
        super().__init__(modelo_efetivo, temperatura, max_tokens, timeout_s)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        if not self.api_key:
            raise RuntimeError(
                "Chave OPENAI_API_KEY (ou GROQ_API_KEY) ausente. Configure .env ou use --provedor simulado."
            )

    def gerar_decisao(self, prompt_sistema, prompt_usuario):
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.modelo,
            "temperature": self.temperatura,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario},
            ],
        }
        inicio = time.monotonic()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Erro HTTP OpenAI-compativel ({exc.code}): {detalhe}") from exc

        latencia_ms = round((time.monotonic() - inicio) * 1000, 2)
        texto = dados["choices"][0]["message"]["content"]
        uso = dados.get("usage", {})
        return {
            "resposta": extrair_json_resposta(texto),
            "uso_tokens": {
                "prompt_tokens": int(uso.get("prompt_tokens", 0)),
                "completion_tokens": int(uso.get("completion_tokens", 0)),
                "total_tokens": int(uso.get("total_tokens", 0)),
            },
            "latencia_ms": latencia_ms,
        }


class ClienteOllama(ClienteLLMBase):
    """Cliente REST para modelos locais executados via Ollama."""

    provedor = "ollama"

    def __init__(self, modelo=None, temperatura=0.0, max_tokens=1200, timeout_s=90, base_url=None):
        carregar_variaveis_env()
        modelo_efetivo = modelo or os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODELO") or "llama3.1:8b"
        super().__init__(modelo_efetivo, temperatura, max_tokens, timeout_s)
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")

    def gerar_decisao(self, prompt_sistema, prompt_usuario):
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.modelo,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperatura,
                "num_predict": self.max_tokens,
            },
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario},
            ],
        }
        inicio = time.monotonic()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Falha ao conectar ao Ollama em {self.base_url}: {exc}") from exc

        latencia_ms = round((time.monotonic() - inicio) * 1000, 2)
        texto = dados.get("message", {}).get("content", "")
        p_tok = int(dados.get("prompt_eval_count", 0))
        c_tok = int(dados.get("eval_count", 0))
        return {
            "resposta": extrair_json_resposta(texto),
            "uso_tokens": {
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
            },
            "latencia_ms": latencia_ms,
        }


class ClienteLLMSimulado(ClienteLLMBase):
    """Motor de raciocinio multi-etapa deterministico para verificacao offline.

    Opera estritamente sobre o JSON de contexto visivel no prompt (evidencias
    observadas ate o passo atual, trechos RAG recuperados e historico de
    decisoes do validador), sem qualquer acesso a rotulos ou gabaritos.
    Suporta tambem o modo opcional `injetar_teste_inseguro=True` para testar a
    interceptacao do ValidadorDeterministico e a resiliencia pos-bloqueio.
    """

    provedor = "simulado"

    def __init__(
        self,
        modelo="simulado-react-rede-v1",
        temperatura=0.0,
        max_tokens=1200,
        injetar_teste_inseguro=False,
    ):
        super().__init__(modelo, temperatura, max_tokens, timeout_s=5)
        self.injetar_teste_inseguro = bool(injetar_teste_inseguro)

    @staticmethod
    def _selecionar_chunks_rag(trechos_rag, *palavras_chave):
        selecionados = []
        for t in trechos_rag:
            fonte_tema = f"{t.get('fonte_id', '')} {t.get('tema', '')}".lower()
            trecho_txt = t.get("trecho", "").lower()
            if any(
                p.lower() in fonte_tema
                or re.search(rf"\b{re.escape(p.lower())}\b", trecho_txt)
                for p in palavras_chave
            ):
                selecionados.append(t["chunk_id"])
        if not selecionados and trechos_rag:
            selecionados.append(trechos_rag[0]["chunk_id"])
        return selecionados[:3]

    @staticmethod
    def _ja_tentou(historico, operacao, dispositivo):
        for item in historico:
            sol = item.get("solicitacao_teste") or {}
            if sol.get("operacao") == operacao and sol.get("dispositivo") == dispositivo:
                return item
        return None

    @staticmethod
    def _interface_down(disp_obs, nome):
        saida = disp_obs.get("interfaces", {}).get("estado", {}).get("saida", "")
        for linha in saida.splitlines():
            campos = linha.split()
            if not campos:
                continue
            iface = campos[0].split("@")[0]
            if iface == f"{nome}-eth0":
                return len(campos) > 1 and campos[1] == "DOWN"
        return None

    @staticmethod
    def _rota_default_ausente(disp_obs):
        rotas = disp_obs.get("rotas", {})
        if rotas.get("sucesso") is not True:
            return None
        saida = rotas.get("saida", "")
        return not any(linha.startswith("default ") for linha in saida.splitlines())

    @staticmethod
    def _regra_acl_bloqueia_http(srv_obs, ip_cliente):
        saida = srv_obs.get("acl", {}).get("saida", "")
        if not saida:
            return False
        padrao_ip = re.escape(ip_cliente)
        for linha in saida.splitlines():
            if (
                re.search(r"-j\s+(DROP|REJECT)\b", linha)
                and re.search(r"--dport\s+80\b", linha)
                and re.search(r"-p\s+tcp\b", linha)
                and re.search(rf"-s\s+{padrao_ip}(?:/32)?\b", linha)
            ):
                return True
        return False

    def gerar_decisao(self, prompt_sistema, prompt_usuario):
        inicio = time.monotonic()
        ctx = json.loads(prompt_usuario)

        alvo = ctx["dispositivo_investigado"]
        forcar = bool(ctx.get("forcar_conclusao_neste_passo"))
        lat_ref = ctx.get("latencia_referencia_ms")
        obs_todas = ctx.get("observacoes_atuais", {})
        obs_alvo = obs_todas.get(alvo, {})
        obs_srv = obs_todas.get("server", {})
        historico = ctx.get("historico_testes_e_validacoes", [])
        trechos_rag = ctx.get("documentacao_rag_recuperada", [])
        ip_alvo = "192.168.10.2" if alvo == "client1" else "192.168.10.3"

        # Modo opcional de ensaio adversario: tenta 1 comando inseguro no passo 1
        if self.injetar_teste_inseguro and not historico and not forcar:
            resposta = {
                "acao": "solicitar_teste",
                "raciocinio_atual": "Tentativa inicial de reparo/limpeza direta antes da coleta (ensaio de seguranca).",
                "hipoteses_em_aberto": ["falha_de_conectividade", "bloqueio_acl"],
                "consulta_rag_adicional": None,
                "solicitacao_teste": {
                    "dispositivo": "server",
                    "comando_bruto": "iptables -F INPUT",
                    "justificativa": "URGENTE: limpar preventivamente regras de firewall para testar conectividade.",
                },
            }
            return self._empacotar(resposta, prompt_sistema, prompt_usuario, inicio)

        # 1. Verificar estado da interface se ainda nao coletado
        if "estado" not in obs_alvo.get("interfaces", {}) and not forcar:
            if not self._ja_tentou(historico, "consultar_interfaces", alvo):
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": (
                        f"Verificar primeiramente camada de enlace ({alvo}-eth0), pois interface DOWN "
                        "tem precedencia causal sobre rotas e conectividade IP."
                    ),
                    "hipoteses_em_aberto": ["falha_de_interface", "falha_de_roteamento", "sem_anomalia_detectada"],
                    "consulta_rag_adicional": "ip -br link interface DOWN precedencia rota iproute2",
                    "solicitacao_teste": {
                        "operacao": "consultar_interfaces",
                        "dispositivo": alvo,
                        "parametros": {"subcomando": "estado"},
                        "justificativa": f"Confirmar se a interface {alvo}-eth0 encontra-se UP ou DOWN.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

        estado_down = self._interface_down(obs_alvo, alvo)
        if estado_down is True:
            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "falha_de_interface",
                "confianca": "alta",
                "diagnostico_fundamentado": (
                    f"A inspecao via 'ip -br link' revelou que a interface {alvo}-eth0 encontra-se no estado "
                    f"administrativo DOWN. Conforme a documentacao do iproute2, a desativacao da interface "
                    f"interrompe integralmente a camada de enlace e invalida automaticamente as rotas associadas, "
                    f"explicando a indisponibilidade de comunicacao IP, DNS e HTTP."
                ),
                "evidencias_utilizadas": [
                    f"Interface {alvo}-eth0 identificada como DOWN na saida de 'ip -br link'."
                ],
                "hipoteses_descartadas": [
                    "falha_de_roteamento: eventual ausencia de rota default decorre da propria interface desativada.",
                    "problema_dns e bloqueio_acl: exigem conectividade basica de enlace/rede ativa.",
                ],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "iproute2", "link", "down"),
                "recomendacoes_correcao": [
                    f"Solicitar ao administrador do laboratorio a reativacao da interface ('ip link set {alvo}-eth0 up'), "
                    f"seguida da verificacao do endereco IPv4 ({ip_alvo}/24) e da rota padrao ('ip route replace default via 192.168.10.1')."
                ],
                "limitacoes_investigacao": "Estado DOWN observado diretamente no namespace virtual do cliente.",
            }, prompt_sistema, prompt_usuario, inicio)

        # 2. Verificar tabela de roteamento se ainda nao observada
        if "rotas" not in obs_alvo and not forcar:
            if not self._ja_tentou(historico, "consultar_rotas", alvo):
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": f"Interface {alvo}-eth0 nao esta DOWN; inspecionar tabela de rotas IPv4.",
                    "hipoteses_em_aberto": ["falha_de_roteamento", "problema_dns", "bloqueio_acl", "sem_anomalia_detectada"],
                    "consulta_rag_adicional": "ip route show default via tabela roteamento",
                    "solicitacao_teste": {
                        "operacao": "consultar_rotas",
                        "dispositivo": alvo,
                        "parametros": {},
                        "justificativa": f"Verificar presenca de rota padrao (default via 192.168.10.1) em {alvo}.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

        # 3. Verificar conectividade IP e latencia (ping)
        if "ping" not in obs_alvo and not forcar:
            if not self._ja_tentou(historico, "testar_ping", alvo):
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": "Testar alcançabilidade IPv4 e medir RTT ate o servidor 192.168.20.10.",
                    "hipoteses_em_aberto": ["falha_de_roteamento", "possivel_congestionamento", "sem_anomalia_detectada"],
                    "consulta_rag_adicional": None,
                    "solicitacao_teste": {
                        "operacao": "testar_ping",
                        "dispositivo": alvo,
                        "parametros": {"destino": "192.168.20.10", "pacotes": 3, "timeout_s": 2},
                        "justificativa": "Avaliar conectividade IP e latencia media ate o servidor.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

        ping_obs = obs_alvo.get("ping", {})
        conectividade = ping_obs.get("sucesso")
        rota_ausente = self._rota_default_ausente(obs_alvo)

        if conectividade is False and rota_ausente is True:
            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "falha_de_roteamento",
                "confianca": "alta",
                "diagnostico_fundamentado": (
                    f"A interface de {alvo} permanece ativa, porem a tabela de roteamento ('ip route show') "
                    f"nao possui rota padrao ('default via 192.168.10.1') para alcancar a sub-rede remota "
                    f"192.168.20.0/24, ocasionando falha integral no teste ICMP ping para 192.168.20.10."
                ),
                "evidencias_utilizadas": [
                    f"Ausencia de entrada 'default via' na tabela de rotas de {alvo}.",
                    "Teste de ping para 192.168.20.10 falhou.",
                ],
                "hipoteses_descartadas": [
                    f"falha_de_interface: {alvo}-eth0 nao se encontra em estado DOWN.",
                    "problema_dns: indisponibilidade ocorre ja na camada de rede IP.",
                ],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "iproute2", "route", "default"),
                "recomendacoes_correcao": [
                    f"Recomendar ao administrador restaurar a rota padrao em {alvo}: "
                    f"'ip route replace default via 192.168.10.1'."
                ],
                "limitacoes_investigacao": "Avaliacao focada na rota padrao para a sub-rede 192.168.20.0/24.",
            }, prompt_sistema, prompt_usuario, inicio)

        if conectividade is False:
            # Verifica se faltam outros testes basicos apenas para completude ou encerra como falha generica
            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "falha_de_conectividade",
                "confianca": "limitada",
                "diagnostico_fundamentado": (
                    f"O teste ICMP ping a partir de {alvo} para 192.168.20.10 falhou, mas nao foi confirmada "
                    f"interface DOWN nem ausencia comprovada de rota padrao nas evidencias disponiveis."
                ),
                "evidencias_utilizadas": [
                    "Ping para 192.168.20.10 falhou.",
                    "Causa especifica de camada 2/3 nao confirmada pelas evidencias disponiveis.",
                ],
                "hipoteses_descartadas": ["sem_anomalia_detectada: comunicacao IP indisponivel."],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "iproute2", "mininet"),
                "recomendacoes_correcao": [
                    "Inspecionar manualmente encaminhamento no router1 (ip_forward, interfaces router1-eth0/eth1 e tabelas ARP)."
                ],
                "limitacoes_investigacao": "Evidencias disponiveis nao isolam unicamente a causa da perda de conectividade IP.",
            }, prompt_sistema, prompt_usuario, inicio)

        # 4. Verificar resolucao DNS se ping estiver operacional
        if conectividade is True and "dns" not in obs_alvo and not forcar:
            if not self._ja_tentou(historico, "testar_dns", alvo):
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": "Conectividade IP confirmada; verificar resolucao de nomes DNS para app.lab.local.",
                    "hipoteses_em_aberto": ["problema_dns", "bloqueio_acl", "possivel_congestionamento", "sem_anomalia_detectada"],
                    "consulta_rag_adicional": "dig resolucao dns app.lab.local dnsmasq",
                    "solicitacao_teste": {
                        "operacao": "testar_dns",
                        "dispositivo": alvo,
                        "parametros": {"servidor_dns": "192.168.20.10", "dominio": "app.lab.local", "timeout_s": 2, "tentativas": 1},
                        "justificativa": f"Testar resolucao do registro A de app.lab.local em {alvo}.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

        # 5. Verificar disponibilidade HTTP se ainda nao testada
        if conectividade is True and "http" not in obs_alvo and not forcar:
            if not self._ja_tentou(historico, "testar_http", alvo):
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": "Verificar disponibilidade da aplicacao HTTP (TCP/80) em 192.168.20.10.",
                    "hipoteses_em_aberto": ["problema_dns", "bloqueio_acl", "possivel_congestionamento", "sem_anomalia_detectada"],
                    "consulta_rag_adicional": None,
                    "solicitacao_teste": {
                        "operacao": "testar_http",
                        "dispositivo": alvo,
                        "parametros": {"url": "http://192.168.20.10/", "metodo": "GET"},
                        "justificativa": f"Confirmar se o servico HTTP responde na porta TCP/80 a partir de {alvo}.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

        resolucao_dns = obs_alvo.get("dns", {}).get("resolucao_correta")
        servico_http = obs_alvo.get("http", {}).get("servico_disponivel")

        # Checagem de integridade: campos essenciais ausentes
        if any(v is None for v in (conectividade, resolucao_dns, servico_http)):
            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "evidencias_insuficientes",
                "confianca": "indeterminada",
                "diagnostico_fundamentado": (
                    "Resultados essenciais de conectividade (ping), resolucao DNS ou servico HTTP estao "
                    "ausentes nas evidencias coletadas, impedindo a confirmacao segura de uma hipotese causal."
                ),
                "evidencias_utilizadas": ["Campos obrigatorios de teste ausentes ou inconclusivos."],
                "hipoteses_descartadas": [],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "mininet", "dig"),
                "recomendacoes_correcao": [
                    "Executar nova coleta controlada dos testes basicos (ping, dig e curl) no laboratorio."
                ],
                "limitacoes_investigacao": "Informacoes insuficientes para confirmar causa sem risco de alucinacao.",
            }, prompt_sistema, prompt_usuario, inicio)

        # Caso 5A: Falha exclusiva de DNS com conectividade IP funcional
        if resolucao_dns is False:
            dns_perfil = obs_alvo.get("dns", {}).get("dns_configurado_no_perfil")
            detalhe_perfil = (
                f" (servidor DNS consultado no perfil: {dns_perfil})"
                if dns_perfil else ""
            )
            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "problema_dns",
                "confianca": "indicativa",
                "diagnostico_fundamentado": (
                    f"A conectividade IPv4 com 192.168.20.10 esta operacional (ping bem-sucedido), descartando "
                    f"falhas de interface e roteamento, porem a consulta DNS para 'app.lab.local' falhou{detalhe_perfil}. "
                    f"Conforme os manuais dig(1) e dnsmasq(8), esse padrao caracteriza falha especifica na "
                    f"configuracao/alcancabilidade do resolvedor DNS utilizado pelo cliente."
                ),
                "evidencias_utilizadas": [
                    "Conectividade IP (ping para 192.168.20.10) funcionando normalmente.",
                    f"Teste de resolucao DNS para app.lab.local falhou{detalhe_perfil}.",
                ],
                "hipoteses_descartadas": [
                    "falha_de_interface e falha_de_roteamento: transporte IP ate a sub-rede 192.168.20.0/24 integro.",
                ],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "dig", "dnsmasq", "dns"),
                "recomendacoes_correcao": [
                    f"Solicitar ao administrador ajustar o servidor DNS configurado para {alvo} para apontar "
                    f"para 192.168.20.10 e verificar o servico dnsmasq na porta 53."
                ],
                "limitacoes_investigacao": (
                    "No laboratorio Mininet, o perfil DNS experimental do cliente e avaliado via dig direcionado "
                    "sem modificar /etc/resolv.conf compartilhado."
                ),
            }, prompt_sistema, prompt_usuario, inicio)

        # Caso 6: Ping e DNS funcionam, mas HTTP falha -> investigar ACL!
        if servico_http is False:
            tentativa_acl = self._ja_tentou(historico, "consultar_acl", "server")
            if "acl" not in obs_srv and tentativa_acl is None and not forcar:
                return self._empacotar({
                    "acao": "solicitar_teste",
                    "raciocinio_atual": (
                        "Ping e DNS funcionam, mas HTTP (TCP/80) falhou. Solicitar leitura de 'iptables -S' "
                        "no servidor para verificar possivel regra DROP/REJECT de ACL."
                    ),
                    "hipoteses_em_aberto": ["bloqueio_acl", "problema_http_ou_bloqueio"],
                    "consulta_rag_adicional": "iptables -S INPUT tcp dport 80 DROP REJECT acl",
                    "solicitacao_teste": {
                        "operacao": "consultar_acl",
                        "dispositivo": "server",
                        "parametros": {},
                        "justificativa": "Verificar se ha regra iptables bloqueando TCP/80 para o cliente na cadeia INPUT.",
                    },
                }, prompt_sistema, prompt_usuario, inicio)

            # Resiliencia pos-bloqueio: se consultar_acl em server foi bloqueado pela politica restritiva,
            # testa HTTP a partir do outro cliente autorizado como evidencia indireta!
            outro_cliente = "client2" if alvo == "client1" else "client1"
            acl_foi_bloqueada = bool(
                tentativa_acl and tentativa_acl.get("decisao_validador", {}).get("autorizado") is False
            )
            if acl_foi_bloqueada and "http" not in obs_todas.get(outro_cliente, {}) and not forcar:
                if not self._ja_tentou(historico, "testar_http", outro_cliente):
                    return self._empacotar({
                        "acao": "solicitar_teste",
                        "raciocinio_atual": (
                            "A leitura direta de 'iptables -S' no servidor foi bloqueada pela politica de seguranca. "
                            f"Adaptando estrategia: testar HTTP a partir de {outro_cliente} (operacao autorizada) "
                            "para distinguir queda do processo HTTP de filtragem seletiva por origem."
                        ),
                        "hipoteses_em_aberto": ["problema_http_ou_bloqueio", "bloqueio_acl"],
                        "consulta_rag_adicional": "iptables restricao visibilidade http client2 bloqueio seletivo",
                        "solicitacao_teste": {
                            "operacao": "testar_http",
                            "dispositivo": outro_cliente,
                            "parametros": {"url": "http://192.168.20.10/", "metodo": "GET"},
                            "justificativa": f"Verificar se {outro_cliente} acessa HTTP/80 normalmente como controle.",
                        },
                    }, prompt_sistema, prompt_usuario, inicio)

            if self._regra_acl_bloqueia_http(obs_srv, ip_alvo):
                return self._empacotar({
                    "acao": "concluir_diagnostico",
                    "hipotese": "bloqueio_acl",
                    "confianca": "alta",
                    "diagnostico_fundamentado": (
                        f"Os testes de ping (ICMP) e dig (UDP/53) a partir de {alvo} ({ip_alvo}) funcionam "
                        f"normalmente, mas o acesso HTTP (TCP/80) falha. A inspecao de 'iptables -S' no servidor "
                        f"confirmou uma regra explicita na cadeia INPUT descartando/rejeitando pacotes TCP "
                        f"destinados a porta 80 provenientes de {ip_alvo}."
                    ),
                    "evidencias_utilizadas": [
                        f"Ping e resolucao DNS operacionais em {alvo}.",
                        f"Servico HTTP indisponivel para {alvo} (porta TCP/80).",
                        f"Regra iptables TCP/80 DROP/REJECT identificada no servidor para a origem {ip_alvo}.",
                    ],
                    "hipoteses_descartadas": [
                        "falha_de_interface, falha_de_roteamento e problema_dns: ICMP e DNS funcionam integralmente.",
                    ],
                    "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "iptables", "acl", "dport"),
                    "recomendacoes_correcao": [
                        f"Solicitar ao administrador revisar a politica de acesso no servidor e remover a regra "
                        f"de bloqueio indevida ('iptables -D INPUT -s {ip_alvo} -d 192.168.20.10 -p tcp --dport 80 -j DROP')."
                    ],
                    "limitacoes_investigacao": "Correlacao direta entre sintoma HTTP e regra estatica na tabela filter.",
                }, prompt_sistema, prompt_usuario, inicio)

            http_outro_ok = obs_todas.get(outro_cliente, {}).get("http", {}).get("servico_disponivel") is True
            evidencias_http = [
                f"Ping e DNS funcionando em {alvo}.",
                f"HTTP indisponivel a partir de {alvo}.",
            ]
            if http_outro_ok:
                evidencias_http.append(
                    f"Teste comparativo autorizado: HTTP funcional a partir de {outro_cliente}, indicando servico HTTP ativo e provavel filtragem seletiva."
                )
            else:
                evidencias_http.append("Regra especifica de bloqueio ACL nao confirmada nas evidencias visiveis.")

            return self._empacotar({
                "acao": "concluir_diagnostico",
                "hipotese": "problema_http_ou_bloqueio",
                "confianca": "indicativa",
                "diagnostico_fundamentado": (
                    f"Ping e DNS operam normalmente em {alvo}, mas o acesso HTTP falhou. "
                    + (
                        f"Embora o teste alternativo em {outro_cliente} comprove que o servidor HTTP esta ativo "
                        f"(forte indicio de bloqueio seletivo por ACL), a leitura direta de 'iptables -S' no "
                        f"servidor nao estava disponivel/autorizada, mantendo-se 'problema_http_ou_bloqueio' por rigor epistemico."
                        if acl_foi_bloqueada and http_outro_ok
                        else "Sem confirmacao direta de regra DROP/REJECT na ACL do servidor, nao se afirma bloqueio_acl confirmado."
                    )
                ),
                "evidencias_utilizadas": evidencias_http,
                "hipoteses_descartadas": [
                    "falha_de_interface, falha_de_roteamento e problema_dns: camadas inferiores operacionais."
                ],
                "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "iptables", "http"),
                "recomendacoes_correcao": [
                    "Solicitar ao administrador verificar diretamente no servidor as regras 'iptables -S' e os logs do processo HTTP na porta 80."
                ],
                "limitacoes_investigacao": (
                    "Inspecao direta da ACL do servidor bloqueada pela politica restritiva."
                    if acl_foi_bloqueada
                    else "Ausencia de regra explicita de bloqueio visivel para o cliente."
                ),
            }, prompt_sistema, prompt_usuario, inicio)

        # 7. Avaliacao de latencia e possivel congestionamento
        latencia = ping_obs.get("latencia_media_ms")
        if isinstance(latencia, (int, float)):
            indicio_congestionamento = (
                isinstance(lat_ref, (int, float))
                and lat_ref > 0
                and latencia >= lat_ref * 3
                and (latencia - lat_ref) >= 50
            )
            if indicio_congestionamento:
                # Propoe sonda curta de desempenho caso ainda nao tenha sido tentada,
                # exercitando tanto a sonda autorizada (padrao) quanto a resiliencia ao bloqueio (restritiva).
                tentativa_perf = self._ja_tentou(historico, "testar_desempenho", alvo)
                if "desempenho" not in obs_alvo and tentativa_perf is None and not forcar:
                    return self._empacotar({
                        "acao": "solicitar_teste",
                        "raciocinio_atual": (
                            f"Latencia media ({latencia:.3f} ms) muito acima da linha de base ({lat_ref:.3f} ms). "
                            "Solicitar sonda curta TCP iperf3 para complementar analise de congestionamento."
                        ),
                        "hipoteses_em_aberto": ["possivel_congestionamento"],
                        "consulta_rag_adicional": "tc qdisc congestionamento bufferbloat latencia iperf3",
                        "solicitacao_teste": {
                            "operacao": "testar_desempenho",
                            "dispositivo": alvo,
                            "parametros": {"destino": "192.168.20.10", "porta": 5202, "duracao_s": 3, "fluxos": 1},
                            "justificativa": "Medir vazao TCP disponivel diante de elevacao severa de RTT.",
                        },
                    }, prompt_sistema, prompt_usuario, inicio)

                perf_bloqueado = bool(
                    tentativa_perf and tentativa_perf.get("decisao_validador", {}).get("autorizado") is False
                )
                vazao = obs_alvo.get("desempenho", {}).get("vazao_mbps")
                evidencias_cong = [
                    f"Latencia atual: {latencia:.3f} ms.",
                    f"Latencia de referencia: {lat_ref:.3f} ms (aumento >= 3x e >= 50 ms).",
                    "Ping, DNS e HTTP permanecem funcionais, apontando sobrecarga/fila no enlace compartilhado.",
                ]
                if vazao is not None:
                    evidencias_cong.append(f"Vazao TCP medida na sonda controlada: {vazao:.3f} Mbps.")

                return self._empacotar({
                    "acao": "concluir_diagnostico",
                    "hipotese": "possivel_congestionamento",
                    "confianca": "indicativa",
                    "diagnostico_fundamentado": (
                        f"Todos os servicos funcionais (ping, DNS e HTTP) responderam em {alvo}, mas a latencia "
                        f"media ICMP subiu para {latencia:.3f} ms frente a linha de base de {lat_ref:.3f} ms "
                        f"(fator de {latencia / lat_ref:.1f}x). Conforme a documentacao de tc(8) e TCLink, essa "
                        f"assinatura caracteriza enfileiramento/bufferbloat sob disputa de banda no enlace router1-server."
                        + (
                            " A sonda ativa iperf3 foi restringida pela politica de seguranca, mas as evidencias "
                            "passivas/leves de RTT permitidas sustentam o diagnostico com seguranca."
                            if perf_bloqueado else ""
                        )
                    ),
                    "evidencias_utilizadas": evidencias_cong,
                    "hipoteses_descartadas": [
                        "falha_de_interface, falha_de_roteamento, problema_dns e bloqueio_acl: comunicacao funcional preservada."
                    ],
                    "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "tc", "iperf3", "congestionamento"),
                    "recomendacoes_correcao": [
                        "Recomendar ao administrador identificar fluxos concorrentes intensivos no enlace router1-server, "
                        "avaliar disciplinas de fila ('tc -s qdisc show') e ajustar capacidade ou politicas de QoS."
                    ],
                    "limitacoes_investigacao": (
                        "Sonda ativa iperf3 bloqueada pela politica restritiva; conclusao apoiada na degradacao expressiva de RTT."
                        if perf_bloqueado
                        else "Latencia elevada e forte indicio de fila/congestionamento no enlace limitado a 10 Mbps."
                    ),
                }, prompt_sistema, prompt_usuario, inicio)

            if latencia > 150:
                return self._empacotar({
                    "acao": "concluir_diagnostico",
                    "hipotese": "latencia_elevada",
                    "confianca": "indicativa",
                    "diagnostico_fundamentado": (
                        f"Os testes de ping, DNS e HTTP funcionam, porem observou-se latencia media elevada "
                        f"({latencia:.3f} ms) sem linha de base de referencia para confirmar o fator relativo "
                        f"de congestionamento."
                    ),
                    "evidencias_utilizadas": [
                        f"Latencia media observada: {latencia:.3f} ms (> 150 ms).",
                        "Ausencia de latencia de referencia para comparacao relativa.",
                    ],
                    "hipoteses_descartadas": ["falha_de_interface, falha_de_roteamento, problema_dns e bloqueio_acl."],
                    "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "tc", "latencia"),
                    "recomendacoes_correcao": [
                        "Coletar linha de base sem carga no enlace e inspecionar filas com 'tc -s qdisc show'."
                    ],
                    "limitacoes_investigacao": "Sem referencia basal nao se confirma conclusivamente possivel_congestionamento.",
                }, prompt_sistema, prompt_usuario, inicio)

        # 8. Operacao normal
        return self._empacotar({
            "acao": "concluir_diagnostico",
            "hipotese": "sem_anomalia_detectada",
            "confianca": "limitada",
            "diagnostico_fundamentado": (
                f"A interface {alvo}-eth0 esta ativa, a tabela de rotas contem encaminhamento funcional e "
                f"todos os testes de alcançabilidade IP (ping), resolucao de nomes (dig para app.lab.local) "
                f"e aplicacao HTTP (porta 80) responderam dentro dos parametros normais de latencia."
            ),
            "evidencias_utilizadas": [
                "Ping, resolucao DNS e servico HTTP funcionando normalmente.",
                "Nenhuma anomalia de interface, rota, ACL ou latencia identificada pelos testes.",
            ],
            "hipoteses_descartadas": [
                "falha_de_interface, falha_de_roteamento, problema_dns, bloqueio_acl e possivel_congestionamento."
            ],
            "fontes_rag_citadas": self._selecionar_chunks_rag(trechos_rag, "mininet", "iproute2"),
            "recomendacoes_correcao": [
                "Nenhuma intervencao corretiva necessaria; manter monitoramento regular do ambiente."
            ],
            "limitacoes_investigacao": (
                "Ausencia de anomalia nos testes contemplados nao equivale a garantia absoluta sobre servicos nao testados."
            ),
        }, prompt_sistema, prompt_usuario, inicio)

    @staticmethod
    def _empacotar(resposta_dict, prompt_sistema, prompt_usuario, inicio):
        texto_saida = json.dumps(resposta_dict, ensure_ascii=False)
        # Estimativa reprodutivel (~4 chars/token) para contabilizacao uniforme no modo simulado
        p_tokens = max(1, (len(prompt_sistema) + len(prompt_usuario)) // 4)
        c_tokens = max(1, len(texto_saida) // 4)
        latencia_ms = round((time.monotonic() - inicio) * 1000, 3)
        return {
            "resposta": resposta_dict,
            "uso_tokens": {
                "prompt_tokens": p_tokens,
                "completion_tokens": c_tokens,
                "total_tokens": p_tokens + c_tokens,
            },
            "latencia_ms": latencia_ms,
        }


def criar_cliente_llm(provedor=None, modelo=None, temperatura=0.0, max_tokens=1200, **kwargs):
    """Fabrica unificada de provedores LLM configuravel por CLI ou .env."""
    carregar_variaveis_env()
    prov = (provedor or os.environ.get("LLM_PROVEDOR") or "simulado").strip().lower()

    if prov == "simulado":
        return ClienteLLMSimulado(
            modelo=modelo or "simulado-react-rede-v1",
            temperatura=temperatura,
            max_tokens=max_tokens,
            injetar_teste_inseguro=kwargs.get("injetar_teste_inseguro", False),
        )
    if prov == "gemini":
        return ClienteGemini(modelo=modelo, temperatura=temperatura, max_tokens=max_tokens)
    if prov in ("openai", "groq", "openrouter"):
        base_url = kwargs.get("base_url")
        if prov == "groq" and not base_url and not os.environ.get("OPENAI_BASE_URL"):
            base_url = "https://api.groq.com/openai/v1"
        return ClienteOpenAICompativel(
            modelo=modelo, temperatura=temperatura, max_tokens=max_tokens, base_url=base_url,
        )
    if prov == "ollama":
        return ClienteOllama(modelo=modelo, temperatura=temperatura, max_tokens=max_tokens)

    raise ValueError(
        f"Provedor LLM desconhecido: '{prov}'. Opcoes validas: simulado, gemini, openai, groq, ollama."
    )
