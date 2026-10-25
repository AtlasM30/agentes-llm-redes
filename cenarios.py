"""Cenarios de falha exclusivos do laboratorio Mininet.

DNS: a configuracao DNS por cliente e mantida como parametro explicito do
coletor, sem editar /etc/resolv.conf (compartilhado no Mininet padrao).
"""
import subprocess
import time


class GerenciadorCenarios:
    NOMES = ('normal', 'dns', 'rota', 'interface', 'acl', 'congestionamento')

    def __init__(self, net, dns_clientes):
        self.net = net
        self.dns_clientes = dns_clientes
        self._cenario = None
        self._carga = None

    def _cmd(self, host, comando):
        resultado = self.net.get(host).cmd(comando)
        return resultado

    def aplicar(self, nome):
        if nome not in self.NOMES:
            raise ValueError(f'Cenario desconhecido: {nome}')
        if self._cenario is not None:
            raise RuntimeError('Restaure o cenario anterior antes de continuar')
        self._cenario = nome
        try:
            if nome == 'dns':
                # DNS configurado incorretamente APENAS no perfil do cliente1.
                self.dns_clientes['client1'] = '192.168.20.99'
            elif nome == 'rota':
                self._cmd('client1', 'ip route del default via 192.168.10.1')
            elif nome == 'interface':
                self._cmd('client1', 'ip link set client1-eth0 down')
            elif nome == 'acl':
                saida = self._cmd('server',
                    'iptables -I INPUT 1 -s 192.168.10.2 -d 192.168.20.10 -p tcp --dport 80 -j DROP; echo ACL_RC:$?')
                if 'ACL_RC:0' not in saida:
                    raise RuntimeError(f'Nao foi possivel configurar ACL: {saida}')
            elif nome == 'congestionamento':
                # Requer o servidor iperf3 permanente já iniciado pelo runner.
                self._carga = self.net.get('client2').popen(
                    ['iperf3', '-c', '192.168.20.10', '-p', '5201',
                     '-t', '90', '-P', '2'],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                time.sleep(1)
                if self._carga.poll() is not None:
                    raise RuntimeError('A carga iperf3 nao iniciou; verifique o servidor')
        except Exception:
            self.restaurar()
            raise

    def restaurar(self):
        nome = self._cenario
        try:
            if nome == 'dns':
                self.dns_clientes['client1'] = '192.168.20.10'
            elif nome == 'rota':
                self._cmd('client1', 'ip route replace default via 192.168.10.1')
            elif nome == 'interface':
                self._cmd('client1', 'ip link set client1-eth0 up')
                self._cmd('client1', 'ip addr replace 192.168.10.2/24 dev client1-eth0')
                self._cmd('client1', 'ip route replace default via 192.168.10.1')
            elif nome == 'acl':
                self._cmd('server',
                    'iptables -D INPUT -s 192.168.10.2 -d 192.168.20.10 -p tcp --dport 80 -j DROP; echo ACL_DELETE_RC:$?')
        finally:
            if self._carga is not None:
                if self._carga.poll() is None:
                    self._carga.terminate()
                    try:
                        self._carga.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._carga.kill()
                        self._carga.wait()
                self._carga = None
            self._cenario = None


GABARITOS = {
    'normal': 'Nenhuma falha introduzida',
    'dns': 'Cliente1 consulta DNS incorreto 192.168.20.99 (perfil experimental)',
    'rota': 'Rota padrao removida de client1',
    'interface': 'Interface client1-eth0 desativada',
    'acl': 'Regra iptables bloqueia TCP/80 de client1 no servidor',
    'congestionamento': 'Dois fluxos TCP iperf3 concorrentes sobre enlace router1-server limitado',
}
