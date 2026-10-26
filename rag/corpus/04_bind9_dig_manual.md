# Manual BIND 9 dig(1) — Consultas e Diagnostico de Resolucao DNS

## Sinopse e Opcoes de Consulta Controlada
O utilitario `dig` (*domain information groper*, BIND 9.18) interroga servidores de nomes DNS e exibe respostas detalhadas ou resumidas para depuracao. A sinopse segura recomendada para testes diagnosticos automatizados e:
```text
dig @<servidor_dns> <dominio> A +time=<segundos> +tries=<tentativas> +short
```
Significado dos parametros principais segundo `dig(1)`:
- `@<servidor_dns>`: direciona a consulta explicitamente ao endereco IP informado (ex.: `@192.168.20.10` ou ao DNS configurado no perfil do cliente), contornando `/etc/resolv.conf`.
- `A`: solicita especificamente o registro de endereco IPv4 associado ao nome de dominio (`app.lab.local`).
- `+time=2` (ou `+time=1`): define o tempo limite de espera por tentativa em segundos (padrao do `dig` seria 5s, excessivo para testes rapidos).
- `+tries=1` (ou `+tries=2`): limita o numero de tentativas UDP, evitando bloqueio prolongado quando o servidor de destino nao responde.
- `+short`: imprime apenas o valor final da resposta (por exemplo, `192.168.20.10`) em caso de sucesso, facilitando analise programatica.

## Interpretacao de Saidas, Erros e Codigos de Retorno
- **Resolucao bem-sucedida (`codigo_retorno == 0` e IP esperado na saida)**: `dig +short` retorna `192.168.20.10`. Confirma tanto o transporte IP/UDP ate a porta 53 do servidor DNS quanto a presenca do registro `A`.
- **Timeout / Servidor DNS inalcancavel (`codigo_retorno == 9` ou mensagem `communications error` / `connection timed out; no servers could be reached`)**: nenhum servidor respondeu no IP consultado dentro de `+time`. Isso ocorre quando:
  1. O cliente nao possui conectividade IP alguma (interface `DOWN` ou rota ausente — nesses casos, o `ping` para `192.168.20.10` tambem falha!); ou
  2. A conectividade IP esta integra (`ping` funciona), mas o IP do servidor DNS configurado para o cliente esta incorreto/inexistente (ex.: `192.168.20.99`) ou filtrando a porta 53.
- **Resposta vazia ou NXDOMAIN (`codigo_retorno == 0`, saida vazia no `+short`)**: o servidor DNS respondeu, mas nao conhece o nome consultado.

## Regra Fundamental de Eliminacao Causal (Conectividade vs DNS)
Uma falha na resolucao DNS **jamais** deve ser classificada isoladamente como `problema_dns` sem antes verificar o estado da interface, a tabela de rotas e a conectividade IP (`ping`):
- Se a interface estiver `DOWN` ou a rota padrao estiver ausente, o `dig` falhara como efeito secundario da perda de conectividade IP. A causa raiz nesses casos e `falha_de_interface` ou `falha_de_roteamento`.
- Somente quando a conectividade IP com a sub-rede do servidor estiver comprovadamente funcional (`ping` com sucesso) e a resolucao DNS falhar (ou retornar endereco incorreto) caracteriza-se `problema_dns`.

## Seguranca nas Consultas DNS
O validador deterministico deve restringir consultas `dig` aos tipos `A` ou `AAAA` para dominios internos autorizados (`app.lab.local`) e servidores dentro do enderecamento do laboratorio (`192.168.10.0/24` e `192.168.20.0/24`). Consultas de transferencia de zona (`AXFR`, `IXFR`), consultas amplificadoras (`ANY`) e consultas para resolvedores publicos externos (como `8.8.8.8` ou `1.1.1.1`) sao proibidas.
