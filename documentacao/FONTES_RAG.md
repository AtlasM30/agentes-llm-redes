# Catálogo inicial de fontes técnicas para RAG

A lista é uma curadoria de referências técnicas; os documentos ainda **não foram coletados, segmentados ou indexados**. Verifique versão, permissões de reutilização, idioma e metadados antes da ingestão.

| Tema | Fonte recomendada | URL | Uso esperado |
|---|---|---|---|
| Topologia e isolamento | Mininet Walkthrough | https://mininet.org/walkthrough/ | namespaces, hosts virtuais, links TCLink, comandos e testes |
| Medições TCP | Documentação iperf3 (ESnet) | https://software.es.net/iperf/ | duração, vazão, timeout, saída JSON |
| DNS | dnsmasq manual | https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html | DNS local, parâmetros `--no-resolv`, `--address` e interfaces |
| Resolução DNS | BIND 9 `dig` manual | https://bind9.readthedocs.io/en/latest/manpages.html | consulta DNS e interpretação da resposta |
| Roteamento / interfaces | `iproute2` manual Linux | https://man7.org/linux/man-pages/man8/ip-route.8.html | tabelas de rotas, rota padrão e comandos de consulta |
| Regras de filtragem | `iptables` manual | https://man7.org/linux/man-pages/man8/iptables.8.html | cadeia INPUT, filtro por origem e porta |
| Controle de tráfego | `tc` manual | https://man7.org/linux/man-pages/man8/tc.8.html | latência/banda/fila e impacto nas medições |

Sugestão de metadados por trecho: `fonte_id`, `titulo`, `url`, `versao`, `data_acesso`, `tema`, `comandos_relevantes`, `licenca`, `trecho`, `escopo_de_uso`. Evite adicionar comandos de alteração de rede como autorização de execução: o validador determinístico precisa decidir independentemente.

**Separação obrigatória:** `dados/gabaritos/causas_reais.json` deve permanecer inacessível para o agente de diagnóstico. Os logs de treinamento/teste devem ser anonimizados ou identificados por IDs neutros e não podem conter o rótulo da falha em metadados acessíveis ao agente.
