import pandas as pd
from netmiko import ConnectHandler
import pynetbox
import urllib3
import requests

# Importar funções do dhcp_helper
from dhcp_helper import (
    extract_macs_from_output, 
    generate_dhcp_entries,
    save_dhcp_config,
    apply_dhcp_config_to_server,
    validate_ips_with_ping,
    collect_serials_from_ipmis,
    generate_mapping_report,
    format_mac_for_dhcp
)

# ==================== CONFIGURAÇÕES ====================
url = "https://netbox.latitude.co"
token = "91c2679a21ccbf55cab082d91f7c59983445db82"
username = "felipe.gomes"
password = "Sucodemilho@2005"
secret = "21M03t@oB8~06"

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
session = requests.Session()
session.verify = False
nb.http_session = session


def get_mac_ipmi(device, port):
    """Conecta no switch e busca os MAC addresses"""
    try:
        with ConnectHandler(**device) as connection:
            prompt = connection.find_prompt()
            hostname = prompt[0:-1]
            connection.send_command_timing("enable")
            connection.send_command_timing(secret)
            output = connection.send_command(f"show mac address interface ethernet1/{port}")
            print(output)
            return output
    except Exception as e:
        print(f'{device["host"]}: Erro ao conectar - {e}')
        return None


def main():
    # Ler CSV
    df = pd.read_csv('[DAL] 4x m4.large (Rack B12 - RU 06~07) - Delivery.csv')
    
    # Extrair informações básicas
    rack = df.columns[2]
    rack_name = str(rack)
    
    ipmi_switch_ru = df[['Unnamed: 7']]
    linha7 = ipmi_switch_ru.iloc[7].dropna().astype(str).str.strip().tolist()

    rack_ru = df[[rack_name]]
    linha7_rack_ru = rack_ru.iloc[7].dropna().astype(str).str.strip().tolist()
    
    # Buscar switch no dicionário
    switches_RU = []
    valores = df[rack].iloc[1:4].dropna().astype(str).str.strip().tolist()
    switches_RU.extend(valores)
    
    label = df.columns[3]
    switch_label = []
    valores = df[label].iloc[1:4].dropna().astype(str).str.strip().tolist()
    switch_label.extend(valores)
    
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
            "timeout": 60*2,
            "verbose": False
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
                macs = extract_macs_from_output(output)
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
            clean_ru = linha7_rack_ru[0].replace(' ', '_').replace('~', '-')
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
        filename = f"dhcp_{rack_name}_ru{linha7_rack_ru[0]}.conf"
        filename = filename.replace(' ', '_').replace('~', '-')
        save_dhcp_config(dhcp_config, filename)
        
        print("\n" + "="*70)
        print(f"✓ Configuração salva localmente em: {filename}")
        print("="*70)
        
        # ==================== APLICAÇÃO NO SERVIDOR DHCP ====================
        print("\nDeseja aplicar a configuração automaticamente no servidor DHCP?")
        print(f"Servidor: {DHCP_SERVER_IP}")
        print(f"Usuário: {DHCP_SERVER_USER}")
        resposta = input("\nDigite 's' para aplicar ou 'n' para pular: ").lower().strip()
        
        if resposta == 's':
            print("\n" + "="*70)
            print("APLICANDO CONFIGURAÇÃO NO SERVIDOR DHCP")
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
                import time
                time.sleep(10)
                
                # Validar conectividade
                ip_list = [m['ip'] for m in mac_ip_mapping]
                ip_status = validate_ips_with_ping(ip_list, timeout=2, max_retries=3)
                
                # Filtrar apenas IPs ativos
                active_ips = [ip for ip, status in ip_status.items() if status]
                
                if active_ips:
                    print(f"\n✓ {len(active_ips)} IPMIs estão respondendo!")
                    
                    # ==================== COLETA DE SERIAIS ====================
                    print("\nDeseja coletar os serial numbers via Redfish?")
                    resposta_serial = input("Digite 's' para coletar ou 'n' para pular: ").lower().strip()
                    
                    if resposta_serial == 's':
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
                        report_filename = f"ipmi_mapping_{rack_name}_ru{linha7_rack_ru[0]}.txt"
                        report_filename = report_filename.replace(' ', '_').replace('~', '-')
                        report = generate_mapping_report(mac_serial_mapping, report_filename)
                        print(report)
                        print(f"✓ Relatório salvo em: {report_filename}")
                    else:
                        print("\n⚠ Coleta de seriais ignorada.")
                else:
                    print("\n✗ Nenhuma IPMI está respondendo ainda.")
                    print("Aguarde alguns minutos e tente validar manualmente com ping.")
            else:
                print(f"\n{'='*70}")
                print("✗ FALHA NA APLICAÇÃO")
                print(f"{'='*70}")
                print(f"✗ Erro: {message}")
        else:
            print("\n⚠ Aplicação no servidor DHCP ignorada.")
        
        print("\n" + "="*70)
        print("EXECUÇÃO FINALIZADA")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()