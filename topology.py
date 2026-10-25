#!/usr/bin/env python3
"""Topologia integrada para a Etapa 5 (Mininet).

Interface reutilizavel: construir_rede(), iniciar_servicos(), parar_processos().
Nao executa mount nem altera /etc/resolv.conf da VM; nao usa killall.
"""
import subprocess
import sys
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import Node, OVSSwitch

RAIZ = Path(__file__).resolve().parent
SERVIDOR_IP = '192.168.20.10'
DOMINIO = 'app.lab.local'
BANDA_MBIT = 10   # parametro experimental: use 100 para replicar o enlace original
ATRASO = '10ms'  # por direcao; especificar no relatorio


class Roteador(Node):
    def config(self, **params):
        super().config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')


def construir_rede():
    net = Mininet(topo=None, controller=None, switch=OVSSwitch,
                  link=TCLink, build=False, autoSetMacs=True)
    c1 = net.addHost('client1', ip='192.168.10.2/24',
                     defaultRoute='via 192.168.10.1')
    c2 = net.addHost('client2', ip='192.168.10.3/24',
                     defaultRoute='via 192.168.10.1')
    r = net.addHost('router1', cls=Roteador, ip=None)
    s = net.addHost('server', ip='192.168.20.10/24',
                    defaultRoute='via 192.168.20.1')
    sw = net.addSwitch('switch1', failMode='standalone')
    net.addLink(c1, sw)
    net.addLink(c2, sw)
    net.addLink(sw, r, intfName2='router1-eth0')
    net.addLink(r, s, intfName1='router1-eth1',
                intfName2='server-eth0', bw=BANDA_MBIT, delay=ATRASO)
    try:
        net.build()
        net.start()
        for comando in (
            'ip addr replace 192.168.10.1/24 dev router1-eth0',
            'ip addr replace 192.168.20.1/24 dev router1-eth1',
            'ip link set router1-eth0 up',
            'ip link set router1-eth1 up',
        ):
            saida = r.cmd(comando)
            if 'Error:' in saida or 'Cannot find device' in saida:
                raise RuntimeError(f'Falha configurando roteador: {comando}: {saida}')
        return net
    except Exception:
        net.stop()
        raise


def iniciar_servicos(server, processos, arquivos):
    """Processos rastreados individualmente; sem interferencia no host Ubuntu."""
    pasta = RAIZ / 'logs' / 'servicos'
    pasta.mkdir(parents=True, exist_ok=True)
    servicos = (
        ('http', [sys.executable, '-m', 'http.server', '80', '--bind', SERVIDOR_IP]),
        ('dns', ['dnsmasq', '--no-daemon', '--no-resolv', '--no-hosts',
                 '--bind-interfaces', '--listen-address=' + SERVIDOR_IP,
                 '--address=/' + DOMINIO + '/' + SERVIDOR_IP, '--port=53']),
        ('iperf3', ['iperf3', '-s', '-B', SERVIDOR_IP, '-p', '5201']),
    )
    for nome, args in servicos:
        arquivo = open(pasta / f'{nome}.log', 'wb')
        arquivos.append(arquivo)
        p = server.popen(args, stdin=subprocess.DEVNULL,
                         stdout=arquivo, stderr=subprocess.STDOUT)
        processos.append(p)
    time.sleep(2)
    for (nome, _), p in zip(servicos, processos[-len(servicos):]):
        if p.poll() is not None:
            raise RuntimeError(f'Servico {nome} terminou. Veja logs/servicos/{nome}.log')


def parar_processos(processos, arquivos):
    for p in reversed(processos):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    for arquivo in arquivos:
        if not arquivo.closed:
            arquivo.close()


if __name__ == '__main__':
    from mininet.log import setLogLevel
    setLogLevel('info')
    rede = None
    processos, arquivos = [], []
    try:
        rede = construir_rede()
        iniciar_servicos(rede.get('server'), processos, arquivos)
        print('Topologia iniciada. Teste simples:')
        print(rede.get('client1').cmd('ping -n -c 2 -W 2 192.168.20.10'))
        print(rede.get('client1').cmd('dig @192.168.20.10 app.lab.local +short'))
        print(rede.get('client1').cmd('curl --noproxy "*" -sS -o /dev/null -w "%{http_code}" http://192.168.20.10/'))
    finally:
        parar_processos(processos, arquivos)
        if rede is not None:
            rede.stop()
