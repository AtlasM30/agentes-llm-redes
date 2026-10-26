# Manual Linux iptables(8) — Filtragem de Pacotes IPv4 e Listas de Controle de Acesso (ACL)

## Inspecao de Regras de Filtragem com iptables -S
O utilitario `iptables` (versao 1.8.10 sobre `nf_tables`) inspeciona e administra tabelas de filtragem de pacotes IPv4 no kernel Linux. Para diagnostico seguro e deterministico sem risco de atraso por resolucao DNS reversa, utiliza-se na tabela `filter` padrao o comando somente leitura:
```text
iptables -S
```
O parametro `-S` (`--list-rules`) imprime todas as politicas padrao e regras ativas exatamente no formato de especificacao do `iptables`:
```text
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
-A INPUT -s 192.168.10.2/32 -d 192.168.20.10/32 -p tcp -m tcp --dport 80 -j DROP
```
Elementos de uma regra de bloqueio na cadeia `INPUT` do servidor:
- `-P INPUT ACCEPT`: politica padrao permissiva para pacotes destinados ao proprio host quando nenhuma regra anterior casa.
- `-A INPUT`: regra anexada na cadeia de entrada de pacotes destinados ao servidor.
- `-s 192.168.10.2/32`: filtra pacotes cuja origem IPv4 seja especificamente `client1` (`192.168.10.2`).
- `-d 192.168.20.10/32`: filtra pacotes destinados ao IP do `server`.
- `-p tcp` e `--dport 80`: restringe a correspondencia exclusivamente ao protocolo TCP na porta 80 (servico HTTP).
- `-j DROP` ou `-j REJECT`: descarta silenciosamente (`DROP`, causando timeout em `curl`) ou rejeita ativamente (`REJECT`, causando `Connection refused` em `curl`) a conexao TCP.

## Assinatura Sintomatica de Bloqueio por ACL vs Indisponibilidade HTTP
Quando existe no servidor uma regra `INPUT` bloqueando `TCP/80` seletivamente para `192.168.10.2` (`client1`):
1. **Conectividade IP (`ping`) de `client1` funciona**: pacotes ICMP Echo Request/Reply nao casam com `-p tcp --dport 80` e sao aceitos.
2. **Resolucao DNS (`dig`) de `client1` funciona**: consultas DNS utilizam UDP/53 (ou TCP/53), nao afetadas pela regra da porta 80.
3. **Teste HTTP (`curl http://192.168.20.10/`) a partir de `client1` falha**: retorna timeout (`codigo_retorno` 28 no `curl` sob `DROP`) ou recusa de conexao (`codigo_retorno` 7 sob `REJECT`), com `servico_disponivel = False`.
4. **Teste HTTP a partir de `client2` (`192.168.10.3`) funciona normalmente (HTTP 200)**: comprova que o processo servidor HTTP na porta 80 esta ativo e saudavel!

## Raciocinio sob Restricao de Visibilidade (Quando iptables -S nao esta acessivel)
Em ambientes onde a politica de seguranca nao autoriza o agente a inspecionar `iptables -S` diretamente no servidor:
- O agente pode comparar o teste HTTP de `client1` (falho, com `ping` e `dig` funcionais) com o teste HTTP de `client2` (sucesso HTTP 200).
- Entretanto, sem a evidencia direta da regra `iptables` na cadeia `INPUT`, o agente deve manter rigor epistemico: caso nao haja confirmacao direta da regra ACL, deve indicar `problema_http_ou_bloqueio` com confianca indicativa (ou apontar a forte suspeita de filtragem seletiva por origem documentando a limitacao de permissao de leitura da ACL).
- Quando `iptables -S` no servidor confirma a regra `-p tcp --dport 80 -j DROP/REJECT` para `192.168.10.2`, confirma-se `bloqueio_acl` com confianca alta.

## Proibicao de Alteracao de Firewall pelo Agente
Flags administrativas que alteram o estado do Netfilter (`-A`, `-I`, `-D`, `-R`, `-F`, `-Z`, `-N`, `-X`, `-P`) sao estritamente proibidas ao agente. Diante de `bloqueio_acl` confirmado, o agente deve recomendar ao administrador humano revisar a politica de acesso e remover especificamente a regra indevida no servidor (ex.: `iptables -D INPUT -s 192.168.10.2 -d 192.168.20.10 -p tcp --dport 80 -j DROP`).
