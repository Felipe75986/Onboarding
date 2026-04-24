import pandas as pd
from netmiko import ConnectHandler
import csv
import re

def main():
    # --- Credenciais ---
    switch_ip = input("IP do switch: ")
    username = input("Usuário: ")
    password = input("Senha: ")

    device = {
        "device_type": "cisco_nxos",
        "ip": switch_ip,
        "username": username,
        "password": password,
    }

    print("\nConectando ao switch...\n")
    conn = ConnectHandler(**device)

    print("Coletando VLANs com 'show vlan brief'...\n")
    vlan_output = conn.send_command("show vlan brief")

    # Regex captura VLAN ID + Nome
    vlan_pattern = r"^\s*(\d+)\s+([A-Za-z0-9\-_]+)"
    vlans = re.findall(vlan_pattern, vlan_output, re.MULTILINE)

    results = []

    for vlan_id, vlan_name in vlans:
        print(f"Verificando MACs da VLAN {vlan_id}...")

        mac_cmd = f"show mac address-table vlan {vlan_id}"
        mac_output = conn.send_command(mac_cmd)

        # Capturar MAC + Interface
        mac_pattern = r"([0-9a-fA-F\.]{14})\s+\S+\s+(\S+)"
        mac_entries = re.findall(mac_pattern, mac_output)

        # Se houver mais de 2 MACs, pega apenas os dois primeiros
        mac_entries = mac_entries[:2] if mac_entries else [("NONE", "NONE")]

        for mac, interface in mac_entries:
            results.append([vlan_id, vlan_name, mac, interface])

    conn.disconnect()

    # --- Criar CSV ---
    csv_filename = "mac_report.csv"
    print(f"\nSalvando resultados em {csv_filename}...\n")

    with open(csv_filename, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["VLAN", "Name", "MAC Address", "Interface"])
        writer.writerows(results)

    print("Concluído! Arquivo mac_report.csv gerado.\n")




df = pd.read_csv("[NRT10 - TYO] 1x g4.6k.large (Rack 310.C08.05 - RU 34~37) - Delivery.csv")
    
rack = df.columns[2]
rack_name = str(rack)
print (f"Rack: {rack_name}")
    
ipmi_switch_ru = df[['Unnamed: 7']]
linha7 = ipmi_switch_ru.iloc[7].dropna().astype(str).str.strip().tolist()
print(f"Switch RU: {linha7[0]}")
    
    # Buscar switch no dicionário
switches_RU = []
valores = df[rack].iloc[1:4].dropna().astype(str).str.strip().tolist()
switches_RU.extend(valores)
print(f"Switches RU: {switches_RU}")
    
label = df.columns[3]
switch_label = []
valores = df[label].iloc[1:4].dropna().astype(str).str.strip().tolist()
switch_label.extend(valores)
print(f"Switch Labels: {switch_label}")
    
merged_dict = {ru: label for ru, label in zip(switches_RU, switch_label)}
print(f"Dicionário RU -> Label: {merged_dict}")
    
if linha7[0] not in merged_dict:
    print("Switch não encontrado no dicionário.")
    
ipmi_switch_name = merged_dict[linha7[0]]