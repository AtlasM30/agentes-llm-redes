#!/usr/bin/env python3
"""Experimento reproduzivel: baseline x congestionamento (Mininet).

Uso: sudo python3 validar_desempenho.py --repeticoes 3

Reutiliza a rede e os servicos do executar_experimentos.py sem modifica-lo.
Gera CSV e JSON com medicoes brutas, resumos e ambiente.
"""
import argparse
import csv
import json
import platform
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

from coleta.coletor import ColetorEvidencias
from cenarios import GerenciadorCenarios
from executar_experimentos import construir_rede, iniciar_servicos, parar_processos

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / 'dados' / 'desempenho'
CLIENTES = ('client1', 'client2')
PORTA_SONDA = 5202  # exclusiva, separada do fluxo concorrente na porta 5201


def versao(comando):
    try:
        p = subprocess.run(comando, capture_output=True, text=True, timeout=8)
        return ((p.stdout or p.stderr).strip().splitlines() or ['indisponivel'])[0]
    except (OSError, subprocess.TimeoutExpired) as e:
        return f'indisponivel: {e}'


def iniciar_servidor_sonda(server, processos, arquivos):
    pasta = RAIZ / 'logs' / 'servicos'
    pasta.mkdir(parents=True, exist_ok=True)
    log = open(pasta / 'iperf3_sonda.log', 'wb')
    arquivos.append(log)
    processo = server.popen(['iperf3', '-s', '-B', '192.168.20.10',
                             '-p', str(PORTA_SONDA)],
                            stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT)
    processos.append(processo)
    time.sleep(1)
    if processo.poll() is not None:
        raise RuntimeError('Servidor iperf3 de sonda nao iniciou; veja logs/servicos/iperf3_sonda.log')


def medir_vazao(cliente):
    """Mede vazao TCP recebida; devolve erro explicito se indisponivel."""
    proc = cliente.popen(['iperf3', '-c', '192.168.20.10', '-p', str(PORTA_SONDA),
                          '-t', '5', '-J'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    try:
        saida, erros = proc.communicate(timeout=35)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return {'sucesso': False, 'vazao_mbps': None, 'erro': 'Timeout no iperf3'}
    if proc.returncode != 0:
        return {'sucesso': False, 'vazao_mbps': None,
                'erro': erros.decode('utf-8', 'replace')[:1000]}
    try:
        dados = json.loads(saida.decode('utf-8', 'replace'))
        end = dados.get('end', {})
        # TCP receiver-side throughput (measured at target).
        taxas = end.get('sum_received', {}).get('bits_per_second')
        if taxas is None:
            raise ValueError('Campo end.sum_received.bits_per_second ausente')
        return {'sucesso': True, 'vazao_mbps': round(taxas / 1_000_000, 3)}
    except (ValueError, KeyError, TypeError) as e:
        return {'sucesso': False, 'vazao_mbps': None, 'erro': str(e)}


def medir_condicao(coletor, rede, condicao, repeticao, gerenciador):
    if condicao == 'congestionamento':
        gerenciador.aplicar('congestionamento')
        if gerenciador._carga is None or gerenciador._carga.poll() is not None:
            raise RuntimeError('Trafego concorrente nao esta ativo')
    try:
        resultados = []
        for cliente in CLIENTES:
            if condicao == 'congestionamento' and gerenciador._carga.poll() is not None:
                raise RuntimeError('Carga concorrente terminou antes da coleta')
            ping = coletor.testar_ping(cliente)
            vazao = medir_vazao(rede.get(cliente))
            resultados.append({
                'repeticao': repeticao,
                'condicao': condicao,
                'cliente': cliente,
                'ping_sucesso': ping.get('sucesso'),
                'perda_percentual': ping.get('perda_percentual'),
                'latencia_media_ms': ping.get('latencia_media_ms'),
                'vazao_sucesso': vazao.get('sucesso'),
                'vazao_mbps': vazao.get('vazao_mbps'),
                'erro_ping': ping.get('erro', ''),
                'erro_vazao': vazao.get('erro', ''),
            })
            print(f"  {cliente}: ping={ping.get('sucesso')}, "
                  f"latencia={ping.get('latencia_media_ms')} ms, "
                  f"perda={ping.get('perda_percentual')}%, "
                  f"vazao={vazao.get('vazao_mbps')} Mbps", flush=True)
        return resultados
    finally:
        if condicao == 'congestionamento':
            gerenciador.restaurar()


def resumir(linhas):
    resumo = {}
    for cliente in CLIENTES:
        resumo[cliente] = {}
        for condicao in ('normal', 'congestionamento'):
            registros = [x for x in linhas if x['cliente'] == cliente and x['condicao'] == condicao]
            medidas = {}
            for campo in ('latencia_media_ms', 'perda_percentual', 'vazao_mbps'):
                valores = [float(x[campo]) for x in registros if x[campo] is not None]
                medidas[campo] = {
                    'n_validas': len(valores),
                    'media': round(statistics.mean(valores), 3) if valores else None,
                    'mediana': round(statistics.median(valores), 3) if valores else None,
                    'desvio_padrao_amostral': round(statistics.stdev(valores), 3) if len(valores) > 1 else None,
                }
            medidas['n_execucoes'] = len(registros)
            resumo[cliente][condicao] = medidas
    return resumo


def salvar(linhas, metadados):
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo_csv = DESTINO / 'medicoes.csv'
    with arquivo_csv.open('w', encoding='utf-8', newline='') as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    resumo = resumir(linhas)
    arquivo_json = DESTINO / 'resumo_desempenho.json'
    arquivo_json.write_text(json.dumps({
        'metadados': metadados, 'resumo': resumo, 'medicoes': linhas,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return arquivo_csv, arquivo_json, resumo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeticoes', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeticoes <= 10:
        parser.error('--repeticoes deve estar entre 1 e 10')
    metadados = {
        'data_inicio': datetime.now().astimezone().isoformat(),
        'repeticoes': args.repeticoes,
        'topologia': 'laboratorio independente: client1/client2 -> switch1 -> router1 -> server',
        'ip_servidor': '192.168.20.10',
        'enlace_servidor': '10 Mbps, 10 ms por direcao configurados no TCLink',
        'iperf3_carga': 'TCP, client2->server, 2 fluxos paralelos, porta 5201, ate 90s por rodada',
        'iperf3_sonda': 'TCP, cada cliente->server, 5s, porta 5202, sequencial',
        'ping': '3 pacotes por cliente; medido antes da sonda iperf3',
        'kernel': platform.release(),
        'versoes': {
            'python': platform.python_version(),
            'mininet': versao(['mn', '--version']),
            'iperf3': versao(['iperf3', '--version']),
            'ovs': versao(['ovs-vsctl', '--version']),
        },
        'nota': ('O iperf3 sonda compartilha o enlace com o fluxo de carga. '
                 'As medidas de clientes sao sequenciais e cada rodada de carga '
                 'comeca novamente. Nao sao medidas simultaneas de ping e vazao.'),
    }
    rede = None
    gerenciador = None
    processos, arquivos = [], []
    linhas = []
    try:
        rede = construir_rede()
        iniciar_servicos(rede.get('server'), processos, arquivos)
        iniciar_servidor_sonda(rede.get('server'), processos, arquivos)
        dns = {cliente: '192.168.20.10' for cliente in CLIENTES}
        gerenciador = GerenciadorCenarios(rede, dns)
        coletor = ColetorEvidencias(rede)
        for repeticao in range(1, args.repeticoes + 1):
            for condicao in ('normal', 'congestionamento'):
                if condicao == 'normal' and repeticao > 1:
                    print('Aguardando recuperacao (15 s)...', flush=True)
                    time.sleep(15)
                print(f'\n[Rodada {repeticao}/{args.repeticoes}] {condicao}', flush=True)
                linhas.extend(medir_condicao(coletor, rede, condicao, repeticao, gerenciador))
        metadados['data_fim'] = datetime.now().astimezone().isoformat()
        arquivo_csv, arquivo_json, resumo = salvar(linhas, metadados)
        print('\n=== RESUMO (medianas) ===')
        for cliente in CLIENTES:
            print(f'\n{cliente}')
            for condicao in ('normal', 'congestionamento'):
                medidas = resumo[cliente][condicao]
                print(f"  {condicao}: latencia={medidas['latencia_media_ms']['mediana']} ms, "
                      f"perda={medidas['perda_percentual']['mediana']}%, "
                      f"vazao={medidas['vazao_mbps']['mediana']} Mbps")
        print(f'\nCSV: {arquivo_csv}\nJSON: {arquivo_json}')
    finally:
        if gerenciador is not None:
            gerenciador.restaurar()
        parar_processos(processos, arquivos)
        if rede is not None:
            rede.stop()
        if linhas and len(linhas) < args.repeticoes * 2 * len(CLIENTES):
            metadados['execucao_incompleta'] = True
            metadados['data_fim'] = datetime.now().astimezone().isoformat()
            salvar(linhas, metadados)


if __name__ == '__main__':
    main()
