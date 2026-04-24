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
    generate_mapping_report
)

# ==================== CONFIGURAÇÕES ====================
url = "https://netbox.latitude.co"
token = "91c2679a21ccbf55cab082d91f7c59983445db82"
username = "felipe.gomes"
password = "Sucodemilho@2005"
secret = "21M03t@oB8~06"




# Configurações do servidor DHCP - AJUSTE AQUI
DHCP_SERVER_IP = "10.90.10.30"       # IP do servidor DHCP
DHCP_SERVER_USER = "ubuntu"     # Usuário SSH
DHCP_SERVER_PASS = "Netops@123"       # Senha SSH

# ==================== SETUP NETBOX ====================
nb = pynetbox.api(url=url, token=token, threading=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.verify = False
nb.http_session = session


def get_mac_ipmi(device, port):
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
    
    IPMI_IP_collum = df[['Unnamed: 9']]
    ip_mask = IPMI_IP_collum.iloc[7].dropna().astype(str).str.strip().tolist()
    base_ip = ip_mask[0].split('/')[0]
    print (base_ip)
    DHCP_BASE_IP = ".".join(base_ip.split(".")[:3])
    print (DHCP_BASE_IP)

    DHCP_START_HOST = int(base_ip.split(".")[3])


    ipmi_switch_ru = df[['Unnamed: 7']]
    linha7 = ipmi_switch_ru.iloc[7].dropna().astype(str).str.strip().tolist()
    rack = df.columns[2]
    rack_name = str(rack)

    rack_ru = df[[rack_name]]
    linha7_rack_ru = rack_ru.iloc[7].dropna().astype(str).str.strip().tolist()

    ipmi_port = df[['Unnamed: 8']]
    port = ipmi_port.iloc[7].dropna().astype(str).str.strip().tolist()
    
    switches_RU = []
    valores = df[rack].iloc[1:4].dropna().astype(str).str.strip().tolist()
    switches_RU.extend(valores)
    

    label = df.columns[3]
    switch_label = []
    valores = df[label].iloc[1:4].dropna().astype(str).str.strip().tolist()
    switch_label.extend(valores)
    
    def merge_switch_RU(switches_RU, switch_label):
        merged_dict = {}
        for ru, label in zip(switches_RU, switch_label):
            merged_dict[ru] = label
        return merged_dict
    
    merged_dict = merge_switch_RU(switches_RU, switch_label)
    

    if linha7[0] in merged_dict:
        ipmi_switch_name = merged_dict[linha7[0]]
    else:
        print("Switch não encontrado no dicionário.")
        return
    
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
        
        print(f"Conectando no switch {ipmi_switch_name} ({host})...")
        
        # Buscar MACs
        output = get_mac_ipmi(switch, port[0])
        
        if not output:
            print("Erro ao obter output do switch")
            return
        
        # ==================== PROCESSAMENTO DHCP ====================
        print("\n" + "="*70)
        print("PROCESSANDO CONFIGURAÇÃO DHCP")
        print("="*70)
        
        # Extrair MACs do output
        mac_list = extract_macs_from_output(output)
        print(f"\n✓ {len(mac_list)} MACs encontrados")
        
        # Gerar configuração DHCP
        dhcp_config = generate_dhcp_entries(
            mac_list=mac_list,
            base_ip=DHCP_BASE_IP,
            start_host=DHCP_START_HOST,
            rack_name=rack_name,
            ru_position=linha7_rack_ru[0]
        )
        
        # Mostrar preview
        print("\n" + "="*70)
        print("CONFIGURAÇÃO DHCP GERADA:")
        print("="*70)
        print(dhcp_config)
        
        # Salvar arquivo local
        filename = f"dhcp_{rack_name}_ru{linha7[0]}.conf"
        save_dhcp_config(dhcp_config, filename)
        
        print("\n" + "="*70)
        print(f"✓ Configuração salva localmente em: {filename}")
        print("="*70)
        
        # ==================== APLICAÇÃO NO SERVIDOR DHCP ====================
        print("\nDeseja aplicar a configuração automaticamente no servidor DHCP?")
        print(f"Servidor: {DHCP_SERVER_IP}")
        print(f"Usuário: {DHCP_SERVER_USER}")
        resposta = input("\nDigite 's' para aplicar ou 'n' para aplicar manualmente: ").lower().strip()
        
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
                print("✓ SUCESSO!")
                print(f"{'='*70}")
                print(f"✓ {message}")
                print(f"\nOs seguintes hosts agora receberão IPs via DHCP:")
                for idx, mac in enumerate(mac_list, 1):
                    ip = f"{DHCP_BASE_IP}.{DHCP_START_HOST + idx - 1}"
                    print(f"  - Node {idx}: {ip}")
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
        else:
            print("\n" + "="*70)
            print("APLICAÇÃO MANUAL")
            print("="*70)
            print(f"\nConfiguração NÃO foi aplicada automaticamente.")
            print(f"Use o arquivo local: {filename}")
            print("\nPara aplicar manualmente no servidor DHCP:")
            print(f"1. scp {filename} {DHCP_SERVER_USER}@{DHCP_SERVER_IP}:/tmp/")
            print(f"2. ssh {DHCP_SERVER_USER}@{DHCP_SERVER_IP}")
            print(f"3. sudo cat /tmp/{filename} >> /etc/dhcp/dhcpd.conf")
            print("4. sudo dhcpd -t")
            print("5. sudo systemctl restart isc-dhcp-server")
        
        print("\n" + "="*70)
        print("EXECUÇÃO FINALIZADA")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Erro ao buscar device no Netbox: {e}")


if __name__ == "__main__":
    main()