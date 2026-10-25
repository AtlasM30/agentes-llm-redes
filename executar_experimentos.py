#!/usr/bin/env python3
"""Executa seis cenarios controlados, usando o coletor.py ja desenvolvido.

Requer: Ubuntu/Mininet, openvswitch-switch, dnsmasq, iperf3, iptables, curl,
dnsutils e o arquivo coleta/coletor.py existente no projeto.
Execute na RAIZ do projeto com sudo python3 executar_experimentos.py.
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from mininet.net import Mininet
from mininet.node import Node, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

from coleta.coletor import ColetorEvidencias
from cenarios import GerenciadorCenarios, GABARITOS

RAIZ = Path(__file__).resolve().parent


from topology import construir_rede, iniciar_servicos, parar_processos, BANDA_MBIT


class ColetorExperimental(ColetorEvidencias):
    """Adapta somente o DNS para usar o perfil de DNS de cada cliente.

    Nao altera /etc/resolv.conf da VM e nao executa comandos do LLM.
    """
    def __init__(self, rede, dns_clientes):
        super().__init__(rede)
        self.dns_clientes = dns_clientes

    def testar_dns(self, dispositivo):
        if dispositivo not in self.CLIENTES:
            return {'sucesso': False, 'erro': 'Origem nao autorizada'}
        servidor = self.dns_clientes[dispositivo]
        resultado = self.executar(dispositivo,
            ['dig', f'@{servidor}', self.DOMINIO, 'A',
             '+time=1', '+tries=1', '+short'], timeout=4)
        enderecos = [l.strip() for l in resultado.get('saida', '').splitlines()
                     if l.strip()]
        resultado.update({
            'dominio': self.DOMINIO,
            'dns_configurado_no_perfil': servidor,
            'enderecos_resolvidos': enderecos,
            'resolucao_correta': resultado.get('sucesso', False)
                                 and self.SERVIDOR_IP in enderecos,
            'observacao': 'DNS do perfil experimental; nao altera resolv.conf'
        })
        return resultado

    def coletar_dispositivo(self, dispositivo, testes_ativos=True, desempenho=False):
        # Desempenho feito separadamente, para nao disputar a mesma porta
        # iperf3 e nao gerar carga em todos os cenarios.
        dados = super().coletar_dispositivo(
            dispositivo, testes_ativos=testes_ativos, desempenho=False)
        if dispositivo in self.CLIENTES:
            dados['perfil_dns'] = self.dns_clientes[dispositivo]
        return dados


def executar():
    net = None
    processos, arquivos = [], []
    gerenciador = None
    try:
        net = construir_rede()
        iniciar_servicos(net.get('server'), processos, arquivos)
        dns_clientes = {
            'client1': '192.168.20.10',
            'client2': '192.168.20.10'
        }
        coletor = ColetorExperimental(net, dns_clientes)
        gerenciador = GerenciadorCenarios(net, dns_clientes)
        gabaritos = {}
        for indice, nome in enumerate(GerenciadorCenarios.NOMES):
            identificador = f'caso_{indice:02d}'
            print(f'\n=== Executando {identificador} ===', flush=True)
            gerenciador.aplicar(nome)
            try:
                dados = coletor.coletar_rede(
                    cenario=identificador, testes_ativos=True, desempenho=False)
                dados['tipo_dns'] = 'perfil de cliente experimental'
                dados['enlace_servidor_mbps'] = BANDA_MBIT
                dados['execucao'] = datetime.now().astimezone().isoformat()
                coletor.salvar(dados)
                gabaritos[identificador] = {
                    'cenario': nome, 'causa_real': GABARITOS[nome]
                }
            finally:
                gerenciador.restaurar()

        destino = RAIZ / 'dados' / 'gabaritos'
        destino.mkdir(parents=True, exist_ok=True)
        (destino / 'causas_reais.json').write_text(
            json.dumps(gabaritos, ensure_ascii=False, indent=2),
            encoding='utf-8')
        print('\nConcluido: seis JSONs em logs/ e gabarito separado em dados/gabaritos/')
    finally:
        if gerenciador is not None:
            gerenciador.restaurar()
        parar_processos(processos, arquivos)
        if net is not None:
            net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    executar()
