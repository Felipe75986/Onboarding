# DHCP Automation — Refactor

## Contexto

O script de produção original (`ipmi_unifiedv3.py`, 1017 linhas) foi substituído por um
package Python estruturado que espelha a arquitetura do `Onboarding_Automation/`.

### Problemas resolvidos no v3

| # | Problema | Solução |
|---|---|---|
| 1 | 5 credenciais hardcoded no topo do módulo | Todas as secrets lidas exclusivamente de `RD_OPTION_*` |
| 2 | `option = "individual"` hardcoded na linha 983 (ignorava `RD_OPTION_TESTE`) | `RD_OPTION_MODE=chassis|individual` lido e validado em `inputs.py` |
| 3 | `process_chassis()` e `process_individual()` com ~80% de código duplicado | Deduplicado em `orchestrator.py` com funções `_run_chassis` e `_run_individual` |
| 4 | CSV parsing por `Unnamed: 37` — quebrava a cada coluna inserida | `column_resolver.py` busca por nome+alias, sobrevive a colunas extras e reordenação |
| 5 | Nomes de arquivo CSV hardcoded no topo do módulo | Passados via `RD_FILE_ONBOARDING_CSV` / `RD_FILE_DELIVERY_CSV` |
| 6 | 6 scripts legados ao redor (`ipmi_unified.py`, `ipmi_chassis.py`, etc.) | Movidos para `.archived/` — fora do `PYTHONPATH` ativo, histórico Git preservado |
| 7 | Sem backup do `dhcpd.conf` antes de sobrescrever | Backup automático `dhcpd.conf.bak.<utc-timestamp>` antes de qualquer mudança |

### O que foi mantido igual ao v3

- Comportamento de **sobrescrita total** do `dhcpd.conf` (não append)
- SSH via paramiko com senha passada por stdin (`sudo -S`)
- Os dois modos de operação: chassis e individual
- Coleta de MACs via netmiko (`show mac address-table interface ethernet1/<port>`)
- Restart do `isc-dhcp-server` após aplicar config

### O que foi removido (fora de escopo)

- Coleta Redfish/serial pós-DHCP (`collect_serials_from_ipmis`, `validate_ips_with_ping`)
- `generate_mapping_report()` — substituído por log estruturado JSONL

---

## Estrutura de arquivos

```
DHCP_Automation/
├── run_dhcp.py                         # Entrypoint (~40 LOC) — wira config → orchestrator
├── dhcp_provisioning/
│   ├── __init__.py
│   ├── exceptions.py                   # Hierarquia de erros: DhcpError, ConfigError,
│   │                                   #   MacCollectionError, DhcpApplyError
│   ├── config.py                       # DhcpConfig dataclass + load_config() + create_session()
│   ├── inputs.py                       # DhcpInputs dataclass + parse_inputs() — valida RD_OPTION_*
│   ├── column_resolver.py              # Detecção de header por âncora + lookup por alias
│   ├── csv_parser.py                   # parse_onboarding_csv() + parse_delivery_csv()
│   ├── netbox_lookup.py                # get_switch_info() — resolve label → IP + OS via NetBox
│   ├── switch_client.py                # collect_macs_for_port() — netmiko, Nexus + IOS
│   ├── dhcp_writer.py                  # format_mac() + generate_entries() — funções puras
│   ├── dhcp_apply.py                   # apply_to_server() — backup, dhcpd -t, mv, restart
│   └── orchestrator.py                 # run() — dispatch de modo, fluxo principal
└── .archived/                          # Scripts legados preservados pra referência
    ├── ipmi_unifiedv3.py               # Script original de produção
    ├── ipmi_unified.py
    ├── ipmi_individual.py
    ├── ipmi_chassis.py
    ├── redfish.py
    ├── dhcp_helper.py
    ├── dhcp_helper_backup.py
    ├── balskna.py
    └── cwbw8ue.py
```

---

## Módulos — responsabilidades

### `exceptions.py`

Hierarquia de erros para separar categoria de falha:

```
DhcpError (base)
├── ConfigError          — var de ambiente ausente / valor inválido
├── MacCollectionError   — falha ao parsear CSV ou coletar MAC no switch
└── DhcpApplyError       — falha SSH, validação dhcpd -t, restart, etc.
```

### `config.py`

Carrega as variáveis de ambiente obrigatórias e retorna um `DhcpConfig` frozen dataclass.

- Acumula **todos** os campos faltando antes de levantar `ConfigError` (o operador vê todos os
  problemas de uma vez).
- Importa `BASE_URL` de `Onboarding_Automation/netbox_onboarding/config.py` via `sys.path` —
  nunca duplica a constante de URL do NetBox sandbox.
- `create_session()` configura retry (5 tentativas, backoff exponencial) e desabilita avisos SSL.

### `inputs.py`

Valida os inputs de execução (modo, paths de CSV, rack, RU) e faz cross-validation:
- Modo `chassis` exige `RD_FILE_ONBOARDING_CSV`
- Modo `individual` exige `RD_FILE_DELIVERY_CSV` + credenciais de switch
- Acumula todos os erros antes de levantar (mesma regra do `config.py`)

### `column_resolver.py`

Resolve colunas da planilha **por nome**, não por posição. Composto por quatro funções puras:

| Função | O que faz |
|---|---|
| `normalize(text)` | Lowercase, `\n` → espaço, colapsa whitespace — normaliza variações de header |
| `find_header_row(df, anchors)` | Varre as primeiras 20 linhas procurando uma âncora (ex: "Deployment name") |
| `build_header_map(df, row)` | Retorna `{header_normalizado: col_index}` |
| `find_column(headers, *aliases)` | Primeira alias que bater no mapa vence. Erro claro se nenhuma bater |
| `find_metadata(df, label_aliases, offset)` | Acha célula de metadado por label (ex: "White Cable") e retorna o valor no offset |

**Resiliência:** coluna extra inserida no meio da planilha → o resolver reacha todas as colunas
pelo nome, sem quebrar. Testado em produção contra o CSV do ASH2 com coluna inserida na posição 5.

### `csv_parser.py`

Dois parsers, um por modo:

**`parse_onboarding_csv(path)` — modo chassis**
- Lê o CSV de Onboarding
- Localiza o header row pela âncora `"Deployment name"` / `"Server Name"`
- Extrai `(server_name, mac, ip)` de cada linha de device
- Pula linhas sem MAC **ou** sem IP (device ainda não preenchido pelo operador)
- Retorna `list[MacIpRow]`

**`parse_delivery_csv(path)` — modo individual**
- Lê o CSV de Delivery
- Extrai o switch IPMI do bloco de metadados "White Cable" no topo da planilha
  (label NetBox + RU — ex: `SWACC63-ASH2`, `RU 34~35`)
- Localiza o header de seção pela âncora `"IPMI (White)"` / `"IPMI Cable"`
- Extrai `(server_name, switch, port, ip)` de cada linha de device
- MAC não é extraído — individual mode descobre o MAC via SSH no switch em runtime
- Retorna `list[DeliveryEntry]`

### `netbox_lookup.py`

`get_switch_info(session, token, url_api, label) → SwitchInfo`

- Consulta `GET /api/dcim/devices/?name=<label>` no NetBox
- Extrai `primary_ip4.address` → `host` (sem a máscara)
- Determina OS pelo nome do device type / fabricante:
  - `"nexus"` no fabricante ou modelo → `cisco_nxos`
  - Qualquer outro → `cisco_ios`
- Levanta `MacCollectionError` se o device não existe ou não tem IP primário

### `switch_client.py`

`collect_macs_for_port(host, device_os, port, username, password, secret) → list[str]`

- Conecta via netmiko (`ConnectHandler`) com timeouts de 120s
- **Nexus:** `show mac address-table interface ethernet1/<port>` (sem enable)
- **IOS:** entra em enable mode primeiro, depois `show mac address interface ethernet1/<port>`
- Extrai MACs com regex `[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}` (formato Cisco dot)
- Levanta `MacCollectionError` se nenhum MAC for encontrado na porta

### `dhcp_writer.py`

Funções puras, sem I/O:

- `format_mac(mac_cisco)` — converte `905a.0818.5214` → `90:5A:08:18:52:14`
- `generate_entries(rows, rack, ru)` — gera blocos `host { hardware ethernet ...; fixed-address ...; }`

Exemplo de saída:
```
host 01.03_22-32_1 {
    hardware ethernet 90:5A:08:18:52:14;
    fixed-address 10.106.59.7;
}

host 01.03_22-32_2 {
    hardware ethernet 90:5A:08:18:52:15;
    fixed-address 10.106.59.9;
}
```

### `dhcp_apply.py`

`apply_to_server(content, host, user, password) → (True, message)`

Aplica a config no servidor DHCP remoto via SSH (paramiko). Levanta `DhcpApplyError` em
qualquer passo que falhe.

**Sequência de operações (all-or-nothing):**

```
1. SSH connect (paramiko, timeout 30s)
2. sudo cp dhcpd.conf → dhcpd.conf.bak.<YYYYMMDDTHHMMSSZ>   ← NOVO (v3 não tinha)
3. cat /etc/dhcp/dhcpd.conf.template                         ← fallback para config base embutida
4. Monta: template + "# Last updated: <iso-ts>" + entries
5. sudo tee /etc/dhcp/dhcpd.conf.new                         ← arquivo temporário
6. sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf.new               ← valida ANTES de tocar o conf ativo
   └── se falhar: rm dhcpd.conf.new, dhcpd.conf original intacto, raise DhcpApplyError
7. sudo mv dhcpd.conf.new → dhcpd.conf                       ← SOBRESCREVE completamente
8. sudo systemctl restart isc-dhcp-server
9. sudo systemctl is-active isc-dhcp-server                  ← verifica "active"
```

**Sobre a sobrescrita:** o comportamento é idêntico ao v3 — o arquivo é **completamente
substituído** (não há append). A config final é `template + entries geradas`. O DHCP server é
dedicado IPMI, então sobrescrita total é o comportamento correto.

**Sobre o backup:** antes de qualquer mudança, `dhcpd.conf` é copiado para
`dhcpd.conf.bak.<timestamp-utc>`. Se a run falhar após o `mv`, o operador tem o arquivo original
no backup para restaurar manualmente.

**Limitação conhecida:** sudo via senha em stdin (`sudo -S`) — herdado do v3. Melhoria futura:
SSH key + NOPASSWD no `/etc/sudoers` do DHCP server.

### `orchestrator.py`

`run(config, inputs, logger) → None`

Despacha para o modo correto e executa o fluxo principal:

```
chassis mode:
  parse_onboarding_csv(onboarding_csv)
  → list[MacIpRow]

individual mode:
  parse_delivery_csv(delivery_csv)
  → para cada switch único: get_switch_info(session, label)
  → para cada device: collect_macs_for_port(switch_host, port)
  → list[MacIpRow]

(ambos os modos convergem aqui)
generate_entries(rows, rack, ru) → str
apply_to_server(content, dhcp_host, user, pass)
```

### `run_dhcp.py`

Entrypoint fino (~40 LOC). Não contém lógica de negócio:

```
load_config()       → DhcpConfig   (falha rápido com ConfigError)
parse_inputs()      → DhcpInputs   (falha rápido com ConfigError)
FileLogger(...)
orchestrator.run()
sys.exit(0 | 1)
```

---

## Variáveis de ambiente

| Variável | Obrigatória | Modo | Descrição |
|---|---|---|---|
| `RD_OPTION_MODE` | sim | ambos | `chassis` ou `individual` |
| `RD_OPTION_RACK_NAME` | sim | ambos | Nome do rack (ex: `01.03`) |
| `RD_OPTION_RU_POSITION` | sim | ambos | Posição RU (ex: `22~32`) |
| `RD_OPTION_NETBOXTOKEN` | sim | ambos | Token de API do NetBox |
| `RD_OPTION_DHCP_SERVER_HOST` | sim | ambos | IP do servidor DHCP |
| `RD_OPTION_DHCP_SERVER_USER` | sim | ambos | Usuário SSH do DHCP server |
| `RD_OPTION_DHCP_SERVER_PASSWORD` | sim | ambos | Senha SSH do DHCP server |
| `RD_FILE_ONBOARDING_CSV` | chassis | chassis | Path do CSV de Onboarding (upload Rundeck) |
| `RD_FILE_DELIVERY_CSV` | individual | individual | Path do CSV de Delivery (upload Rundeck) |
| `RD_OPTION_SWITCH_USERNAME` | individual | individual | Usuário SSH do switch |
| `RD_OPTION_SWITCH_PASSWORD` | individual | individual | Senha SSH do switch |
| `RD_OPTION_SWITCH_SECRET` | individual | individual | Enable secret (Cisco IOS) |

Inputs sensíveis devem usar `secure: true` no job Rundeck. **Nenhum valor de credencial é
logado ou impresso** — o código valida presença mas nunca printa o valor.

---

## Como executar

```bash
# A partir do root do repositório
cd DHCP_Automation

# Modo chassis
export RD_OPTION_MODE=chassis
export RD_FILE_ONBOARDING_CSV=/path/to/Onboarding.csv
export RD_OPTION_RACK_NAME=01.03
export RD_OPTION_RU_POSITION=22-32
export RD_OPTION_NETBOXTOKEN=<token>
export RD_OPTION_DHCP_SERVER_HOST=<ip>
export RD_OPTION_DHCP_SERVER_USER=ubuntu
export RD_OPTION_DHCP_SERVER_PASSWORD=<senha>
python run_dhcp.py

# Modo individual (adicionar ao chassis)
export RD_OPTION_MODE=individual
export RD_FILE_DELIVERY_CSV=/path/to/Delivery.csv
export RD_OPTION_SWITCH_USERNAME=<usuario>
export RD_OPTION_SWITCH_PASSWORD=<senha>
export RD_OPTION_SWITCH_SECRET=<enable-secret>   # só se IOS
python run_dhcp.py
```

---

## Diferenças entre os modos

| | Chassis | Individual |
|---|---|---|
| **CSV usado** | Onboarding (tem MAC preenchido) | Delivery (tem porta do switch) |
| **Como obtém o MAC** | Lê diretamente do CSV | SSH no switch → `show mac address-table interface ethernet1/<port>` |
| **Quando usar** | MACs já disponíveis na planilha de Onboarding | MACs desconhecidos — switch ainda não descoberto |
| **Depende do switch** | Não | Sim (NetBox lookup + SSH netmiko) |

---

## Testes locais realizados

Todos passaram sem infra externa:

| Teste | Resultado |
|---|---|
| Import chain completa do package | OK |
| `load_config` sem env vars | `ConfigError` listando todas as vars faltando |
| `parse_inputs` com mode inválido | Acumula todos os erros antes de raise |
| `parse_inputs` chassis sem CSV | Erro claro |
| `parse_inputs` individual sem switch creds | Erros acumulados |
| `parse_delivery_csv` contra CSV real ASH2 | 10 servidores, switch/porta/IP corretos |
| `parse_onboarding_csv` ASH2 (MACs vazios) | 0 rows — comportamento esperado |
| `format_mac` + `generate_entries` | Formato dhcpd.conf correto |
| Coluna extra inserida na posição 5 do CSV | `column_resolver` achou `MAC Address BMC` deslocado |
| Secrets leak check | Nenhum valor de credencial no output |

---

## Testes de integração pendentes

Requerem acesso à infra de lab:

1. **Smoke chassis mode** — CSV de Onboarding com MACs preenchidos, verificar backup criado,
   `dhcpd -t` passou, conf sobrescrito, serviço ativo.

2. **Smoke individual mode** — CSV de Delivery, verificar que busca o switch certo no NetBox,
   coleta MACs via SSH, gera entries idênticas ao chassis para o mesmo conjunto de servidores.

3. **Falha de validação dhcpd** — CSV malformado que gera conf inválido → confirmar que o
   backup existe, o `dhcpd.conf` original foi preservado, exit 1.

4. **Verificação de backup no servidor:**
   ```bash
   ssh <dhcp-server> ls -la /etc/dhcp/dhcpd.conf.bak.*
   ```

5. **Verificação do serviço após restart:**
   ```bash
   ssh <dhcp-server> systemctl is-active isc-dhcp-server
   ```

---

## Commits do refactor

```
e8181ee feat(dhcp): add netbox_lookup, switch_client, dhcp_writer, dhcp_apply, orchestrator, run_dhcp
3a8a0a1 feat(dhcp): add csv_parser for chassis + individual modes
3cbd4df feat(dhcp): add column_resolver for header-based CSV column lookup
ef43e8f feat(dhcp): add config + inputs loaders with env-var validation
0d12c57 feat(dhcp): add dhcp_provisioning package skeleton
f474b71 chore(dhcp): add Claude rules for security and testing
f5c49b5 chore(dhcp): archive 9 legacy IPMI/DHCP scripts
```
