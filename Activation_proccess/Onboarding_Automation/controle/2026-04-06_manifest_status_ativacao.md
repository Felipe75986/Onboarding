# Feature: Manifest de IDs, Validacao de Status e Script de Ativacao

**Data:** 2026-04-06
**Autor:** Felipe Gomes + Claude

---

## 1. Manifest de IDs (`manifest.py`)

### O que foi feito
- Criada classe `OnboardingManifest` em `netbox_onboarding/manifest.py`
- Rastreia todos os IDs criados durante o onboarding: devices, interfaces, IPs, VLANs, prefixes, cables e chassis
- Salva como JSON na pasta `manifests/` com nome `YYYY-MM-DD_{site}_{rack}.json`
- Metodos: `add_device()`, `add_ip()`, `add_vlan()`, `add_prefix()`, `add_cable()`, `add_interface()`, `set_chassis()`, `save()`, `load()`
- Deduplicacao automatica para VLANs e prefixes (evita duplicatas no manifest)

### Motivacao
- Antes nao havia registro dos IDs dos objetos criados no NetBox
- Sem os IDs, era impossivel fazer operacoes em massa (como mudar status) nos objetos criados
- O manifest serve como "recibo" do onboarding e como input para o script de ativacao

### Formato do manifest
```json
{
  "created_at": "2026-04-06T14:30:00",
  "site": "LAX5",
  "rack": "A-07-15-1-A",
  "ticket": "TICKET-123",
  "status": "planned",
  "chassis": {"id": 7001, "name": "chassis-01"},
  "devices": [{"id": 1001, "name": "server-01"}],
  "interfaces": [{"id": 2001, "name": "ETH0", "device": "server-01"}],
  "ip_addresses": [{"id": 3001, "address": "10.0.0.1/31", "device": "server-01"}],
  "vlans": [{"id": 4001, "vid": 3750, "group": "vg-lax5"}],
  "prefixes": [{"id": 5001, "prefix": "10.0.0.0/31"}],
  "cables": [{"id": 6001, "description": "server-01:ETH0 -> SWACC26:Ethernet1/1"}]
}
```

---

## 2. Validacao de status dos switches (`validators.py`)

### O que foi feito
- Adicionada funcao `resolve_status_from_switches()` em `netbox_onboarding/validators.py`
- Busca cada switch pelo nome no NetBox e verifica seu campo `status`
- Logica de resolucao:
  - Todos os switches "active" → retorna "active"
  - Qualquer switch "planned" → retorna "planned"
  - Switch nao encontrado → warning no log, usa fallback (env var original)
- O status resolvido sobrescreve o `config.status` usando `dataclasses.replace()`

### Motivacao
- Antes o status era definido exclusivamente pela env var `RD_OPTION_RESERVA`
- Em producao, o status deveria refletir a realidade da infraestrutura: se os switches ainda estao como planned, os devices tambem devem ser planned
- Evita criar devices como "active" quando a infraestrutura de rede ainda nao esta pronta

---

## 3. Integracao do manifest no orchestrator

### O que foi feito
- `orchestrator.py` agora cria um `OnboardingManifest` no inicio do fluxo
- Cada objeto criado (chassis, device, interface, IP, VLAN, prefix) e registrado no manifest
- O manifest e salvo ao final da execucao, mesmo em caso de falha parcial
- `OnboardingResults` agora inclui `manifest_path` para referencia
- O `run()` aceita parametro opcional `switch_names` para ativar a validacao de status

### Motivacao
- Centralizar o rastreamento de IDs em um unico ponto do fluxo
- Garantir que o manifest e salvo mesmo se alguns devices falharem
- Permitir que o script de ativacao tenha todos os IDs necessarios

---

## 4. Script de ativacao (`activate.py` + `run_activate.py`)

### O que foi feito
- Criado `netbox_onboarding/activate.py` com funcao `activate_from_manifest()`
- Criado `run_activate.py` como entry point independente
- Fluxo:
  1. Le o manifest JSON
  2. Para cada tipo de objeto (devices, IPs, VLANs, prefixes), faz `PATCH {"status": "active"}`
  3. Chassis tambem e ativado se presente
  4. Atualiza o manifest com `"status": "active"` e `"activated_at": timestamp`
  5. Log de resumo com contagem de sucesso/falha

### Uso
```bash
# Via argumento CLI:
python run_activate.py manifests/2026-04-06_LAX5_A-07-15-1-A.json

# Via env var (Rundeck):
RD_FILE_MANIFEST="manifests/2026-04-06_LAX5_A-07-15-1-A.json" python run_activate.py
```

### Motivacao
- Antes nao havia como ativar em massa os objetos criados como "planned"
- O operador teria que acessar o NetBox e mudar cada objeto manualmente
- Agora basta rodar o script com o manifest para ativar tudo de uma vez

---

## 5. Manifest no connections.py

### O que foi feito
- `create_cables()` agora aceita parametro opcional `manifest`
- Cada cabo criado e registrado no manifest com seu ID e descricao
- Retrocompativel: se manifest nao for passado, comportamento e identico ao anterior

### Motivacao
- Os cabos fazem parte da documentacao do onboarding e devem ser rastreados
- Permite que o manifest completo inclua todos os objetos criados (devices + cabos)

---

## 6. Retorno de dados em networking.py

### O que foi feito
- `create_prefix()`, `_create_ipv4_prefix()` e `_create_ipv6_prefix()` agora retornam o prefix criado (dict) ou None
- Permite que o orchestrator registre o prefix no manifest

### Motivacao
- Antes as funcoes retornavam `None` (void) e nao era possivel saber o ID do prefix criado
- Necessario para alimentar o manifest com os IDs dos prefixes

---

## Resumo de arquivos

| Arquivo | Acao | Descricao |
|---------|------|-----------|
| `netbox_onboarding/manifest.py` | Novo | Classe OnboardingManifest para rastrear IDs |
| `netbox_onboarding/activate.py` | Novo | Logica de ativacao planned → active |
| `run_activate.py` | Novo | Entry point do script de ativacao |
| `netbox_onboarding/validators.py` | Modificado | Adicionada `resolve_status_from_switches()` |
| `netbox_onboarding/orchestrator.py` | Modificado | Integrado manifest + status dos switches |
| `netbox_onboarding/networking.py` | Modificado | Funcoes de prefix agora retornam dados |
| `netbox_onboarding/connections.py` | Modificado | Suporte a manifest opcional |
