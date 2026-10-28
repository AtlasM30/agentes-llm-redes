#!/usr/bin/env python3
"""Apresentacao integrada do projeto agentes-llm-redes.

Modos:
  - Reproducao fiel de auditoria Gemini real ja registrada.
  - Coleta nova no Mininet + diagnostico novo (Gemini ou simulado).
  - Diagnostico novo sobre evidencias existentes.
  - Resumo real dos experimentos e da seguranca.

Somente a opcao de coleta usa sudo; o agente nunca roda como root.
Nao importa gabarito para o agente nem altera os experimentos da Etapa 8.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

RAIZ = Path(__file__).resolve().parent
EXPERIMENTOS = RAIZ / "experimentos_etapa8"
ENTRADAS = EXPERIMENTOS / "entradas"
BATERIA = EXPERIMENTOS / "baterias" / "20261026T061113Z"
RESULTADOS = RAIZ / "resultados_apresentacao"
CENARIOS = {0: "Rede sem falhas", 1: "Falha DNS", 2: "Falha de roteamento", 3: "Interface desativada", 4: "Bloqueio ACL de HTTP", 5: "Congestionamento"}


def cabecalho(titulo):
    print("\n" + "=" * 74)
    print(titulo.upper())
    print("=" * 74, flush=True)


def pausa(automatico=False):
    if not automatico and sys.stdin.isatty():
        input("\n[ENTER] para continuar...")


def escolher_rotulo(pergunta, opcoes, padrao):
    print("\n" + pergunta)
    for chave, descricao in opcoes.items():
        print(f"  {chave} - {descricao}")
    escolha = input(f"Escolha [{padrao}]: ").strip() or padrao
    if escolha not in opcoes:
        print("Opcao invalida; aplicando o padrao.")
        escolha = padrao
    return escolha


def arquivo_auditoria_referencia():
    return (BATERIA / "restritiva" / "repeticao_01" / "caso_04" /
            "auditoria" / "auditoria_caso_04_restritiva_client1.json")


def exibir_auditoria(arquivo, automatico=False):
    dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    met = dados.get("metricas_sessao", {})
    final = dados.get("resultado_final", {})
    conf = dados.get("hiperparametros", {})

    cabecalho("1/5 - Contexto da investigacao")
    print(f"Origem: auditoria registrada - {Path(arquivo).name}")
    print(f"Cliente: {dados.get('dispositivo_alvo', 'N/D')}")
    print(f"Provedor: {conf.get('provedor_llm', 'N/D')} | Modelo: {conf.get('modelo_llm', 'N/D')}")
    print(f"Politica: {conf.get('politica_seguranca', 'N/D')}")
    print("NOTA: esta opcao REPRODUZ um registro anterior, nao executa o modelo agora.")
    pausa(automatico)

    cabecalho("2/5 - Agente ReAct: testes e validador")
    for passo in dados.get("passos_investigacao", []):
        pedido = passo.get("solicitacao_teste") or {}
        decisao = passo.get("decisao_validador") or {}
        acao = pedido.get("operacao", passo.get("acao_modelo", "etapa"))
        disp = pedido.get("dispositivo", "-")
        if decisao:
            autorizado = decisao.get("autorizado")
            simbolo = "AUTORIZADO" if autorizado else "BLOQUEADO"
            print(f"  {acao} em {disp} -> {simbolo} | {decisao.get('codigo_motivo', '')}")
        elif acao:
            print(f"  {acao}")
    pausa(automatico)

    cabecalho("3/5 - Fontes RAG e fundamentacao")
    fontes = final.get("fontes_rag_citadas", [])
    for fonte in fontes:
        print(f"  - {fonte}")
    if not fontes:
        print("  Fontes nao registradas.")
    print(f"Aderencia das citacoes (indicador interno): {met.get('taxa_aderencia_citacoes_rag', 'N/D')}")
    pausa(automatico)

    cabecalho("4/5 - Diagnostico e limitacoes")
    print(f"Hipotese: {final.get('hipotese', 'N/D')}")
    print(f"Confianca: {final.get('confianca', 'N/D')}")
    print("\nFundamentacao:")
    print(final.get("diagnostico_fundamentado", "Sem fundamentacao registrada"))
    print("\nLimitacoes declaradas:")
    print(final.get("limitacoes_investigacao", "Nenhuma registrada"))
    pausa(automatico)

    cabecalho("5/5 - Metricas e rastreabilidade")
    for campo, nome in (
        ("testes_propostos", "Testes propostos"),
        ("testes_autorizados_executados", "Testes autorizados/executados"),
        ("testes_bloqueados", "Testes bloqueados"),
        ("tokens_total", "Tokens registrados"),
        ("tempo_diagnostico_s", "Tempo do diagnostico (s)"),
    ):
        print(f"  {nome}: {met.get(campo, 'N/D')}")
    print(f"Arquivo de auditoria: {arquivo}")


def exibir_resultados():
    cabecalho("Resultados registrados - Etapa 8")
    resumo = EXPERIMENTOS / "consolidados" / "resumo_comparativo.json"
    if resumo.is_file():
        dados = json.loads(resumo.read_text(encoding="utf-8"))
        for politica, r in dados.get("politicas", {}).items():
            print(f"{politica}: {r.get('acertos')}/{r.get('total')} | acuracia {r.get('acuracia_percentual')}%")
            print(f"  Tempo medio (s): {r.get('tempo_s', {}).get('media')}")
            print(f"  Tokens medios: {r.get('tokens_total', {}).get('media')}")
            print(f"  Testes bloqueados: {r.get('testes_bloqueados_total')}")
    else:
        print(f"Resumo nao encontrado: {resumo}")

    seg = RAIZ / "resultados_agente" / "avaliacao_seguranca_validador.json"
    if seg.is_file():
        dados = json.loads(seg.read_text(encoding="utf-8"))
        print("\nBenchmark de seguranca:")
        for politica, r in dados.get("politicas", {}).items():
            total = r.get("total_solicitacoes", 0)
            corretas = r.get("autorizacoes_corretas", 0) + r.get("bloqueios_corretos", 0)
            print(f"{politica}: {corretas}/{total} decisoes concordantes com o esperado")
    else:
        print("\nBenchmark: arquivo de seguranca nao encontrado (opcional para o demo).")

    print("\nNota: 72/72 refere-se aos diagnosticos obtidos apos as recuperacoes.")
    print("Primeira bateria: 19/36 execucoes de cenario completas; 40/72 auditorias.")


def coletar_mininet(cenario, destino):
    """Roda SOMENTE ao chamar este script como root via --coletar-interno.

    Reutiliza exatamente a topologia e o coletor da Etapa 5.
    Grava um controle normal e depois um cenario recem-coletado.
    """
    if os.geteuid() != 0:
        raise SystemExit("A coleta precisa de sudo (somente nesta etapa).")
    from topology import construir_rede, iniciar_servicos, parar_processos, BANDA_MBIT
    from cenarios import GerenciadorCenarios
    from executar_experimentos import ColetorExperimental
    from mininet.log import setLogLevel

    setLogLevel("warning")
    net = None
    processos, arquivos = [], []
    gerenciador = None
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    try:
        cabecalho("Iniciando novo laboratorio Mininet")
        net = construir_rede()
        iniciar_servicos(net.get("server"), processos, arquivos)
        dns = {"client1": "192.168.20.10", "client2": "192.168.20.10"}
        gerenciador = GerenciadorCenarios(net, dns)
        coletor = ColetorExperimental(net, dns)
        # Referencia normal fresca, para comparar a latencia quando aplicavel.
        referencia = coletor.coletar_rede(cenario="controle_normal_apresentacao", testes_ativos=True, desempenho=False)
        referencia["enlace_servidor_mbps"] = BANDA_MBIT
        (destino / "evidencias_caso_00.json").write_text(
            json.dumps(referencia, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Controle normal coletado.", flush=True)
        nome = GerenciadorCenarios.NOMES[cenario]
        cabecalho(f"Aplicando falha controlada: {nome}")
        gerenciador.aplicar(nome)
        try:
            evidencias = coletor.coletar_rede(cenario=f"demo_{nome}", testes_ativos=True, desempenho=False)
            evidencias["enlace_servidor_mbps"] = BANDA_MBIT
            (destino / f"evidencias_caso_{cenario:02d}.json").write_text(
                json.dumps(evidencias, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Nova evidencia salva: {destino / f'evidencias_caso_{cenario:02d}.json'}")
        finally:
            gerenciador.restaurar()
    finally:
        if gerenciador is not None:
            try:
                gerenciador.restaurar()
            except Exception as exc:
                print(f"Aviso durante restauracao: {exc}")
        parar_processos(processos, arquivos)
        if net is not None:
            net.stop()
        print("Topologia temporaria encerrada.", flush=True)


def diagnosticar(evidencia, pasta_logs, politica, provedor, pasta_saida):
    cabecalho("Diagnostico novo - agente + RAG + validador")
    cmd = [sys.executable, "-u", str(RAIZ / "executar_agente.py"),
           "--provedor", provedor,
           "--politica", politica,
           "--modo-evidencias", "progressivo",
           "--cliente", "client1", "--logs", str(pasta_logs),
           "--auditoria-dir", str(pasta_saida)]
    # --arquivo faz o programa diagnosticar exatamente a evidencia escolhida.
    cmd.extend(["--arquivo", str(evidencia)])
    if provedor == "gemini":
        cmd.extend(["--modelo", "gemini-3.1-flash-lite", "--temperatura", "0.0", "--top-k", "4"])
    print("Executando o AGENTE DE VERDADE sobre o arquivo escolhido.")
    print("Modo:", "Gemini real via API" if provedor == "gemini" else "provedor simulado - sem API")
    print("Comando:", " ".join(cmd), flush=True)
    ret = subprocess.run(cmd, cwd=RAIZ, check=False)
    if ret.returncode != 0:
        print("\nFalha na execucao do agente. Voce pode usar a auditoria gravada como plano B.")
        return False
    arquivos = sorted(pasta_saida.glob("auditoria_*.json"), key=lambda p: p.stat().st_mtime)
    if arquivos:
        print(f"\nAuditoria nova criada: {arquivos[-1]}")
        print("A mesma auditoria pode ser exibida em formato guiado.")
    return True


def menu():
    cabecalho("Agentes LLM - Demonstracao integrada")
    print("1 - Diagnostico NOVO: coletar novamente no Mininet e usar Gemini real")
    print("2 - Diagnostico NOVO: usar evidencias existentes e Gemini real")
    print("3 - Diagnostico NOVO: usar provedor simulado (sem internet)")
    print("4 - Reproduzir auditoria REAL do Gemini (ACL restritiva, passo a passo)")
    print("5 - Mostrar resultados consolidados e seguranca")
    print("0 - Sair")


def main():
    parser = argparse.ArgumentParser(description="Apresentacao integrada dos agentes LLM")
    parser.add_argument("--coletar-interno", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cenario", type=int, choices=CENARIOS.keys(), default=4)
    parser.add_argument("--saida", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--replay", action="store_true", help="Executa apenas reproducao gravada")
    parser.add_argument("--resumo", action="store_true", help="Exibe resultados consolidados")
    parser.add_argument("--automatico", action="store_true", help="Nao pausar a cada etapa")
    args = parser.parse_args()
    if args.coletar_interno:
        if args.saida is None:
            parser.error("--saida obrigatorio para coleta")
        coletar_mininet(args.cenario, args.saida)
        return
    if args.replay:
        exibir_auditoria(arquivo_auditoria_referencia(), args.automatico)
        return
    if args.resumo:
        exibir_resultados()
        return

    while True:
        menu()
        opcao = input("\nEscolha: ").strip()
        if opcao == "0":
            break
        if opcao == "4":
            try:
                exibir_auditoria(arquivo_auditoria_referencia())
            except (OSError, ValueError, KeyError) as exc:
                print("Auditoria indisponivel:", exc)
            continue
        if opcao == "5":
            exibir_resultados()
            pausa()
            continue
        if opcao not in ("1", "2", "3"):
            print("Opcao invalida")
            continue

        cenario = int(escolher_rotulo("Escolha o tipo de falha controlada:",
                         {str(k): v for k, v in CENARIOS.items()}, "4"))
        politica = escolher_rotulo("Politica de seguranca:",
                                  {"padrao": "Padrao", "restritiva": "Restritiva"}, "restritiva")
        provedor = "simulado" if opcao == "3" else "gemini"
        sessao = RESULTADOS / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        sessao.mkdir(parents=True, exist_ok=False)
        pasta_logs = sessao / "evidencias" if opcao == "1" else ENTRADAS
        evidencia = pasta_logs / f"evidencias_caso_{cenario:02d}.json"
        if opcao == "1":
            cabecalho("Coleta de evidencia NOVA, sem acessar a API")
            print("Sera criada uma topologia Mininet temporaria com falha controlada.")
            print("O gabarito nao sera enviado ao agente.")
            comando = ["sudo", "/usr/bin/python3", str(Path(__file__).resolve()),
                       "--coletar-interno", "--cenario", str(cenario), "--saida", str(pasta_logs)]
            retorno = subprocess.run(comando, cwd=RAIZ, check=False)
            if retorno.returncode != 0:
                print("Falha na coleta. Verifique Mininet e privilegios sudo.")
                continue
        if not evidencia.is_file():
            print("Arquivo de evidencias nao encontrado:", evidencia)
            continue
        print("\nEvidencias selecionadas:", evidencia)
        pausa()
        sucesso = diagnosticar(evidencia, pasta_logs, politica, provedor, sessao / "auditorias")
        if sucesso:
            auditorias = list((sessao / "auditorias").glob("auditoria_*.json"))
            if auditorias and input("\nMostrar o resultado em etapas? [S/n] ").strip().lower() != "n":
                exibir_auditoria(auditorias[0])
        pausa()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDemonstracao interrompida.")
