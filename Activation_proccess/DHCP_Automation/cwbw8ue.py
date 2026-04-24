import pandas as pd
from netmiko import ConnectHandler
import pynetbox
import urllib3
import requests
import re
import os
import sys
from datetime import datetime

# ==================== CONFIGURAÇÕES ====================
url = "https://netbox.latitude.co"
token = "893f12c535bcfa304d9c5ef6b3d025d7f8b1ecda"
username = "felipe.gomes"
password = "Sucodemilho@2005"
secret = "21M03t@oB8~06"

# Arquivo de entrada
INPUT_CSV = 'PSU_Switches - Fontes detectadas - Automação.csv'

# Modo de teste (testar com apenas 1 switch)
MODO_TESTE = False
MAX_SWITCHES_TESTE = 1

# ==================== SETUP NETBOX ====================
nb = pynetbox.api(url=url, token=token, threading=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.verify = False
nb.http_session = session


# ============================================================
# VALIDAÇÕES INICIAIS
# ============================================================
def validar_ambiente():
    """Valida todas as dependências e arquivos necessários"""
    print("=" * 60)
    print("VALIDANDO AMBIENTE")
    print("=" * 60)
    
    # 1. Verificar openpyxl (não necessário para CSV, mas mantém compatibilidade)
    print("✔ Modo CSV ativo - openpyxl não necessário.")

    # 2. Teste de escrita CSV
    try:
        df_teste = pd.DataFrame({"TESTE": [1, 2, 3]})
        arquivo_teste = "TEST_WRITE_CHECK.csv"
        df_teste.to_csv(arquivo_teste, index=False)
        
        # Verificar se o arquivo foi criado
        if not os.path.exists(arquivo_teste):
            raise Exception("Arquivo não foi criado")
            
        # Tentar ler o arquivo
        df_lido = pd.read_csv(arquivo_teste)
        if len(df_lido) != 3:
            raise Exception("Dados não foram escritos corretamente")
            
        os.remove(arquivo_teste)
        print("✔ Teste de escrita/leitura CSV bem-sucedido.")
    except Exception as e:
        print(f"❌ Falha no teste CSV: {e}")
        return False

    # 3. Verificar arquivo CSV de entrada
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Arquivo CSV não encontrado: {INPUT_CSV}")
        return False
    print(f"✔ Arquivo CSV encontrado: {INPUT_CSV}")

    # 4. Validar estrutura do CSV
    try:
        df = pd.read_csv(INPUT_CSV)
        if 'Switch' not in df.columns:
            print("❌ Coluna 'Switch' não encontrada no CSV")
            return False
        
        switches = df[['Switch']].dropna().astype(str)['Switch'].tolist()
        if len(switches) == 0:
            print("❌ Nenhum switch encontrado no CSV")
            return False
            
        print(f"✔ CSV válido com {len(switches)} switches")
    except Exception as e:
        print(f"❌ Erro ao ler CSV: {e}")
        return False

    # 5. Testar conexão com NetBox
    try:
        devices = nb.dcim.devices.all()
        print(f"✔ Conexão com NetBox OK ({len(list(devices))} dispositivos)")
    except Exception as e:
        print(f"❌ Erro ao conectar no NetBox: {e}")
        return False

    print("\n✅ TODAS AS VALIDAÇÕES PASSARAM!\n")
    return True


# ============================================================
# PARSER PARA OS DOIS PADRÕES DE SAÍDA
# ============================================================
def parse_power_output(output):
    """Parse da saída do comando show environment power"""
    psus = []

    # -------- Formato moderno (N9K mais novo)
    regex_moderno = r"(\d+)\s+([\w\-]+)\s+(\d+)\s+W\s+(\d+)\s+W\s+(\d+)\s+W"
    matches_moderno = re.findall(regex_moderno, output)

    if matches_moderno:
        for match in matches_moderno:
            psu_id, model, output_w, input_w, cap = match
            psus.append({
                "PSU": psu_id,
                "Modelo": model,
                "Input(W)": input_w,
                "Output(W)": output_w,
                "Capacity(W)": cap
            })
        return psus

    # -------- Formato antigo (N2K / N9K old)
    regex_antigo = r"(\d+)\s+([\w\-]+)\s+AC\s+([\d\.]+)\s+([\d\.]+)\s+\w+"
    matches_antigo = re.findall(regex_antigo, output)

    if matches_antigo:
        for psu_id, model, input_w, current in matches_antigo:
            psus.append({
                "PSU": psu_id,
                "Modelo": model,
                "Input(W)": input_w,
                "Output(W)": "N/A",
                "Capacity(W)": "N/A"
            })
        return psus

    return psus


# ============================================================
# FUNÇÃO PARA SALVAR RESULTADOS
# ============================================================
def salvar_resultados(resultados, modo_teste=False):
    """Salva os resultados em arquivo CSV com timestamp"""
    if not resultados:
        print("\n⚠ Nenhum dado para salvar.")
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if modo_teste:
        nome_arquivo = f"PSU_Result_TESTE_{timestamp}.csv"
    else:
        nome_arquivo = f"PSU_Result_{timestamp}.csv"
    
    try:
        final_df = pd.DataFrame(resultados)
        
        # Reordenar colunas para melhor visualização
        colunas_ordem = ["Switch", "IP", "PSU", "Modelo", "Input(W)", "Output(W)", "Capacity(W)"]
        final_df = final_df[colunas_ordem]
        
        final_df.to_csv(nome_arquivo, index=False, encoding='utf-8')
        
        # Verificar se o arquivo foi criado
        if not os.path.exists(nome_arquivo):
            raise Exception("Arquivo não foi criado")
        
        # Verificar tamanho do arquivo
        tamanho = os.path.getsize(nome_arquivo)
        if tamanho < 50:
            raise Exception("Arquivo gerado está muito pequeno")
        
        print(f"\n✅ Arquivo gerado com sucesso: {nome_arquivo}")
        print(f"   Tamanho: {tamanho} bytes")
        print(f"   Total de registros: {len(final_df)}")
        
        return nome_arquivo
        
    except Exception as e:
        print(f"\n❌ Erro ao salvar arquivo: {e}")
        return None


# ============================================================
# FUNÇÃO PARA PROCESSAR UM SWITCH
# ============================================================
def processar_switch(sw):
    """Processa um switch e retorna lista de PSUs encontradas"""
    print(f"\n{'=' * 60}")
    print(f"Processando switch: {sw}")
    print(f"{'=' * 60}")
    
    resultados_switch = []

    # Busca no NetBox
    try:
        device_obj = nb.dcim.devices.get(name=sw)
    except Exception as e:
        print(f"❌ Erro ao buscar no NetBox: {e}")
        return []
    
    if not device_obj:
        print(f"❌ Switch {sw} não encontrado no NetBox")
        return []

    primary_ipv4 = device_obj.primary_ip4
    if not primary_ipv4:
        print(f"❌ Switch {sw} sem IP primário configurado")
        return []

    host = str(primary_ipv4).split('/')[0]
    print(f"📍 IP encontrado: {host}")

    # Detecta se é Nexus
    if "nexus" in str(device_obj.device_type.manufacturer).lower():
        device_os = "cisco_nxos"
    else:
        device_os = "cisco_ios"
    
    print(f"🔧 Sistema operacional detectado: {device_os}")

    conn_data = {
        "device_type": device_os,
        "host": host,
        "username": username,
        "password": password,
        "timeout": 120,
        "fast_cli": False,
        "global_delay_factor": 2
    }

    print(f"🔌 Conectando ao switch...")

    try:
        net = ConnectHandler(**conn_data)
        print("✔ Conectado com sucesso")
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return []

    # Configuração de terminal
    try:
        net.send_command("terminal length 0", expect_string=r"#")
    except:
        pass

    print("⚙ Executando comando show environment power...")

    # Fallback automático
    comandos = [
        "show environment power | head",
        "show environment power"
    ]

    output = ""
    for cmd in comandos:
        try:
            print(f"   Tentando: {cmd}")
            output = net.send_command(cmd, expect_string=r"#", read_timeout=60)
            if output and "Power" in output:
                print(f"   ✔ Comando executado com sucesso")
                break
        except Exception as e:
            print(f"   ⚠ Falha: {e}")
            continue

    net.disconnect()

    if not output:
        print(f"❌ Nenhuma saída válida obtida")
        return []

    # Parse da saída
    psu_info = parse_power_output(output)

    if not psu_info:
        print(f"⚠ Não foi possível interpretar PSU")
        print(f"   Primeiras linhas da saída:")
        for linha in output.split('\n')[:10]:
            print(f"   {linha}")
        return []

    print(f"✔ {len(psu_info)} PSU(s) encontrada(s)")

    for item in psu_info:
        item["Switch"] = sw
        item["IP"] = host
        resultados_switch.append(item)
        print(f"   PSU {item['PSU']}: {item['Modelo']} - {item['Input(W)']}W")

    return resultados_switch


# ============================================================
# MAIN
# ============================================================
def main():
    # Validações iniciais
    if not validar_ambiente():
        print("\n❌ Falha nas validações. Corrija os erros antes de continuar.")
        sys.exit(1)

    # Carregar lista de switches
    df = pd.read_csv(INPUT_CSV)
    switches = df[['Switch']].dropna().astype(str)['Switch'].tolist()
    
    if MODO_TESTE:
        switches = switches[:MAX_SWITCHES_TESTE]
        print(f"\n⚠ MODO DE TESTE ATIVO - Processando apenas {len(switches)} switch(es)")
        print(f"   Para processar todos, defina MODO_TESTE = False no código\n")
    else:
        print(f"\n📊 Modo PRODUÇÃO - Processando {len(switches)} switches")
        resposta = input("Deseja continuar? (s/n): ")
        if resposta.lower() != 's':
            print("Operação cancelada pelo usuário.")
            sys.exit(0)

    # Processar switches
    resultados = []
    sucesso = 0
    falhas = 0

    for idx, sw in enumerate(switches, 1):
        print(f"\n[{idx}/{len(switches)}]")
        resultado_sw = processar_switch(sw)
        
        if resultado_sw:
            resultados.extend(resultado_sw)
            sucesso += 1
        else:
            falhas += 1

    # Resumo
    print(f"\n{'=' * 60}")
    print("RESUMO DA EXECUÇÃO")
    print(f"{'=' * 60}")
    print(f"Switches processados: {len(switches)}")
    print(f"Sucessos: {sucesso}")
    print(f"Falhas: {falhas}")
    print(f"Total de PSUs coletadas: {len(resultados)}")

    # Salvar resultados
    if resultados:
        arquivo = salvar_resultados(resultados, modo_teste=MODO_TESTE)
        if arquivo:
            print(f"\n✅ PROCESSO CONCLUÍDO COM SUCESSO!")
            if MODO_TESTE:
                print(f"\n💡 PRÓXIMOS PASSOS:")
                print(f"   1. Verifique o arquivo gerado: {arquivo}")
                print(f"   2. Se estiver correto, defina MODO_TESTE = False")
                print(f"   3. Execute novamente para processar todos os switches")
        else:
            print(f"\n❌ ERRO ao salvar resultados")
    else:
        print("\n⚠ Nenhum dado foi coletado.")


if __name__ == "__main__":
    main()