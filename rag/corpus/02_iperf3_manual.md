# Documentacao Tecnica iperf3 (ESnet) — Medicao de Vazao e Desempenho TCP

## Visao Geral e Funcionamento Cliente-Servidor
O `iperf3` e uma ferramenta de medicao ativa da vazao maxima alcancavel em redes IP (TCP, UDP e SCTP). A ferramenta exige um processo servidor escutando em uma porta especifica (`iperf3 -s -B <ip> -p <porta>`) e um cliente gerando trafego de teste (`iperf3 -c <destino> -p <porta> -t <segundos> -J`). Em ambientes de laboratorio controlado, recomenda-se separar a porta de geracao de carga concorrente (ex.: TCP/5201) da porta dedicada a sondas curtas de diagnostico (ex.: TCP/5202), evitando recusa de conexao porque cada instancia `iperf3 -s` atende apenas um teste ativo por vez.

## Sintaxe de Sonda Segura e Saida Estruturada JSON
Para diagnostico seguro sem sobrecarregar prolongadamente a rede, a execucao cliente deve restringir a duracao (`-t`) entre 1 e 5 segundos, utilizar protocolo TCP padrao com apenas um fluxo (`-P 1` implicito) e solicitar saida estruturada com `-J` (`--json`):
```text
iperf3 -c 192.168.20.10 -p 5202 -t 3 -J
```
Na estrutura JSON retornada pelo `iperf3`, o indicador primario de vazao efetivamente entregue ao receptor encontra-se no caminho:
- `end.sum_received.bits_per_second`: taxa media recebida no destino em bits por segundo. Para converter para Megabits por segundo (Mbps), divide-se `bits_per_second` por `1_000_000`.
- `end.sum_sent.retransmits`: numero de retransmissoes de segmentos TCP durante o intervalo de medicao, util como sinal complementar de perda ou saturacao de fila.

## Interpretacao de Resultados sob Congestionamento e Timeouts
Em um enlace configurado a 10 Mbps sem trafego concorrente, uma sonda TCP individual atinge tipicamente cerca de 9,3 Mbps a 9,5 Mbps (descontados os cabecalhos Ethernet, IPv4 e TCP). Quando ha congestionamento severo causado por multiplos fluxos TCP concorrentes disputando o mesmo gargalo:
1. A vazao medida pela sonda cai drasticamente (por exemplo, para menos de 1 a 3 Mbps, representando reducao superior a 70%–90%).
2. O handshake ou encerramento de controle do `iperf3` pode sofrer atraso extremo na fila e atingir timeout (`TimeoutExpired` ou erro de conexao do canal de controle TCP). Um timeout da sonda durante conectividade ICMP funcional (com RTT elevado) nao deve ser confundido com falha fisica de interface: trata-se de sintoma compativel com saturacao severa do enlace.

## Restricoes de Seguranca e Controle de Volume de Trafego
Por ser um teste ativo gerador de carga, o uso de `iperf3` por sistemas automatizados exige limites rigorosos de validacao deterministica:
- Duracao maxima estrita (`-t` limitado a no maximo 5 segundos) para impedir saturacao persistente.
- Proibicao de multiplos fluxos paralelos (`-P > 1`) e proibicao de modo UDP irrestrito (`-u`, `-b`), que poderiam provocar negacao de servico (DoS) no enlace virtual.
- Caso uma politica operacional restritiva bloqueie a execucao de `iperf3` para preservar a rede, o diagnostico de possivel congestionamento deve apoiar-se nas medicoes passivas/leves permitidas, como a elevacao expressiva da latencia media de `ping` em relacao a linha de base e estatisticas de fila em `tc -s qdisc show` ou `ip -s link`.
