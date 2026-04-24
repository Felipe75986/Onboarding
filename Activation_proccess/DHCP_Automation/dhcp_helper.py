"""
Módulo auxiliar para geração de configurações DHCP a partir de MACs coletados
"""
import re
import paramiko
from datetime import datetime
import subprocess
import time
import requests
import json
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


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
    Adiciona as entradas APENAS na seção de hosts, preservando o resto do arquivo
    
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
        
        # 1. Fazer backup do arquivo atual
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_cmd = f"sudo cp /etc/dhcp/dhcpd.conf /etc/dhcp/backup_files/dhcpd.conf.bak.{timestamp}"
        stdin, stdout, stderr = ssh.exec_command(backup_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            return False, f"Erro ao fazer backup: {error}"
        
        print(f"✓ Backup criado: dhcpd.conf.bak.{timestamp}")
        
        # 2. Ler configuração atual
        read_cmd = "sudo cat /etc/dhcp/dhcpd.conf"
        stdin, stdout, stderr = ssh.exec_command(read_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        current_config = stdout.read().decode()
        
        print("✓ Configuração atual lida")
        
        # 3. Adicionar nova configuração ao final (após a seção de hosts)
        new_section = f"\n# Hosts adicionados automaticamente em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        new_section += config_content
        new_config = current_config + new_section
        
        # 4. Criar arquivo temporário em /etc/dhcp/ usando comandos shell
        temp_file = f"/etc/dhcp/dhcpd.conf.tmp.{timestamp}"
        
        # Criar o arquivo usando tee com sudo (permite escrever em /etc/dhcp/)
        # Importante: NÃO usar stdin.write() após a senha para evitar incluí-la no arquivo
        create_cmd = f'sudo -S tee {temp_file} > /dev/null'
        stdin, stdout, stderr = ssh.exec_command(create_cmd)
        ##stdin.write(password + '\n')
        stdin.flush()
        # Aguardar prompt do sudo processar
        time.sleep(1.5)
        # Agora escrever o conteúdo
        stdin.write(new_config)
        stdin.channel.shutdown_write()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao criar arquivo temporário: {error}"
        
        print(f"✓ Nova configuração criada em {temp_file}")
        
        # 5. Validar configuração
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
        
        # 6. Aplicar configuração
        apply_cmd = f"sudo mv {temp_file} /etc/dhcp/dhcpd.conf"
        stdin, stdout, stderr = ssh.exec_command(apply_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao aplicar configuração: {error}"
        
        print("✓ Configuração aplicada")
        
        # 7. Reiniciar serviço DHCP
        restart_cmd = "sudo systemctl restart isc-dhcp-server"
        stdin, stdout, stderr = ssh.exec_command(restart_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode()
            ssh.close()
            return False, f"Erro ao reiniciar serviço: {error}"
        
        print("✓ Serviço DHCP reiniciado")
        
        # 8. Verificar status do serviço
        status_cmd = "sudo systemctl is-active isc-dhcp-server"
        stdin, stdout, stderr = ssh.exec_command(status_cmd)
        stdin.write(password + '\n')
        stdin.flush()
        status = stdout.read().decode().strip()
        
        ssh.close()
        
        if status == "active":
            print("\n" + "="*70)
            print("✓ CONFIGURAÇÃO APLICADA COM SUCESSO!")
            print("="*70)
            return True, "Configuração aplicada e serviço reiniciado com sucesso"
        else:
            return False, f"Serviço não está ativo. Status: {status}"
            
    except paramiko.AuthenticationException:
        return False, "Erro de autenticação SSH. Verifique usuário/senha."
    except paramiko.SSHException as e:
        return False, f"Erro SSH: {str(e)}"
    except Exception as e:
        return False, f"Erro inesperado: {str(e)}"
    

def validate_ips_with_ping(ip_list, timeout=2, max_retries=3):
    """
    Valida se os IPs estão respondendo via ping
    
    Args:
        ip_list (list): Lista de IPs para validar
        timeout (int): Timeout do ping em segundos
        max_retries (int): Número máximo de tentativas
        
    Returns:
        dict: {ip: bool} indicando se cada IP está ativo
    """
    print(f"\n{'='*70}")
    print("VALIDANDO IPs VIA PING")
    print(f"{'='*70}\n")
    print("Aguarde, testando conectividade com as IPMIs...")
    print("(Isso pode levar alguns minutos enquanto os IPs são atribuídos)\n")
    
    results = {}
    
    for ip in ip_list:
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                # Ping usando subprocess (funciona em Linux/Windows/Mac)
                import os
                param = "-n" if os.name == "nt" else "-c"
                timeout_param = "-w" if os.name == "nt" else "-W"
                timeout_value = str(timeout * 1000 if os.name == "nt" else timeout)
                
                command = ["ping", param, "1", timeout_param, timeout_value, ip]
                
                result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                if result.returncode == 0:
                    print(f"✓ {ip} - ATIVO")
                    success = True
                    break
                else:
                    if attempt < max_retries:
                        print(f"  {ip} - Tentativa {attempt}/{max_retries} falhou, aguardando 5s...")
                        time.sleep(5)
            except Exception as e:
                print(f"✗ {ip} - Erro ao testar: {e}")
                break
        
        if not success:
            print(f"✗ {ip} - SEM RESPOSTA após {max_retries} tentativas")
        
        results[ip] = success
    
    # Resumo
    active_count = sum(results.values())
    total_count = len(results)
    
    print(f"\n{'='*70}")
    print(f"RESUMO: {active_count}/{total_count} IPs ativos")
    print(f"{'='*70}\n")
    
    return results


def get_serial_from_redfish(ip, username="ADMIN", password="QFLGXTFDXA", timeout=10):
    """
    Obtém o serial number via API Redfish
    
    Args:
        ip (str): IP da IPMI
        username (str): Usuário Redfish
        password (str): Senha Redfish
        timeout (int): Timeout da requisição
        
    Returns:
        str: Serial number ou None se falhar
    """
    url = f"https://{ip}/redfish/v1/Systems/1"
    
    try:
        response = requests.get(
            url,
            auth=(username, password),
            verify=False,
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            serial = data.get("SerialNumber")
            return serial
        else:
            return None
            
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        return None


def collect_serials_from_ipmis(ip_mac_mapping, redfish_user="ADMIN", redfish_pass="QFLGXTFDXA"):
    """
    Coleta serial numbers de todas as IPMIs e mapeia com MACs
    
    Args:
        ip_mac_mapping (dict): {ip: mac} mapeamento de IP para MAC
        redfish_user (str): Usuário Redfish
        redfish_pass (str): Senha Redfish
        
    Returns:
        dict: {mac: {"ip": ip, "serial": serial, "status": status}}
    """
    print(f"\n{'='*70}")
    print("COLETANDO SERIAL NUMBERS VIA REDFISH")
    print(f"{'='*70}\n")
    
    results = {}
    
    for ip, mac in ip_mac_mapping.items():
        print(f"Consultando {ip} ({mac})...", end=" ")
        
        serial = get_serial_from_redfish(ip, redfish_user, redfish_pass)
        
        if serial:
            print(f"✓ Serial: {serial}")
            results[mac] = {
                "ip": ip,
                "serial": serial,
                "status": "success"
            }
        else:
            print(f"✗ Falha ao obter serial")
            results[mac] = {
                "ip": ip,
                "serial": None,
                "status": "failed"
            }
    
    # Resumo
    success_count = sum(1 for v in results.values() if v["status"] == "success")
    total_count = len(results)
    
    print(f"\n{'='*70}")
    print(f"RESUMO: {success_count}/{total_count} seriais coletados com sucesso")
    print(f"{'='*70}\n")
    
    return results


def generate_mapping_report(mac_serial_mapping, filename="ipmi_mapping_report.txt"):
    """
    Gera relatório final com mapeamento MAC → IP → Serial
    
    Args:
        mac_serial_mapping (dict): Resultado de collect_serials_from_ipmis
        filename (str): Nome do arquivo para salvar
        
    Returns:
        str: Conteúdo do relatório
    """
    report = f"""
{'='*70}
RELATÓRIO DE MAPEAMENTO IPMI
Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*70}

"""
    
    # Ordenar por IP
    sorted_items = sorted(mac_serial_mapping.items(), key=lambda x: x[1]["ip"])
    
    for idx, (mac, info) in enumerate(sorted_items, 1):
        mac_formatted = mac.replace('.', '').upper()
        mac_formatted = ':'.join([mac_formatted[i:i+2] for i in range(0, 12, 2)])
        
        status_symbol = "✓" if info["status"] == "success" else "✗"
        serial = info["serial"] if info["serial"] else "N/A"
        
        report += f"""
Node {idx:2d}:
  Status:      {status_symbol} {info['status'].upper()}
  MAC Address: {mac_formatted}
  IP Address:  {info['ip']}
  Serial:      {serial}
{'-'*70}
"""
    
    # Estatísticas
    total = len(mac_serial_mapping)
    success = sum(1 for v in mac_serial_mapping.values() if v["status"] == "success")
    failed = total - success
    
    report += f"""
{'='*70}
ESTATÍSTICAS
{'='*70}
Total de Nodes:     {total}
Sucesso:            {success}
Falhas:             {failed}
Taxa de Sucesso:    {(success/total*100):.1f}%
{'='*70}
"""
    
    # Salvar em arquivo
    with open(filename, 'w') as f:
        f.write(report)
    
    return report