import pandas as pd
from netmiko import ConnectHandler
import pynetbox
import urllib3
import requests
import time
import re
import paramiko
from datetime import datetime
import subprocess
import json
from urllib3.exceptions import InsecureRequestWarning
import os
import sys
import socket

# ==================== CONFIGURAÇÕES ====================
url = "https://netbox.latitude.co"
token = "38ddf596d29b2b735c1ba14720a2aa4d9c9bad79"
username = "felipe.gomes"
password = "Sucodemilho@2005"
secret = "21M03t@oB8~06"

file_name = ("[ASH2] 10x m4.xlarge (Rack 01.03 - RU 22~32) - Delivery.csv")
file_name_onboard = ("[ASH2] 10x m4.xlarge (Rack 01.03 - RU 22~32) - Onboarding.csv")

# Configurações do servidor DHCP - AJUSTE AQUI
DHCP_SERVER_IP = "10.90.10.30"
DHCP_SERVER_USER = "ubuntu"
DHCP_SERVER_PASS = "Netops@123"

# Configurações Redfish - AJUSTE AQUI
REDFISH_USER = "ADMIN"
REDFISH_PASS = "QFLGXTFDXA"

# ==================== SETUP NETBOX ====================
nb = pynetbox.api(url=url, token=token, threading=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
session = requests.Session()
session.verify = False
nb.http_session = session


# ==================== FUNÇÕES AUXILIARES DHCP ====================

def extract_macs_from_output(output):
    """
    Extrai endereços MAC da saída do comando 'show mac address'
    
    Args:
        output (str): Saída do comando show mac do switch
        
    Returns:
        list: Lista de MACs no formato Cisco (ex: 905a.0818.5214)
    """
    mac_pattern = r'([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})'
    return re.findall(mac_pattern, output.lower())


def format_mac_for_dhcp(mac_cisco):
    """
    Converte MAC do formato Cisco para formato DHCP
    
    Args:
        mac_cisco (str): MAC no formato Cisco (ex: 905a.0818.5214)
        
    Returns:
        str: MAC no formato DHCP (ex: 90:5A:08:18:52:14)
    """
    mac_clean = mac_cisco.replace('.', '').upper()
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])


def generate_dhcp_entries(mac_list, base_ip, start_host, rack_name, ru_position):
    """
    Gera entradas de configuração DHCP para cada MAC
    
    Args:
        mac_list (list): Lista de MACs no formato Cisco
        base_ip (str): Primeiros 3 octetos do IP (ex: "10.250.140")
        start_host (int): Número do primeiro host (ex: 10 para .10)
        rack_name (str): Nome do rack (ex: "AI47")
        ru_position (str): Posição RU (ex: "31")
        
    Returns:
        str: Configuração DHCP formatada
    """
    entries = []
    
    # Limpar rack_name e ru_position removendo espaços e caracteres especiais
    clean_rack = rack_name.replace(' ', '_').replace('~', '-')
    clean_ru = ru_position.replace(' ', '_').replace('~', '-')
    
    for idx, mac in enumerate(mac_list, 1):
        mac_dhcp = format_mac_for_dhcp(mac)
        ip = f"{base_ip}.{start_host + idx - 1}"
        hostname = f"ipmi_{clean_rack}_ru{clean_ru}_node{idx}"
        
        entry = f"""host {hostname} {{
  hardware ethernet {mac_dhcp};
  fixed-address {ip};
}}
"""
        entries.append(entry)
    
    return '\n'.join(entries)


def save_dhcp_config(config_content, filename="dhcp_hosts.conf"):
    """
    Salva a configuração DHCP em arquivo
    
    Args:
        config_content (str): Conteúdo da configuração DHCP
        filename (str): Nome do arquivo para salvar
        
    Returns:
        str: Nome do arquivo salvo
    """
    with open(filename, 'w') as f:
        f.write(config_content)
    return filename


def apply_dhcp_config_to_server(config_content, server_ip, username, password):
    """
    Aplica configuração DHCP automaticamente no servidor via SSH
    SOBRESCREVE o arquivo dhcpd.conf completamente (não adiciona, substitui)
    
    Args:
        config_content (str): Conteúdo da configuração DHCP (apenas hosts)
        server_ip (str): IP do servidor DHCP
        username (str): Usuário SSH
        password (str): Senha SSH
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        print(f"\n{'='*70}")
        print(f"Conectando no servidor DHCP {server_ip}...")
        print(f"{'='*70}\n")
        
        # Conectar via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=username, password=password, timeout=30)
        
        # 1. Ler template base da configuração DHCP (sem os hosts dinâmicos)
        # Vamos assumir que existe um template em /etc/dhcp/dhcpd.conf.template
        # Se não existir, usamos uma configuração base mínima
        
        print("Lendo configuração base do DHCP...")
        read_template_cmd = "cat /etc/dhcp/dhcpd.conf.template 2>/dev/null || echo ''"
        stdin, stdout, stderr = ssh.exec_command(read_template_cmd)
        template_config = stdout.read().decode()
        
        if not template_config.strip():
            # Template não existe, criar configuração base
            print("⚠ Template não encontrado, usando configuração base padrão")
            template_config = """# DHCP Server Configuration
# Auto-generated by IPMI Unified Script

option domain-name "latitude.co";
option domain-name-servers 8.8.8.8, 8.8.4.4;

default-lease-time 600;
max-lease-time 7200;

ddns-update-style none;

authoritative;

# Subnet declarations would go here if needed
# subnet 10.0.0.0 netmask 255.255.255.0 {
#   range 10.0.0.100 10.0.0.200;
# }

# ============================================================================
# IPMI HOST ENTRIES - Managed by automation script
# ============================================================================
"""
        else:
            print("✓ Template de configuração base encontrado")
            # Adicionar separador se não existir
            if "IPMI HOST ENTRIES" not in template_config:
                template_config += """
# ============================================================================
# IPMI HOST ENTRIES - Managed by automation script
# ============================================================================
"""
        
        # 2. Criar nova configuração completa (template + hosts)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_config = template_config + f"\n# Last updated: {timestamp}\n\n"
        new_config += config_content
        
        # 3. Criar arquivo temporário
        temp_file = f"/etc/dhcp/dhcpd.conf.new"
        
        # Criar o arquivo usando tee com sudo
        create_cmd = f'sudo -S tee {temp_file} > /dev/null'
        stdin, stdout, stderr = ssh.exec_command(create_cmd)
        stdin.flush()
        time.sleep(1)
        stdin.write(new_config)
        stdin.channel.shutdown_write()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao criar arquivo temporário: {error}"
        
        print(f"✓ Nova configuração criada em {temp_file}")

        #chmod_cmd = f"sudo chmod 644 {temp_file}"
        #stdin, stdout, stderr = ssh.exec_command(chmod_cmd)
        #stdin.write(password + '\n')
        #stdin.flush()
        #stdout.channel.recv_exit_status()
        
        # 4. Validar configuração
        test_cmd = f"sudo dhcpd -t -cf {temp_file}"
        stdin, stdout, stderr = ssh.exec_command(test_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        test_output = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            # Limpar arquivo temporário
            cleanup_cmd = f"sudo rm -f {temp_file}"
            stdin_clean, stdout_clean, stderr_clean = ssh.exec_command(cleanup_cmd)
            stdin_clean.write(password + '\n')
            stdin_clean.flush()
            ssh.close()
            return False, f"Erro na validação da configuração:\n{test_output}"
        
        print("✓ Configuração validada com sucesso")
        
        # 5. Substituir arquivo de configuração (SOBRESCREVE completamente)
        apply_cmd = f"sudo mv {temp_file} /etc/dhcp/dhcpd.conf"
        stdin, stdout, stderr = ssh.exec_command(apply_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao aplicar configuração: {error}"
        
        print("✓ Configuração aplicada (arquivo SOBRESCRITO)")
        
        # 6. Reiniciar serviço DHCP
        restart_cmd = "sudo systemctl restart isc-dhcp-server"
        stdin, stdout, stderr = ssh.exec_command(restart_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao reiniciar serviço DHCP: {error}"
        
        print("✓ Serviço DHCP reiniciado")
        
        # 7. Verificar status do serviço
        status_cmd = "sudo systemctl is-active isc-dhcp-server"
        stdin, stdout, stderr = ssh.exec_command(status_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        status = stdout.read().decode().strip()
        
        ssh.close()
        
        if status == "active":
            return True, "Configuração aplicada (arquivo sobrescrito) e serviço DHCP está ativo"
        else:
            return False, f"Configuração aplicada mas serviço DHCP está: {status}"
            
    except Exception as e:
        return False, f"Erro ao conectar no servidor DHCP: {e}"


def validate_ips_with_ping(ip_list, timeout=2, max_retries=3):
    """
    Valida quais IPs estão respondendo via ping ou conexão TCP
    
    Args:
        ip_list (list): Lista de IPs para validar
        timeout (int): Timeout do ping em segundos
        max_retries (int): Número máximo de tentativas por IP
        
    Returns:
        dict: Dicionário {ip: True/False} indicando se o IP está acessível
    """
    print(f"\n{'='*70}")
    print(f"VALIDANDO CONECTIVIDADE DE {len(ip_list)} IPs")
    print(f"{'='*70}\n")
    
    # Verificar se ping está disponível
    ping_available = False
    try:
        subprocess.run(['ping', '-c', '1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        ping_available = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("⚠ Comando 'ping' não disponível, usando conexão TCP na porta 443 (HTTPS)\n")
    
    ip_status = {}
    
    for ip in ip_list:
        print(f"Testando {ip}...", end=" ")
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                if ping_available:
                    # Ping usando subprocess
                    result = subprocess.run(
                        ['ping', '-c', '1', '-W', str(timeout), ip],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=timeout + 1
                    )
                    
                    if result.returncode == 0:
                        success = True
                        print(f"✓ OK")
                        break
                else:
                    # Usar socket para testar conectividade TCP na porta 443 (Redfish)
                    import socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((ip, 443))
                    sock.close()
                    
                    if result == 0:
                        success = True
                        print(f"✓ OK (TCP:443)")
                        break
                
                if attempt < max_retries:
                    time.sleep(1)
                    
            except socket.timeout:
                if attempt < max_retries:
                    time.sleep(1)
            except subprocess.TimeoutExpired:
                if attempt < max_retries:
                    time.sleep(1)
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(1)
        
        if not success:
            print(f"✗ SEM RESPOSTA")
        
        ip_status[ip] = success
    
    # Resumo
    active_count = sum(ip_status.values())
    inactive_count = len(ip_list) - active_count
    
    print(f"\n{'='*70}")
    print(f"RESUMO: {active_count} ativos, {inactive_count} inativos de {len(ip_list)} IPs")
    print(f"{'='*70}\n")
    
    return ip_status


def collect_serials_from_ipmis(ip_mac_mapping, username, password):
    """
    Coleta números de série de IPMIs via Redfish API
    
    Args:
        ip_mac_mapping (dict): Dicionário {ip: mac}
        username (str): Usuário Redfish
        password (str): Senha Redfish
        
    Returns:
        dict: Dicionário {mac: serial_number}
    """
    mac_serial_mapping = {}
    
    for ip, mac in ip_mac_mapping.items():
        print(f"\nColetando serial de {ip} (MAC: {mac})...", end=" ")
        
        try:
            # URL do Redfish para informações do sistema
            url = f"https://{ip}/redfish/v1/Systems/1"
            
            # Fazer requisição
            response = requests.get(
                url,
                auth=(username, password),
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                serial = data.get('SerialNumber', 'N/A')
                mac_serial_mapping[mac] = serial
                print(f"✓ Serial: {serial}")
            else:
                print(f"✗ HTTP {response.status_code}")
                mac_serial_mapping[mac] = f"ERROR_HTTP_{response.status_code}"
                
        except requests.exceptions.Timeout:
            print(f"✗ Timeout")
            mac_serial_mapping[mac] = "ERROR_TIMEOUT"
        except requests.exceptions.ConnectionError:
            print(f"✗ Conexão recusada")
            mac_serial_mapping[mac] = "ERROR_CONNECTION"
        except Exception as e:
            print(f"✗ Erro: {e}")
            mac_serial_mapping[mac] = f"ERROR_{str(e)[:20]}"
    
    return mac_serial_mapping


def generate_mapping_report(mac_serial_mapping, filename="ipmi_mapping_report.txt"):
    """
    Gera relatório de mapeamento MAC → Serial
    
    Args:
        mac_serial_mapping (dict): Dicionário {mac: serial}
        filename (str): Nome do arquivo para salvar
        
    Returns:
        str: Conteúdo do relatório
    """
    report_lines = []
    report_lines.append("="*70)
    report_lines.append("RELATÓRIO DE MAPEAMENTO IPMI")
    report_lines.append("="*70)
    report_lines.append(f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Total de IPMIs: {len(mac_serial_mapping)}")
    report_lines.append("="*70)
    report_lines.append("")
    report_lines.append(f"{'MAC Address':<20} {'Serial Number':<30}")
    report_lines.append("-"*70)
    
    for mac, serial in sorted(mac_serial_mapping.items()):
        mac_formatted = format_mac_for_dhcp(mac)
        report_lines.append(f"{mac_formatted:<20} {serial:<30}")
    
    report_lines.append("="*70)
    
    report = '\n'.join(report_lines)
    
    # Salvar em arquivo
    with open(filename, 'w') as f:
        f.write(report)
    
    return report


# ==================== FUNÇÕES PRINCIPAIS ====================

def get_mac_ipmi(device, port):
    """Conecta no switch e busca os MAC addresses"""
    try:
        # Aumentar timeout e adicionar parâmetros de estabilidade
        device_config = device.copy()
        device_config['timeout'] = 120
        device_config['session_timeout'] = 120
        device_config['auth_timeout'] = 120
        device_config['banner_timeout'] = 120
        device_config['blocking_timeout'] = 120
        device_config['conn_timeout'] = 120
        
        with ConnectHandler(**device_config) as connection:
            # Enviar newline para estabilizar conexão
            connection.write_channel('\n')
            time.sleep(1)
            
            # Tentar encontrar o prompt
            try:
                prompt = connection.find_prompt()
                print(f"Prompt detectado: {prompt}")
            except:
                print("Aviso: Não foi possível detectar o prompt, continuando...")
            
            # Comandos diferentes para Nexus vs IOS
            if device['device_type'] == 'cisco_nxos':
                # Cisco Nexus - não precisa de enable e comando diferente
                print("Dispositivo: Cisco Nexus")
                output = connection.send_command(
                    f"show mac address-table interface ethernet1/{port}",
                    read_timeout=60
                )
            else:
                # Cisco IOS - precisa de enable
                print("Dispositivo: Cisco IOS")
                try:
                    connection.send_command_timing("enable", delay_factor=2)
                    connection.send_command_timing(secret, delay_factor=2)
                except:
                    pass  # Se já está em modo privilegiado, ignora erro
                
                output = connection.send_command(
                    f"show mac address interface ethernet1/{port}",
                    read_timeout=60
                )
            
            print(output)
            return output
    except Exception as e:
        print(f'{device["host"]}: Erro ao conectar - {e}')
        import traceback
        traceback.print_exc()
        return None


# ==================== FUNÇÕES ESPECÍFICAS POR MODO ====================

def process_chassis():
    """
    Processa planilha de IPMI no modo CHASSIS
    Agora lê da aba de Onboarding com MACs e IPs já mapeados
    """
    print("\n" + "="*70)
    print("MODO: CHASSIS (COM MAPEAMENTO MAC→IP DA PLANILHA)")
    print("="*70 + "\n")
    
    try:
        # Ler CSV da planilha de Onboarding
        fd = pd.read_csv(file_name)
        df = pd.read_csv(file_name_onboard)
        
        print("✓ Planilha de Onboarding carregada")
        
        # Extrair informações do rack
        rack = fd.columns[2]
        rack_name = str(rack)
        print(f"✓ Rack identificado: {rack_name}")
        
        # Extrair RU position (pode estar em diferentes lugares, vamos buscar)
        try:
            rack_ru = fd[[rack_name]]
            linha7_rack_ru = rack_ru.iloc[7].dropna().astype(str).str.strip().tolist()
            if linha7_rack_ru:
                ru_position = linha7_rack_ru[0]
            else:
                ru_position = "UNKNOWN"
        except:
            ru_position = "UNKNOWN"
        
        print(f"✓ RU Position: {ru_position}")
        
        # ==================== EXTRAIR MACs E IPs DA PLANILHA ====================
        print("\n" + "="*70)
        print("EXTRAINDO MACs E IPs DA PLANILHA")
        print("="*70 + "\n")
        
        # Extrair IPs (coluna 8 - Unnamed: 8 ou o nome da coluna de IPs)
        ips_column = df.columns[8]
        ipmi_ips = df[ips_column].iloc[7:].dropna().astype(str).str.strip().tolist()
        
        # Extrair MACs (coluna 37 - Unnamed: 37)
        mac_addresses = df['Unnamed: 37'].iloc[7:].dropna().astype(str).str.strip().tolist()
        
        # Criar dicionário MAC → IP
        mac_ip_mapping = {}
        for mac, ip in zip(mac_addresses, ipmi_ips):
            # Limpar e formatar MAC se necessário
            mac_clean = mac.strip().upper()
            ip_clean = ip.strip()
            
            # Validar que é um IP válido
            if '.' in ip_clean and len(ip_clean.split('.')) == 4:
                mac_ip_mapping[mac_clean] = ip_clean
            else:
                print(f"⚠ IP inválido ignorado: {ip_clean} para MAC {mac_clean}")
        
        print(f"✓ {len(mac_ip_mapping)} pares MAC→IP encontrados na planilha\n")
        
        # Mostrar mapeamento
        print("Mapeamento MAC → IP:")
        print("-"*70)
        for idx, (mac, ip) in enumerate(mac_ip_mapping.items(), 1):
            print(f"{idx:2d}. {mac} → {ip}")
        print("-"*70)
        
        if not mac_ip_mapping:
            print("\n✗ Nenhum mapeamento MAC→IP foi encontrado na planilha!")
            print("Verifique se:")
            print("  - A coluna 37 (Unnamed: 37) contém os MACs")
            print("  - A coluna 8 contém os IPs")
            print("  - Os dados começam a partir da linha 7")
            return
        
        # ==================== PROCESSAMENTO DHCP ====================
        print("\n" + "="*70)
        print("GERANDO CONFIGURAÇÃO DHCP")
        print("="*70 + "\n")
        
        # Gerar configuração DHCP com mapeamento específico
        dhcp_entries = []
        for idx, (mac, ip) in enumerate(mac_ip_mapping.items(), 1):
            # Limpar rack_name e ru_position para usar no hostname
            clean_rack = rack_name.replace(' ', '_').replace('~', '-')
            clean_ru = str(ru_position).replace(' ', '_').replace('~', '-')
            hostname = f"ipmi_{clean_rack}_ru{clean_ru}_node{idx}"
            
            # MAC já está no formato correto (XX:XX:XX:XX:XX:XX)
            entry = f"""host {hostname} {{
  hardware ethernet {mac};
  fixed-address {ip};
}}
"""
            dhcp_entries.append(entry)
            print(f"Node {idx:2d}: {mac} → {ip}")
        
        dhcp_config = '\n'.join(dhcp_entries)
        
        # Mostrar preview
        print("\n" + "="*70)
        print("CONFIGURAÇÃO DHCP GERADA:")
        print("="*70)
        print(dhcp_config)
        
        # Salvar arquivo local
        filename = f"dhcp_{rack_name}_ru{ru_position}.conf"
        filename = filename.replace(' ', '_').replace('~', '-')
        save_dhcp_config(dhcp_config, filename)
        
        print("\n" + "="*70)
        print(f"✓ Configuração salva localmente em: {filename}")
        print("="*70)
        
        # ==================== APLICAÇÃO AUTOMÁTICA NO SERVIDOR DHCP ====================
        print("\n" + "="*70)
        print("APLICANDO CONFIGURAÇÃO NO SERVIDOR DHCP")
        print(f"Servidor: {DHCP_SERVER_IP}")
        print("="*70)
        
        success, message = apply_dhcp_config_to_server(
            config_content=dhcp_config,
            server_ip=DHCP_SERVER_IP,
            username=DHCP_SERVER_USER,
            password=DHCP_SERVER_PASS
        )
        
        if success:
            print(f"\n{'='*70}")
            print("✓ CONFIGURAÇÃO APLICADA COM SUCESSO!")
            print(f"{'='*70}")
            print(f"✓ {message}")
            
            # ==================== VALIDAÇÃO DE IPs ====================
            print("\nAguardando 10 segundos para as IPMIs receberem os IPs...")
            time.sleep(10)
            
            # Validar conectividade com os IPs
            ip_list = list(mac_ip_mapping.values())
            ip_status = validate_ips_with_ping(ip_list, timeout=2, max_retries=3)
            
            # Filtrar apenas IPs ativos
            active_ips = [ip for ip, status in ip_status.items() if status]
            
            if active_ips:
                print(f"\n✓ {len(active_ips)} IPMIs estão respondendo!")
                
                # ==================== COLETA AUTOMÁTICA DE SERIAIS ====================
                print("\n" + "="*70)
                print("COLETANDO SERIAL NUMBERS VIA REDFISH")
                print("="*70)
                
                # Criar mapeamento IP → MAC apenas para IPs ativos
                ip_mac_mapping_active = {}
                for mac, ip in mac_ip_mapping.items():
                    if ip in active_ips:
                        ip_mac_mapping_active[ip] = mac
                
                # Coletar seriais
                mac_serial_mapping = collect_serials_from_ipmis(
                    ip_mac_mapping_active,
                    REDFISH_USER,
                    REDFISH_PASS
                )
                
                # Gerar relatório
                report_filename = f"ipmi_mapping_{rack_name}_ru{ru_position}.txt"
                report_filename = report_filename.replace(' ', '_').replace('~', '-')
                report = generate_mapping_report(mac_serial_mapping, report_filename)
                print(report)
                print(f"✓ Relatório salvo em: {report_filename}")
            else:
                print("\n✗ Nenhuma IPMI está respondendo ainda.")
                print("Aguarde alguns minutos e tente validar manualmente com ping.")
                
        else:
            print(f"\n{'='*70}")
            print("✗ FALHA NA APLICAÇÃO")
            print(f"{'='*70}")
            print(f"✗ Erro: {message}")
            print(f"\nVocê pode aplicar manualmente usando o arquivo: {filename}")
            print("\nPara aplicar manualmente:")
            print(f"1. scp {filename} {DHCP_SERVER_USER}@{DHCP_SERVER_IP}:/tmp/")
            print(f"2. ssh {DHCP_SERVER_USER}@{DHCP_SERVER_IP}")
            print(f"3. sudo cat /tmp/{filename} >> /etc/dhcp/dhcpd.conf")
            print("4. sudo dhcpd -t")
            print("5. sudo systemctl restart isc-dhcp-server")
        
        print("\n" + "="*70)
        print("EXECUÇÃO FINALIZADA")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Erro ao processar planilha: {e}")
        import traceback
        traceback.print_exc()
        print("\nVerifique se:")
        print("  - O arquivo CSV está no formato correto")
        print("  - A coluna 37 (Unnamed: 37) contém os endereços MAC")
        print("  - A coluna 8 contém os endereços IP")
        print("  - Os dados estão a partir da linha 7 (índice 7)")


def process_individual():
    """
    Processa planilha de IPMI no modo INDIVIDUAL
    """
    print("\n" + "="*70)
    print("MODO: INDIVIDUAL")
    print("="*70 + "\n")
    
    # Ler CSV
    df = pd.read_csv(file_name)
    
    rack = df.columns[2]
    rack_name = str(rack)
    
    ipmi_switch_ru = df[['Unnamed: 7']]
    linha7 = ipmi_switch_ru.iloc[7].dropna().astype(str).str.strip().tolist()
    
    # Buscar switch no dicionário
    switches_RU = []
    valores = df[rack].iloc[1:5].dropna().astype(str).str.strip().tolist()
    switches_RU.extend(valores)
    print(f"Switches RU encontrados: {switches_RU}")
    
    label = df.columns[3]
    switch_label = []
    valores = df[label].iloc[1:5].dropna().astype(str).str.strip().tolist()
    switch_label.extend(valores)
    print(f"Labels de switch encontrados: {switch_label}")
    
    merged_dict = {ru: label for ru, label in zip(switches_RU, switch_label)}
    
    if linha7[0] not in merged_dict:
        print("Switch não encontrado no dicionário.")
        return
    
    ipmi_switch_name = merged_dict[linha7[0]]
    
    # Busca o device no Netbox pelo nome
    try:
        device_obj = nb.dcim.devices.get(name=ipmi_switch_name)
        if not device_obj:
            print(f"Switch {ipmi_switch_name} não encontrado no Netbox")
            return
        
        device_type_obj = device_obj.device_type
        primary_ipv4 = device_obj.primary_ip4
        
        if not primary_ipv4:
            print(f"Switch {ipmi_switch_name} não tem IP configurado no Netbox")
            return
        
        host = str(primary_ipv4).split('/')[0]
        
        if "nexus" in str(device_type_obj.manufacturer).lower():
            device_os = "cisco_nxos"
        else:
            device_os = "cisco_ios"
        
        switch = {
            "device_type": device_os,
            "host": host,
            "username": username,
            "password": password,
            "timeout": 120,
            "session_timeout": 120,
            "auth_timeout": 120,
            "banner_timeout": 120,
            "blocking_timeout": 120,
            "conn_timeout": 120,
            "verbose": False,
            "fast_cli": False,
            "global_delay_factor": 2
        }
        
        print(f"\nConectando no switch {ipmi_switch_name} ({host})...")
        print("="*70 + "\n")
        
        # ==================== COLETA DE MACs E IPs ====================
        # Coletar portas e IPs da planilha (a partir da linha 7)
        ipmi_port_col = df[['Unnamed: 8']]
        ipmi_ip_col = df[['Unnamed: 9']]
        
        mac_ip_mapping = []  # Lista de dicionários {mac, ip, port}
        
        for i in range(7, len(ipmi_port_col)):
            # Extrair porta
            port_row = ipmi_port_col.iloc[i].dropna().astype(str).str.strip().tolist()
            if not port_row:
                continue
            port = port_row[0]
            
            # Extrair IP
            ip_row = ipmi_ip_col.iloc[i].dropna().astype(str).str.strip().tolist()
            if not ip_row:
                continue
            ip = ip_row[0]
            
            print(f"Coletando MACs da porta Eth1/{port} (IP destino: {ip})...")
            
            # Buscar MACs nessa porta
            output = get_mac_ipmi(switch, port)
            
            if output:
                print(f"\nDEBUG - Output recebido ({len(output)} chars):")
                print(f"Primeiros 300 chars: {output[:300]}")
                
                macs = extract_macs_from_output(output)
                print(f"DEBUG - MACs extraídos: {macs}\n")
                
                if macs:
                    # Pegar apenas o primeiro MAC (assumindo 1 MAC por porta)
                    mac = macs[0]
                    mac_ip_mapping.append({
                        'mac': mac,
                        'ip': ip,
                        'port': port
                    })
                    print(f"✓ MAC encontrado: {mac}\n")
                else:
                    print(f"✗ Nenhum MAC encontrado na porta Eth1/{port}\n")
            else:
                print(f"✗ Erro ao buscar MACs da porta Eth1/{port}\n")
        
        if not mac_ip_mapping:
            print("\n✗ Nenhum MAC foi encontrado. Verifique as conexões.")
            return
        
        # ==================== PROCESSAMENTO DHCP ====================
        print("\n" + "="*70)
        print("PROCESSANDO CONFIGURAÇÃO DHCP")
        print("="*70)
        print(f"\n✓ {len(mac_ip_mapping)} MACs encontrados e mapeados com IPs\n")
        
        # Gerar configuração DHCP manualmente com mapeamento correto
        dhcp_entries = []
        for idx, mapping in enumerate(mac_ip_mapping, 1):
            mac_dhcp = format_mac_for_dhcp(mapping['mac'])
            ip = mapping['ip']
            
            # Limpar rack_name e ru_position
            clean_rack = rack_name.replace(' ', '_').replace('~', '-')
            clean_ru = linha7[0].replace(' ', '_').replace('~', '-')
            hostname = f"ipmi_{clean_rack}_ru{clean_ru}_node{idx}"
            
            entry = f"""host {hostname} {{
  hardware ethernet {mac_dhcp};
  fixed-address {ip};
}}
"""
            dhcp_entries.append(entry)
            print(f"Node {idx}: {mac_dhcp} → {ip} (Porta: Eth1/{mapping['port']})")
        
        dhcp_config = '\n'.join(dhcp_entries)
        
        # Mostrar preview
        print("\n" + "="*70)
        print("CONFIGURAÇÃO DHCP GERADA:")
        print("="*70)
        print(dhcp_config)
        
        # Salvar arquivo local
        filename = f"dhcp_{rack_name}_ru{linha7[0]}.conf"
        filename = filename.replace(' ', '_').replace('~', '-')
        save_dhcp_config(dhcp_config, filename)
        
        print("\n" + "="*70)
        print(f"✓ Configuração salva localmente em: {filename}")
        print("="*70)
        
        # ==================== APLICAÇÃO AUTOMÁTICA NO SERVIDOR DHCP ====================
        print("\n" + "="*70)
        print("APLICANDO CONFIGURAÇÃO NO SERVIDOR DHCP")
        print(f"Servidor: {DHCP_SERVER_IP}")
        print("="*70)
        
        success, message = apply_dhcp_config_to_server(
            config_content=dhcp_config,
            server_ip=DHCP_SERVER_IP,
            username=DHCP_SERVER_USER,
            password=DHCP_SERVER_PASS
        )
        
        if success:
            print(f"\n{'='*70}")
            print("✓ CONFIGURAÇÃO APLICADA COM SUCESSO!")
            print(f"{'='*70}")
            print(f"✓ {message}")
            
            # ==================== VALIDAÇÃO DE IPs ====================
            print("\nAguardando 10 segundos para as IPMIs receberem os IPs...")
            time.sleep(10)
            
            # Validar conectividade
            ip_list = [m['ip'] for m in mac_ip_mapping]
            ip_status = validate_ips_with_ping(ip_list, timeout=2, max_retries=3)
            
            # Filtrar apenas IPs ativos
            active_ips = [ip for ip, status in ip_status.items() if status]
            
            if active_ips:
                print(f"\n✓ {len(active_ips)} IPMIs estão respondendo!")
                
                # ==================== COLETA AUTOMÁTICA DE SERIAIS ====================
                print("\n" + "="*70)
                print("COLETANDO SERIAL NUMBERS VIA REDFISH")
                print("="*70)
                
                # Criar mapeamento IP → MAC apenas para IPs ativos
                ip_mac_mapping = {}
                for mapping in mac_ip_mapping:
                    if mapping['ip'] in active_ips:
                        ip_mac_mapping[mapping['ip']] = mapping['mac']
                
                # Coletar seriais
                mac_serial_mapping = collect_serials_from_ipmis(
                    ip_mac_mapping,
                    REDFISH_USER,
                    REDFISH_PASS
                )
                
                # Gerar relatório
                report_filename = f"ipmi_mapping_{rack_name}_ru{linha7[0]}.txt"
                report_filename = report_filename.replace(' ', '_').replace('~', '-')
                report = generate_mapping_report(mac_serial_mapping, report_filename)
                print(report)
                print(f"✓ Relatório salvo em: {report_filename}")
            else:
                print("\n✗ Nenhuma IPMI está respondendo ainda.")
                print("Aguarde alguns minutos e tente validar manualmente com ping.")
        else:
            print(f"\n{'='*70}")
            print("✗ FALHA NA APLICAÇÃO")
            print(f"{'='*70}")
            print(f"✗ Erro: {message}")
        
        print("\n" + "="*70)
        print("EXECUÇÃO FINALIZADA")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Erro: {e}")
        import traceback
        traceback.print_exc()


# ==================== FUNÇÃO PRINCIPAL ====================

def main():
    """
    Função principal que determina qual modo executar
    """
    print("\n" + "="*70)
    print("SCRIPT UNIFICADO DE IPMI - CHASSIS E INDIVIDUAL")
    print("="*70)
    
    # Obter opção da variável de ambiente
    option = "individual"
    
    if not option:
        print("\n✗ ERRO: Variável de ambiente RD_OPTION_TESTE não definida!")
        print("\nPara executar este script, você deve definir a variável de ambiente:")
        print("  export RD_OPTION_TESTE=chassis   (para modo chassis)")
        print("  export RD_OPTION_TESTE=individual   (para modo individual)")
        print("\n" + "="*70 + "\n")
        sys.exit(1)
    
    # Normalizar opção (lowercase e remover espaços)
    option = option.lower().strip()
    
    print(f"\nOpção selecionada: {option.upper()}")
    print("="*70)
    
    # Executar função apropriada baseada na opção
    if option == "chassis":
        process_chassis()
    elif option == "individual":
        process_individual()
    else:
        print(f"\n✗ ERRO: Opção inválida '{option}'!")
        print("\nOpções válidas:")
        print("  - chassis")
        print("  - individual")
        print("\nDefina a variável de ambiente corretamente:")
        print("  export RD_OPTION_TESTE=chassis")
        print("  ou")
        print("  export RD_OPTION_TESTE=individual")
        print("\n" + "="*70 + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()