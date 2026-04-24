# Refatoracao: old_netbox_onboarding.py -> netbox_onboarding/

**Data:** 2026-04-02
**Autor:** Felipe Gomes + Claude
**Arquivo original:** `old_netbox_onboarding.py` (680 linhas, script monolitico)

---

## 1. Modularizacao em pacote Python

### O que foi feito
O script monolitico `old_netbox_onboarding.py` foi decomposto em 8 modulos dentro de um pacote `netbox_onboarding/`:

```
netbox_onboarding/
    __init__.py        # Exporta run()
    config.py          # Configuracao e sessao HTTP
    client.py          # Cliente generico da API NetBox
    cache.py           # Cache de dados de referencia
    spreadsheet.py     # Parsing do CSV com pandas
    validators.py      # Validacao de tipos e payloads
    devices.py         # Criacao de devices, interfaces, IPs
    networking.py      # VLANs, prefixes, gateways
    orchestrator.py    # Fluxo principal
run_onboarding.py      # Entry point
```

### Motivacao
- O script original misturava configuracao, comunicacao HTTP, parsing de CSV, logica de negocio e orquestracao em um unico arquivo
- Dificultava manutencao: qualquer mudanca exigia entender o arquivo inteiro
- Impossibilitava reutilizacao: funcoes como o cliente HTTP ou o cache nao podiam ser usados por outros scripts do projeto
- A separacao por responsabilidade permite que cada modulo seja entendido, testado e modificado de forma independente

---

## 2. Substituicao de csv por pandas

### O que foi feito
- Removido o uso de `csv.reader` no modulo `spreadsheet.py`
- Implementado `pd.read_csv()` com `header=None`, `dtype=str` e `keep_default_na=False`
- O CSV agora e lido uma unica vez (antes eram duas aberturas de arquivo)
- Stripping de whitespace feito em massa com `df.apply(lambda col: col.str.strip())`
- Linhas vazias filtradas com operacao vetorial do pandas

### Motivacao
- O codigo original abria o CSV duas vezes: uma para metadata (linhas 0-7), outra para devices (linhas 8+)
- `dtype=str` previne que pandas converta IPs, VLANs ou seriais em floats
- `keep_default_na=False` evita que celulas vazias virem NaN, mantendo o comportamento de `.strip()` do original


---

## 3. Integracao do FileLogger (JSONL estruturado)

### O que foi feito
- Todos os `print()` do script original foram substituidos por chamadas ao `FileLogger` existente (`file_logger.py`)
- Metodos usados: `logger.info()`, `logger.warn()`, `logger.error()`, `logger.debug()`
- Cada log inclui campos estruturados via `**kwargs` (ex: `device=name`, `endpoint=ep`, `status=code`)
- O logger e inicializado no `orchestrator.py` e passado como parametro para todos os modulos
- Logs gravados em `logs/YYYY-MM-DD_system.log` no formato JSONL (um JSON por linha)

### Motivacao
- `print()` nao e rastreavel: sem timestamp, sem nivel, sem campos estruturados
- Logs JSONL sao compativeis com Grafana, Loki e Elasticsearch para monitoramento em producao
- Campos estruturados permitem queries como `level="ERROR" AND device="server-01"`
- O `FileLogger` ja existia no projeto mas nao era utilizado pelo script de onboarding
- Zero saida no console: toda informacao vai para arquivo, adequado para execucao via Rundeck

---

## 4. Cliente HTTP generico (`client.py`)

### O que foi feito
- Classe `NetboxClient` com metodos: `get()` (paginado), `get_single()`, `create()`, `update()`, `bulk_create()`
- Headers HTTP montados uma unica vez no `__init__` e reutilizados
- Excecoes customizadas: `NetboxAPIError`, `ValidationError`, `SpreadsheetError`
- Erros HTTP logados com body completo da resposta antes de levantar excecao

### Motivacao
- O codigo original recriava o dict de headers em cada funcao (6 vezes no total)
- As 4 funcoes de API (`get_netbox_data`, `create_netbox_data`, `update_netbox_data`, `get_single_device`) tinham logica duplicada de tratamento de erros
- Um cliente generico centraliza a comunicacao HTTP e pode ser reutilizado por outros scripts
- Excecoes customizadas permitem tratamento diferenciado (ex: retry em 429 vs abort em 400)

---

## 5. Cache com warm-up paralelo (`cache.py`)

### O que foi feito
- Classe `NetboxCache` com cache de: device types, device roles, platforms, sites, VLAN groups, VLANs
- Metodo `warm_up()` busca os 4 endpoints de tipos em paralelo usando `ThreadPoolExecutor(max_workers=4)`
- Properties com lazy loading: so buscam da API se o cache estiver vazio
- Cache de VLANs por group_id com `force_refresh` para invalidacao apos criacao

### Motivacao
- O codigo original buscava device types, roles, platforms e sites sequencialmente em `get_netbox_types()` — 4 chamadas HTTP esperando uma pela outra
- O warm-up paralelo reduz o tempo de inicializacao em ~3-4 segundos
- O `NetboxCache` original so cacheava VLAN groups e VLANs; os tipos eram buscados toda vez que `types_validation()` era chamada
- O cache de tipos evita chamadas redundantes a API quando o script roda para multiplos devices

---

## 6. Dataclasses tipadas (`spreadsheet.py`)

### O que foi feito
- Criadas dataclasses: `ChassisInfo`, `DeviceInfo`, `SpreadsheetData`
- Cada campo tem tipo explicito (str, int, etc.)
- Substituem os dicts genericos (`devices_temp = {...}`) usados no original

### Motivacao
- Dicts genericos nao oferecem autocomplete nem deteccao de erros em tempo de desenvolvimento
- Um typo como `device["devie_type"]` passaria silencioso com dict; com dataclass, levanta `AttributeError`
- Dataclasses documentam o formato esperado dos dados sem necessidade de comentarios

---

## 7. Validacao com coleta completa de erros (`validators.py`)

### O que foi feito
- Funcao `validate_and_resolve()` retorna `ValidationResult` com: `valid_devices`, `chassis_payload`, `site_id`, `errors`
- Valida TODOS os devices antes de retornar, coletando todos os erros
- Cada erro inclui o nome do device e qual campo especifico falhou

### Motivacao
- O codigo original silenciosamente pulava devices com validacao falha: `print(f'Validation failed for device {name}')` e continuava
- Se 3 de 10 devices tinham type invalido, o operador so descobria ao conferir o NetBox depois
- Agora todos os erros sao coletados, logados e retornados, permitindo ao orchestrador decidir se aborta ou continua
- Logs detalhados: `logger.warn("Validation failed", device="server-01", reason="device_type 'XYZ' not found")`

---

## 8. Criacao em bulk (`devices.py`)

### O que foi feito
- `create_devices()`: envia todos os payloads em um unico POST quando nao ha chassis (bulk)
- `create_interfaces_bulk()`: envia IPMI, PXE e ETH0 em um unico POST (3 interfaces, 1 request)
- Quando ha chassis, a criacao e sequencial (cada device precisa de device bay imediatamente apos)

### Motivacao
- O codigo original fazia 1 POST por device e 3 POSTs por device para interfaces
- Para 10 devices: 10 + 30 = 40 requests HTTP. Com bulk: 1 + 10 = 11 requests
- Reducao de ~70% nos round-trips HTTP para o cenario sem chassis
- A API do NetBox suporta nativamente bulk POST em `dcim/devices/` e `dcim/interfaces/`

---

## 9. Deduplicacao de VLANs (`orchestrator.py`)

### O que foi feito
- Antes de criar devices, o orchestrador coleta pares unicos `(vlan_group, vlan_id)` de todos os devices
- Cada VLAN e VLAN group e criada uma unica vez
- Resultados armazenados em `vlan_lookup` dict para reuso durante o processamento de cada device

### Motivacao
- O codigo original chamava `create_network_infrastructure()` para cada device individualmente
- Se 10 devices compartilhavam a mesma VLAN, ela era verificada/criada 10 vezes
- A deduplicacao elimina chamadas redundantes a API e evita erros de "VLAN already exists"

---

## 10. Tratamento de falha parcial (`orchestrator.py`)

### O que foi feito
- Cada device e processado em seu proprio `try/except`
- Falha em um device nao aborta o processamento dos demais
- `OnboardingResults` rastreia `succeeded` e `failed` com nome do device e mensagem de erro
- Resumo final logado com contagem de sucesso/falha e duracao total

### Motivacao
- O codigo original poderia parar no meio do processamento se um unico device falhasse
- Em producao, e preferivel criar 9 de 10 devices do que criar 0 por causa de 1 falha
- O resumo final permite ao operador identificar rapidamente quais devices precisam de atencao

---

## 11. Configuracao centralizada (`config.py`)

### O que foi feito
- Dataclass `OnboardingConfig` com todos os parametros de configuracao
- Constantes nomeadas substituindo magic numbers: `ONBOARDING_TENANT_ID = 18458`, `SEGMENTATION_TAG_ID = 61`, `IP_TAG_IDS`, `VID_RANGE`
- `load_config()` le env vars e valida presenca antes de prosseguir
- `create_session()` encapsula a criacao da sessao com retry

### Motivacao
- O codigo original tinha magic numbers espalhados: `18458` na linha 245, `61` na linha 277, `24/25/26` nas linhas 651-653
- Encontrar e alterar esses valores exigia busca manual no arquivo inteiro
- Variaveis de ambiente eram lidas no escopo global sem validacao — se faltasse uma, o erro so aparecia no meio da execucao
- Agora, env vars faltantes geram erro claro no inicio: `"Missing required environment variables: RD_OPTION_NETBOXTOKEN"`

---

## 12. Atualizacao do layout da planilha

### O que foi feito
- Atualizado `spreadsheet.py` para o novo modelo padrao de CSV (`General Onboarding example - Onboarding.csv`)
- 5 indices de colunas de devices foram ajustados:

| Campo | Indice antigo | Indice novo | Header na planilha |
|-------|---------------|-------------|---------------------|
| ip_ipmi | 8 | 9 | IPMI /24 |
| ip_eth0 | 9 | 10 | IPv4 /31 |
| ipv6_eth0 | 11 | 12 | IPv6 /64 |
| vlan | 13 | 14 | Vlan Segmentacao |
| vlan_group | 14 | 15 | Vlan Group |

- Metadata (rows 0-5) e demais colunas de devices (name, device_type, RU, serial, cluster) permaneceram nas mesmas posicoes

### Motivacao
- O novo template padrao adicionou colunas intermediarias (ex: "customer_access" entre "Maxiadmin Info" e "IPMI /24")
- Os campos de rede e VLAN deslocaram 1-2 posicoes para a direita
- O modelo `General Onboarding example - Onboarding.csv` sera o padrao para todas as ativacoes futuras

---

## Resumo de arquivos

| Arquivo | Status | Descricao |
|---------|--------|-----------|
| `netbox_onboarding/__init__.py` | Novo | Package init, exporta `run()` |
| `netbox_onboarding/config.py` | Novo | Configuracao, constantes, sessao HTTP |
| `netbox_onboarding/client.py` | Novo | Cliente HTTP generico + excecoes |
| `netbox_onboarding/cache.py` | Novo | Cache com warm-up paralelo |
| `netbox_onboarding/spreadsheet.py` | Novo | Parsing com pandas + dataclasses |
| `netbox_onboarding/validators.py` | Novo | Validacao com coleta de erros |
| `netbox_onboarding/devices.py` | Novo | Criacao bulk de devices/interfaces/IPs |
| `netbox_onboarding/networking.py` | Novo | VLANs, prefixes, gateways |
| `netbox_onboarding/orchestrator.py` | Novo | Fluxo principal + tracking de resultados |
| `run_onboarding.py` | Novo | Entry point |
| `old_netbox_onboarding.py` | Mantido | Script original preservado para referencia |
| `file_logger.py` | Mantido | Sem alteracoes |
