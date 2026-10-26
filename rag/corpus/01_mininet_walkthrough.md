# Mininet Walkthrough e Isolamento por Namespaces de Rede

## Arquitetura de Emulacao e Isolamento de Hosts
O Mininet cria topologias virtuais em um unico kernel Linux empregando namespaces de rede (`network namespaces`) leves e pares de interfaces virtuais Ethernet (`veth pairs`). Cada host virtual (como `client1`, `client2`, `router1` e `server`) possui sua propria pilha TCP/IP independente: interfaces de rede exclusivas (ex.: `client1-eth0`), enderecos IPv4 proprios, tabela ARP, tabela de roteamento IPv4 e regras locais de filtragem `iptables`.

Diferentemente de maquinas virtuais completas, hosts Mininet no modo padrao compartilham o sistema de arquivos raiz (`mount namespace`) com o sistema operacional hospedeiro. Por essa razao, arquivos globais como `/etc/resolv.conf` sao compartilhados entre os hosts e a maquina virtual Ubuntu: alterar `/etc/resolv.conf` diretamente dentro de um host Mininet modificaria a resolucao de nomes do proprio sistema hospedeiro. Em diagnosticos controlados de DNS, consultas explicitas direcionadas via `dig @<servidor_dns>` permitem avaliar o resolvedor de perfil do cliente sem alterar arquivos do sistema.

## Topologia em Camadas, Switch Standalone e Roteamento IPv4
Em uma topologia segmentada em duas sub-redes IPv4 conectadas por um roteador Linux:
- Os clientes na sub-rede de acesso (ex.: `192.168.10.0/24`) conectam-se a um switch Open vSwitch (`OVSSwitch`) configurado com `failMode='standalone'`. No modo `standalone`, o switch opera como comutador Ethernet de camada 2 tradicional com aprendizado automatico de enderecos MAC, sem depender de controlador OpenFlow externo.
- O roteador (`router1`) possui interfaces nas duas sub-redes (ex.: `router1-eth0` em `192.168.10.1/24` e `router1-eth1` em `192.168.20.1/24`) e encaminha pacotes IPv4 quando o parametro de kernel `net.ipv4.ip_forward=1` esta ativo.
- Para que um cliente em `192.168.10.0/24` alcance um servidor em `192.168.20.0/24` (`192.168.20.10`), tres pre-requisitos de camadas inferiores precisam estar integros: (1) interface fisica/virtual do cliente ativa (`UP`), (2) rota padrao (`default via 192.168.10.1`) ou rota especifica para `192.168.20.0/24` presente na tabela de rotas do cliente, e (3) rota de retorno no servidor (`default via 192.168.20.1`).

## Enlaces TCLink e Parametros de Banda e Atraso
O componente `TCLink` do Mininet utiliza `tc` (Traffic Control) do Linux sob as interfaces virtuais para emular restricoes realistas de enlace:
- `bw` (bandwidth): limita a taxa maxima de transmissao em Mbps (por exemplo, `bw=10` limita o enlace a 10 Mbps usando modeladores HTB/TBF).
- `delay`: adiciona atraso unidirecional por meio do modulo `netem` (por exemplo, `delay='10ms'` em cada sentido resulta em um RTT minimo basal de aproximadamente 20 ms a 35 ms em repouso, somando o processamento virtual).
Quando fluxos TCP intensivos disputam um enlace `TCLink` limitado a 10 Mbps, os buffers das filas `qdisc` enchem rapidamente, elevando o RTT medido por `ping` para centenas de milissegundos mesmo sem perda imediata de pacotes ICMP.

## Limites de Seguranca em Testes no Mininet
Operacoes de diagnostico executadas por agentes automatizados em hosts Mininet devem ser estritamente nao destrutivas e limitadas aos dispositivos da topologia (`client1`, `client2`, `router1`, `server`). Comandos que alterem estado de enlaces (`ip link set ... down`), modifiquem tabelas de rotas (`ip route del/add`), alterem regras de firewall (`iptables -I/-D/-F`) ou encerrem processos (`kill`, `killall`) nao constituem testes diagnosticos e devem permanecer exclusivos do administrador humano do laboratorio.
