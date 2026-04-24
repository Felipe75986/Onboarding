import pandas as pd
import subprocess

def run_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True
        )

        if result.returncode != 0:
            print("❌ Erro ao executar comando:")
            print(result.stderr.strip())
            return None

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        print(f"⏱️ Timeout executando comando: {cmd}")
        return None

df = pd.read_csv("Copy of [ASH] 10x m4.small (Rack AI47 - RU 31~33) - Onboarding.csv")

user = "ADMIN"
passwords = df['Unnamed: 6'].iloc[7:]
ips = df.columns[8]
ipmi_ips = df[ips].iloc[7:].dropna().astype(str).str.strip().tolist()

mac_addresses = []
valores = df['Unnamed: 37'].iloc[7:]
mac_addresses.extend(valores)

def merge_MAC_IPS(mac_addresses, ipmi_ips):
    merged_dict = {}
    for mac, ip in zip(mac_addresses, ipmi_ips):
        merged_dict[mac] = ip
    return merged_dict

merged_dict = merge_MAC_IPS(mac_addresses, ipmi_ips)
print(merged_dict)


#ipmi_ip = ipmi_ips[0]
#cmd = f"ipmitool -I lanplus -H {ipmi_ip} -U {user} -P {passwords.iloc[0]} lan print | grep -i \"MAC Address\""
#output = run_cmd(cmd)
#mac = output.split()[-1]




#for i in ips:
#    ipmi_ip = str(i).strip()
#    print(f"Conectando ao IPMI {ipmi_ip}...")
#    cmd = f"ipmitool -I lanplus -H {ipmi_ip} -U {user} -P {passwords} lan print"
#    output = run_cmd(cmd)
    