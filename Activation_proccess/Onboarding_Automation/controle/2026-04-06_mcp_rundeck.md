# Feature: MCP Server para Rundeck

**Data:** 2026-04-06
**Autor:** Felipe Gomes + Claude

---

## 1. Criacao do MCP Server (`rundeck_server.py`)

### O que foi feito
- Criado servidor MCP em `C:\Users\felipe\.claude\mcp-servers\rundeck_server.py`
- Utiliza a biblioteca `mcp` (FastMCP) para expor tools ao Claude Code
- Comunica com a API v46 do Rundeck via REST (requests)
- Autenticacao via API Token no header `X-Rundeck-Auth-Token`
- Todas as operacoes tem timeout de 30 segundos e tratamento de erros

### Motivacao
- Permitir que o Claude Code interaja diretamente com o Rundeck
- Possibilitar criar, gerenciar e executar jobs sem sair do terminal
- Integrar o fluxo de onboarding com o Rundeck (subir jobs automaticamente)

---

## 2. Tools disponiveis

### Projetos
| Tool | Descricao | Parametros |
|------|-----------|------------|
| `list_projects` | Lista todos os projetos do Rundeck | nenhum |

### Jobs - Leitura
| Tool | Descricao | Parametros |
|------|-----------|------------|
| `list_jobs` | Lista jobs de um projeto | `project`, `filter_name` (opcional) |
| `get_job` | Busca definicao completa por ID | `job_id` |
| `export_job` | Exporta em JSON/YAML/XML | `job_id`, `format` |

### Jobs - Escrita
| Tool | Descricao | Parametros |
|------|-----------|------------|
| `create_job` | Cria job a partir de JSON completo | `project`, `job_definition_json` |
| `create_simple_job` | Cria job com um unico comando | `project`, `name`, `command`, `description`, `group` |
| `update_job` | Atualiza definicao de um job | `job_id`, `job_definition_json` |
| `delete_job` | Deleta um job (irreversivel) | `job_id` |

### Execucoes
| Tool | Descricao | Parametros |
|------|-----------|------------|
| `execute_job` | Executa um job | `job_id`, `options` (JSON opcional) |
| `get_execution` | Status de uma execucao | `execution_id` |
| `get_execution_log` | Log de saida | `execution_id`, `max_lines` |
| `list_executions` | Lista execucoes recentes | `project`, `job_id` (opcional), `max_results` |

---

## 3. Configuracao

### Arquivos
| Arquivo | Descricao |
|---------|-----------|
| `C:\Users\felipe\.claude\mcp-servers\rundeck_server.py` | Codigo do servidor MCP |
| `C:\Users\felipe\.claude.json` | Configuracao global (secao `mcpServers.rundeck`) |

### Variaveis de ambiente (configuradas no .claude.json)
| Variavel | Valor |
|----------|-------|
| `RUNDECK_URL` | `http://10.90.16.100:4440` |
| `RUNDECK_TOKEN` | Token de API configurado |

### Registro
O servidor foi registrado globalmente (escopo `user`) via:
```bash
claude mcp add --transport stdio -s user rundeck \
  --env RUNDECK_URL=http://10.90.16.100:4440 \
  --env RUNDECK_TOKEN=<token> \
  -- python C:/Users/felipe/.claude/mcp-servers/rundeck_server.py
```

---

## 4. Dependencias

| Pacote | Uso |
|--------|-----|
| `mcp` | SDK do Model Context Protocol (FastMCP) |
| `requests` | Chamadas HTTP para a API do Rundeck |

Ambos ja estavam instalados no ambiente Python.

---

## 5. Como usar

Apos reiniciar o Claude Code, os tools ficam disponiveis automaticamente. Exemplos:

**Listar projetos:**
> "Liste os projetos do Rundeck"

**Criar job simples:**
> "Crie um job chamado 'netbox-onboarding' no projeto 'ops' que roda: python /scripts/run_onboarding.py"

**Executar job:**
> "Execute o job <job-id> com as opcoes {'planilha': 'arquivo.csv'}"

**Ver log de execucao:**
> "Mostre o log da execucao <execution-id>"

---

## 6. Seguranca

- O token de API fica armazenado em `C:\Users\felipe\.claude.json` (arquivo local, nao versionado)
- O token nao e exposto nos logs do MCP server
- Todas as chamadas sao feitas via HTTP para a rede interna (10.90.16.100)
- Operacoes destrutivas (delete_job) exigem confirmacao do usuario no Claude Code
