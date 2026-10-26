#!/usr/bin/env python3
"""Executa o Agente LLM de Diagnostico com RAG e Validacao Deterministica (Etapa 7).

Exemplos de uso:
    # Sobre os logs coletados na Etapa 5 (modo progressivo multi-etapa):
    python3 executar_agente.py --provedor simulado --politica padrao

    # Usando API externa (configurada em .env):
    python3 executar_agente.py --provedor gemini --modelo gemini-2.5-flash

    # Avaliando impacto da politica restritiva (resiliencia):
    python3 executar_agente.py --provedor simulado --politica restritiva

    # Teste de fumaca sintetico (quando logs/ ainda nao foi copiado da VM):
    python3 executar_agente.py --demonstracao-sintetica
"""
import argparse
from pathlib import Path

from agente.auditoria import ConfiguracaoAgente
from agente.diagnostico_agente import AgenteDiagnosticoRedes
from agente.executor import verificar_arquivo_evidencia_permitido
from agente.provedores_llm import criar_cliente_llm
from diagnostico.pipeline import carregar_evidencias
from rag.recuperador import RecuperadorRAG
from seguranca.validador import ValidadorDeterministico


def obter_latencia(evidencias_disp):
    return evidencias_disp.get("ping", {}).get("latencia_media_ms")


def construir_casos_demonstracao_sintetica():
    """Gera 6 estruturas neutras compativeis com o coletor apenas para teste de fumaca."""
    def _base_disp(nome, ip, up=True, rota_default=True, ping_ok=True, rtt=24.0,
                   dns_ok=True, dns_srv="192.168.20.10", http_ok=True):
        estado = "UP" if up else "DOWN"
        flags = "<BROADCAST,MULTICAST,UP,LOWER_UP>" if up else "<BROADCAST,MULTICAST>"
        saida_rotas = (
            f"default via 192.168.10.1 dev {nome}-eth0\n192.168.10.0/24 dev {nome}-eth0 proto kernel scope link src {ip}"
            if (up and rota_default)
            else (f"192.168.10.0/24 dev {nome}-eth0 proto kernel scope link src {ip}" if up else "")
        )
        return {
            "interfaces": {
                "enderecos": {"sucesso": True, "saida": f"{nome}-eth0 UP {ip}/24" if up else f"{nome}-eth0 DOWN"},
                "estado": {"sucesso": True, "saida": f"{nome}-eth0@if10 {estado} 00:00:00:00:00:01 {flags}"},
                "estatisticas": {"sucesso": True, "saida": f"2: {nome}-eth0: RX 1200 bytes TX 1100 bytes"},
            },
            "rotas": {"sucesso": True, "saida": saida_rotas},
            "acl": {"sucesso": True, "saida": "-P INPUT ACCEPT\n-P FORWARD ACCEPT\n-P OUTPUT ACCEPT"},
            "ping": {
                "sucesso": ping_ok,
                "destino": "192.168.20.10",
                "pacotes_enviados": 3,
                "perda_percentual": 0.0 if ping_ok else 100.0,
                "latencia_media_ms": rtt if ping_ok else None,
                "saida": f"rtt min/avg/max/mdev = {rtt:.3f}/{rtt:.3f}/{rtt:.3f}/0.100 ms" if ping_ok else "Network is unreachable",
            },
            "dns": {
                "sucesso": dns_ok,
                "dominio": "app.lab.local",
                "dns_configurado_no_perfil": dns_srv,
                "enderecos_resolvidos": ["192.168.20.10"] if dns_ok else [],
                "resolucao_correta": dns_ok,
                "saida": "192.168.20.10" if dns_ok else ";; communications error: timed out",
            },
            "http": {
                "sucesso": http_ok,
                "url": "http://192.168.20.10/",
                "codigo_http": 200 if http_ok else None,
                "servico_disponivel": http_ok,
                "saida": "200" if http_ok else "000",
            },
        }

    def _pacote(c1, c2, acl_srv="-P INPUT ACCEPT\n-P FORWARD ACCEPT\n-P OUTPUT ACCEPT"):
        return {
            "servidor": "192.168.20.10",
            "dominio": "app.lab.local",
            "enlace_servidor_mbps": 10,
            "dispositivos": {
                "client1": c1,
                "client2": c2,
                "router1": {
                    "interfaces": {"estado": {"sucesso": True, "saida": "router1-eth0 UP\nrouter1-eth1 UP"}},
                    "rotas": {"sucesso": True, "saida": "192.168.10.0/24 dev router1-eth0\n192.168.20.0/24 dev router1-eth1"},
                    "acl": {"sucesso": True, "saida": "-P FORWARD ACCEPT"},
                },
                "server": {
                    "interfaces": {"estado": {"sucesso": True, "saida": "server-eth0 UP"}},
                    "rotas": {"sucesso": True, "saida": "default via 192.168.20.1 dev server-eth0"},
                    "acl": {"sucesso": True, "saida": acl_srv},
                },
            },
        }

    c2_ok = lambda rtt=22.0: _base_disp("client2", "192.168.10.3", rtt=rtt)
    return [
        ("sintetico_00", _pacote(_base_disp("client1", "192.168.10.2", rtt=33.4), c2_ok(24.2))),
        ("sintetico_01", _pacote(_base_disp("client1", "192.168.10.2", dns_ok=False, dns_srv="192.168.20.99"), c2_ok())),
        ("sintetico_02", _pacote(_base_disp("client1", "192.168.10.2", rota_default=False, ping_ok=False, dns_ok=False, http_ok=False), c2_ok())),
        ("sintetico_03", _pacote(_base_disp("client1", "192.168.10.2", up=False, rota_default=False, ping_ok=False, dns_ok=False, http_ok=False), c2_ok())),
        ("sintetico_04", _pacote(
            _base_disp("client1", "192.168.10.2", http_ok=False),
            c2_ok(),
            acl_srv="-P INPUT ACCEPT\n-A INPUT -s 192.168.10.2/32 -d 192.168.20.10/32 -p tcp -m tcp --dport 80 -j DROP",
        )),
        ("sintetico_05", _pacote(_base_disp("client1", "192.168.10.2", rtt=199.2), c2_ok(357.8))),
    ]


def main():
    parser = argparse.ArgumentParser(description="Executa o Agente LLM de Diagnostico (Etapa 7)")
    parser.add_argument("--provedor", default="simulado", choices=("simulado", "gemini", "openai", "groq", "ollama"))
    parser.add_argument("--modelo", default=None, help="Nome do modelo no provedor escolhido")
    parser.add_argument("--temperatura", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-iteracoes", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--politica", default="padrao", choices=("padrao", "restritiva"))
    parser.add_argument("--modo-evidencias", default="progressivo", choices=("progressivo", "completo"))
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    parser.add_argument("--caso", type=int, choices=range(6), default=None, help="Executa apenas um caso (0 a 5)")
    parser.add_argument("--arquivo", type=Path, default=None, help="Executa sobre um arquivo JSON especifico")
    parser.add_argument("--auditoria-dir", type=Path, default=Path("resultados_agente/auditoria"))
    parser.add_argument("--sem-salvar-auditoria", action="store_true")
    parser.add_argument(
        "--demonstracao-sintetica",
        action="store_true",
        help="Executa demonstracao em memoria caso logs/ ainda nao esteja presente localmente",
    )
    parser.add_argument(
        "--cliente",
        choices=["client1", "client2"],
        default=None,
        help="Executa somente o cliente selecionado; por padrao executa ambos."
    )
    args = parser.parse_args()

    recuperador = RecuperadorRAG()
    validador = ValidadorDeterministico(politica=args.politica)
    cliente_llm = criar_cliente_llm(
        provedor=args.provedor,
        modelo=args.modelo,
        temperatura=args.temperatura,
        max_tokens=args.max_tokens,
    )
    config = ConfiguracaoAgente(
        provedor_llm=cliente_llm.provedor,
        modelo_llm=cliente_llm.modelo,
        temperatura=args.temperatura,
        max_tokens_resposta=args.max_tokens,
        max_iteracoes=args.max_iteracoes,
        top_k_rag=args.top_k,
        politica_seguranca=args.politica,
        modo_evidencias=args.modo_evidencias,
        versao_indice_rag=recuperador.versao_indice,
    )
    agente = AgenteDiagnosticoRedes(
        cliente_llm=cliente_llm,
        recuperador_rag=recuperador,
        validador=validador,
        configuracao=config,
    )

    entradas = []
    referencias = {"client1": None, "client2": None}

    if args.demonstracao_sintetica:
        print("[MODO DEMONSTRACAO SINTETICA ATIVO — Nao substitui os logs reais do Mininet]")
        casos_demo = construir_casos_demonstracao_sintetica()
        dados_base = casos_demo[0][1]
        referencias = {
            nome: obter_latencia(dados_base["dispositivos"][nome])
            for nome in ("client1", "client2")
        }
        entradas = [casos_demo[args.caso]] if args.caso is not None else casos_demo
    elif args.arquivo is not None:
        verificar_arquivo_evidencia_permitido(args.arquivo)
        dados = carregar_evidencias(args.arquivo)
        arq_base = args.logs / "evidencias_caso_00.json"
        if arq_base.is_file():
            base = carregar_evidencias(arq_base)
            referencias = {nome: obter_latencia(base["dispositivos"][nome]) for nome in ("client1", "client2")}
        entradas = [(args.arquivo.stem, dados)]
    else:
        arq_base = args.logs / "evidencias_caso_00.json"
        if not arq_base.is_file():
            raise SystemExit(
                f"Evidencias nao encontradas em '{args.logs}/'.\n"
                "Copie os arquivos logs/evidencias_caso_00..05.json gerados na VM Mininet "
                "(sudo python3 executar_experimentos.py) ou utilize --demonstracao-sintetica "
                "apenas para verificacao funcional offline do pipeline."
            )
        base = carregar_evidencias(arq_base)
        referencias = {nome: obter_latencia(base["dispositivos"][nome]) for nome in ("client1", "client2")}
        indices = [args.caso] if args.caso is not None else list(range(6))
        for numero in indices:
            caminho = args.logs / f"evidencias_caso_{numero:02d}.json"
            verificar_arquivo_evidencia_permitido(caminho)
            entradas.append((f"caso_{numero:02d}", carregar_evidencias(caminho)))

    for identificador, dados_rede in entradas:
        print(f"\n{'=' * 68}")
        print(f"SESSAO AGENTE LLM — {identificador.upper()} (Politica: {args.politica})")
        print("=" * 68)

        clientes = [args.cliente] if args.cliente else ["client1", "client2"]
        for nome in clientes:
            print(f"[*] Analisando {nome} com {args.provedor} ({agente.config.modelo_llm})...", flush=True)
            _, auditoria = agente.diagnosticar(
                dispositivo=nome,
                evidencias_rede=dados_rede,
                latencia_referencia=referencias.get(nome),
                identificador_sessao=f"{identificador}_{args.politica}",
            )
            print("\n" + auditoria.formatar_relatorio_legivel())
            if not args.sem_salvar_auditoria and not args.demonstracao_sintetica:
                caminho_aud = auditoria.salvar_json(args.auditoria_dir)
                print(f"Auditoria salva       : {caminho_aud}")


if __name__ == "__main__":
    main()
