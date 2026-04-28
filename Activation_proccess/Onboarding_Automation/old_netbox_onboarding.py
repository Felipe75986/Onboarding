import os
import csv
import ipaddress
import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import json


# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment variables
file_name = os.getenv('RD_FILE_PLANILHA')
token = os.getenv('RD_OPTION_NETBOXTOKEN')
reserva = os.getenv('RD_OPTION_RESERVA')
url = "https://netbox.latitude.co"
url_api = f'{url}/api'

# Request headers
headers = {
    "Authorization": f"Token {token}",
    "Content-Type": "application/json"
}

# Cria sessão com retry automático
session = requests.Session()

retry_strategy = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
)

adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)


def csv_import_info(file_name: str) -> tuple:
    """Extract information from CSV file."""
    print("Extracting information from spreadsheet...\n")
    if reserva == "reserved":
        status = "planned"
    else:
        status = "active"

    with open(file_name, "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        rows = list(reader)
        site = rows[0][1]
        rack = rows[2][1]
        ticket = rows[3][4]
        platform = rows[3][1]
        chassis_name = rows[4][1].strip()
        chassis_type = rows[4][4].strip()
        chassis_ru = rows[4][7].strip()
        proc_jira = rows[5][1].strip()

        if chassis_name:
            chassis = {
                "name": chassis_name,
                "device_type": chassis_type,
                "role": {"name": "Enclosure"},
                "site": site.strip(),
                "rack": rack.strip(),
                "position": chassis_ru,
                "custom_fields": {'procurement_ticket_url': proc_jira},
                "face": "front",
                "status": status
            }
        else:
            chassis=None

    with open(file_name, "r") as file:
        reader = csv.reader(file)
        for _ in range(8):
            next(reader)
        devices = []
        x=1
        for row in reader:
            devices_temp = {
                "name": row[0].strip(),
                "device_type": row[3].strip(),
                "platform":{"name":platform.strip()},
                "rack": rack.strip(),
                "position": row[4].strip(),
                "custom_fields": {'automation_instance': row[2].strip(), 'procurement_ticket_url':proc_jira},
                "role": {"name": "Bare Metal"},
                "site": site.strip(),
                "status": status,
                "serial": row[5].strip(),
                "ip_ipmi": row[8].strip(),
                "ip_eth0": row[9].strip(),
                "ipv6_eth0": row[11].strip(),
                "vlan": row[13].strip(),
                "vlan_group": row[14].strip(),
                # "mac_ipmi": row[36].strip(),
                # "mac_eth0": row[37].strip(),
                # "mac_pxe": row[38].strip(),
                "slot":x
            }
            devices.append(devices_temp)
            x+=1

    return devices, ticket, site, chassis

def get_single_device(device_id):
    """Get a single device by ID."""
    endpoint = f'dcim/devices/{device_id}/'
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    try:
        response = session.get(f'{url_api}/{endpoint}', headers=headers, verify=False)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f'Error retrieving device {device_id}: {e}')
        return None
def get_netbox_data(url_api, token, endpoint):
    endpoint = endpoint.lstrip('/')
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    all_results = []
    next_url = f'{url_api.rstrip("/")}/{endpoint}'
    while next_url:
        try:
            response = session.get(next_url, headers=headers, verify=False)
            response.raise_for_status()  # Levanta exceção para códigos de erro
            data = response.json()
            if 'results' in data:
                all_results.extend(data['results'])
            next_url = data.get('next')
        except requests.exceptions.RequestException as e:
            print(f'Error on retrieving data from Netbox: {e.response.status_code} - {e.response.text}')
            break
    return all_results

def create_netbox_data(url_api, token, endpoint, data):
    endpoint = endpoint.lstrip('/')
    post_url = f'{url_api.rstrip("/")}/{endpoint}'
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    try:
        response = session.post(post_url, headers=headers, json=data, verify=False)
        response.raise_for_status()
        print("Created")
        return response
    except requests.exceptions.RequestException as e:
        print(f'Error in creating object: {e.response.status_code} - {e.response.text}')
        return None

def update_netbox_data(url_api, token, endpoint, data):
    endpoint = endpoint.lstrip('/')
    patch_url = f'{url_api.rstrip("/")}/{endpoint}'
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    try:
        response = session.patch(patch_url, headers=headers, json=data, verify=False)
        response.raise_for_status()
        print("OK")
        return response
    except requests.exceptions.RequestException as e:
        print(f'Error in updating object: {e.response.status_code} - {e.response.text}')
        return None

def get_device_by_name(device_name):
    """Obtém o dispositivo pelo nome via API do NetBox"""
    try:
        response = session.get(f"{url_api}/dcim/devices/?name={device_name}", headers=headers, verify=False)
        if response.status_code == 200:
            devices = response.json()["results"]
            return devices[0] if devices else None
        else:
            print(f"An error occurred while retrieving the device: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None
def get_netbox_types():
    """Get device types, platforms, roles and sites from Netbox."""
    print("Synchronizing with Netbox database...")

    device_types = get_netbox_data(url_api, token,endpoint='dcim/device-types/')
    device_roles = get_netbox_data(url_api, token,endpoint='dcim/device-roles/')
    sites = get_netbox_data(url_api, token,endpoint='dcim/sites/')
    device_platform = get_netbox_data(url_api, token,endpoint='dcim/platforms/')


    devices_type_dict = {dt['model']: dt['id'] for dt in device_types}
    devices_role_dict = {dr['name']: dr['id'] for dr in device_roles}
    devices_platform_dict = {dp['name']: dp['id'] for dp in device_platform}
    sites_dict = {s['name']: s['id'] for s in sites}

    return (
        devices_type_dict,
        devices_role_dict,
        devices_platform_dict,
        sites_dict,
        list(sites_dict.keys()),
        list(devices_type_dict.keys()),
        list(devices_role_dict.keys()),
        list(devices_platform_dict.keys())
    )

def types_validation(payload_raw, payload_chassis_raw):
    """Validate and prepare device payload."""
    payload_final = []
    try:
        device_type, device_role, devices_platform, sites, sites_list, device_types_list, device_roles_list, devices_platform_list = get_netbox_types()
    except Exception as e:
        print(f'Error: {e}')
        return []

    print("\nValidating model, platform site and role...")

    #validação do chassi
    if payload_chassis_raw:
        if (payload_chassis_raw["device_type"] in device_types_list and
                payload_chassis_raw["role"]["name"] in device_roles_list and
                payload_chassis_raw["site"] in sites_list):
            chassis_payload = {
                "name": payload_chassis_raw['name'],
                "device_type": device_type[payload_chassis_raw["device_type"]],
                "role": device_role[payload_chassis_raw["role"]["name"]],
                "site": sites[payload_chassis_raw["site"]],
                "status": payload_chassis_raw["status"],
                "rack": payload_chassis_raw["rack"],
                "face": payload_chassis_raw["face"],
                "position": payload_chassis_raw["position"],
                "custom_fields": {
                    'procurement_ticket_url': payload_chassis_raw["custom_fields"]["procurement_ticket_url"]
                },
                "tenant": 18458,  # 18458 = onboarding tenant
            }
    else:
        chassis_payload = None


    #validação das máquinas
    for device_raw in payload_raw:
        site_id = sites[device_raw["site"]]
        if (device_raw["device_type"] in device_types_list and
                device_raw["platform"]["name"] in devices_platform_list and
                device_raw["role"]["name"] in device_roles_list and
                device_raw["site"] in sites_list):

            if device_raw["position"]:
                position = device_raw["position"]
                face = "front"
            else:
                position = None
                face = None

            payload_temp = {
                "name": device_raw['name'],
                "device_type": device_type[device_raw["device_type"]],
                "role": device_role[device_raw["role"]["name"]],
                "site": sites[device_raw["site"]],
                "platform": devices_platform[device_raw["platform"]["name"]],
                "status": device_raw["status"],
                "serial": device_raw["serial"],
                "rack": device_raw["rack"],
                "slot": device_raw["slot"],
                "face": face,
                "position": position,
                "tags":[61], #already_with_segmentation_v2
                "tenant": 18458, #18458 = onboarding tenant
                "custom_fields": {
                    'automation_instance': device_raw["custom_fields"]["automation_instance"],
                    'procurement_ticket_url': device_raw["custom_fields"]["procurement_ticket_url"],
                    "syncable": True,
                }
            }
            payload_final.append(payload_temp)

        else:
            print(f'Validation failed for device {device_raw["name"]}')
    return payload_final, site_id, chassis_payload

def device_bay_creation(chassis_id, device_id, slot):
    endpoint = "dcim/device-bays/"
    data={
        "device": {
            "id": chassis_id,
        },
        "name": f"slot-{slot}",
        "installed_device": {
            "id": device_id,
        },
    }
    response = create_netbox_data(url_api, token, endpoint, data)



def create_device(payload, chassis_id):
    """Create a new device in Netbox."""
    print(f'{payload["name"]}: ',end='')
    endpoint='dcim/devices/'
    slot = payload.pop("slot", None)
    response = create_netbox_data(url_api, token, endpoint, payload)
    if response:
        device = response.json()
        if device:
            if chassis_id:
                print(f'Chassis slot-{slot}: ', end='')
                device_bay_creation(chassis_id, device["id"], slot)
                return device
            else:
                return device
        else:
            return None
    else:
        return None

def create_interface(payload):
    """Create a new interface in Netbox."""
    print(f'Interface {payload["name"]}: ', end='')
    endpoint = 'dcim/interfaces/'
    interface = create_netbox_data(url_api, token, endpoint, payload)
    if interface:
        return interface.json()
    else:
        return None

def create_ip_address(payload):
    """Create a new IP address in Netbox."""
    print(f'IP {payload["address"]}: ',end='')
    endpoint = f'ipam/ip-addresses/?q={payload["address"]}'
    response = get_netbox_data(url_api, token, endpoint)
    if not response:
        endpoint='ipam/ip-addresses/'
        ip = create_netbox_data(url_api, token, endpoint, payload)
        if ip:
            return ip.json()
        else:
            return None
    else:
        print("IP already exists")
        return None

def update_device_main_ip(device_id,ip_id,ip_version):
    """Updated the device main IP information"""
    endpoint = f'dcim/devices/{device_id}/'
    print(f'Updating main {ip_version}: ', end='')
    if ip_version == "ipv6":
        data={
            'primary_ip6': ip_id
        }
        update_netbox_data(url_api, token, endpoint, data)
    elif ip_version == "ipv4":
        data = {
            'primary_ip4': ip_id
        }
        update_netbox_data(url_api, token, endpoint, data)
    return
class NetboxCache:
    """Create vlan and vlan group cache."""
    def __init__(self):
        self.vlan_groups = None
        self.vlans = {}  # Cache por group_id

    def get_vlan_groups(self, force_refresh=False):
        """Get VLAN groups with caching."""
        if self.vlan_groups is None or force_refresh:
            endpoint='ipam/vlan-groups/'
            self.vlan_groups = get_netbox_data(url_api, token, endpoint)
        return self.vlan_groups

    def get_vlans_for_group(self, group_id, force_refresh=False):
        """Get VLANs for a specific group with caching."""
        if group_id not in self.vlans or force_refresh:
            endpoint = f'ipam/vlans/?group_id={group_id}'
            self.vlans[group_id] = get_netbox_data(url_api, token, endpoint)
        return self.vlans[group_id]

def create_vlan(vlan_id, vlan_group):
    """Create a new VLAN in Netbox."""
    endpoint=f"ipam/vlan-groups/?q={vlan_group}"
    vlan_groups = get_netbox_data(url_api, token, endpoint)
    if not vlan_groups:
        return None

    vlan_group_id = vlan_groups[-1]["id"]
    payload = {
        "vid": vlan_id,
        "name": f'{vlan_group.replace("vg-", "").upper()}-Vlan{vlan_id}',
        "group": vlan_group_id,
        "status": reserva
    }
    print(f'VLAN: {vlan_id}: ', end='')
    endpoint='ipam/vlans/'
    response = create_netbox_data(url_api, token, endpoint, payload)
    return response

def create_vlan_group(vlan_group):
    """Create a new VLAN group in Netbox."""
    payload = {
        "name": vlan_group,
        "slug": vlan_group,
        "vid_ranges": [[3738, 3831]],
        "description": f'{vlan_group.replace("vg-", "").upper()}'
    }
    print(f'{vlan_group}: ', end='')
    endpoint='ipam/vlan-groups/'
    response = create_netbox_data(url_api, token, endpoint, payload)
    return response

def check_vlan_group(vlan_group):
    """Check if VLAN group exists using cache."""
    groups = netbox_cache.get_vlan_groups()
    return any(group["name"] == vlan_group for group in groups)

def check_vlan(vlan_id, vlan_group):
    """Check if VLAN exists in group using cache."""
    groups = netbox_cache.get_vlan_groups()
    matching_group = next((group for group in groups if group["name"] == vlan_group), None)

    if not matching_group:
        return False

    vlans = netbox_cache.get_vlans_for_group(matching_group["id"])
    for vlan in vlans:
        if vlan["vid"] == vlan_id:
            return vlan["id"]
    return False

def create_network_infrastructure(vlan_group, vlan_id):
    """Create Switch virtual interface"""
    switch_name = f'{vlan_group.replace("vg-", "").upper()}'
    switch = get_device_by_name(switch_name)
    interface_payload = {
        "device": switch["id"],
        "name": f"Vlan{vlan_id}",
        "type": "virtual",
        "enabled": True,
        "mgmt_only": False
    }
    interface = create_interface(interface_payload)
    if interface:
        switch_interface_id=interface["id"]
    else:
        switch_interface_id=None

    """Create VLAN and VLAN group if they don't exist."""
    if check_vlan_group(vlan_group):
        print(f'{vlan_group} already exist')
    else:
        create_vlan_group(vlan_group)
        # Atualiza o cache após criar um novo grupo
        netbox_cache.get_vlan_groups(force_refresh=True)

    matching_group = next((group for group in netbox_cache.get_vlan_groups()
                           if group["name"] == vlan_group.strip()), None)
    vlan_code = check_vlan(vlan_id, vlan_group)
    if matching_group and not vlan_code:
        created_vlan = create_vlan(vlan_id, vlan_group)
        if created_vlan:
            # Atualiza o cache de VLANs para este grupo
            netbox_cache.get_vlans_for_group(matching_group["id"], force_refresh=True)
        return int(created_vlan.json()["id"]), switch_interface_id
    else:
        print(f'VLAN {vlan_id} already exist on this group')
    return vlan_code, switch_interface_id

def create_prefix(ip_addr, ip_type, vlan, site_id, ticket,switch_interface_id):
    if switch_interface_id:
        gw_interface_type = "dcim.interface"
    else:
        gw_interface_type = None

    if ip_type == "ip_eth0":
        ipv4_address = ipaddress.ip_interface(ip_addr)
        if ipv4_address.network.prefixlen == 31:
            print(f'Prefix {ipv4_address.network}: ',end='')
            prefix_data = [
                {
                    "prefix": str(ipv4_address.network),# Prefixo da rede
                    "site": site_id,
                    "status": reserva,
                    "description": ticket
                }
            ]
            if vlan:
                prefix_data[0]["vlan"]={"id": vlan}

            endpoint = f'ipam/prefixes/?within_include={ipv4_address.network}'
            response = get_netbox_data(url_api, token, endpoint)
            if not response:
                endpoint="ipam/prefixes/"
                response=create_netbox_data(url_api, token, endpoint, prefix_data)
            else:
                print("Prefix already exists")

            """Create GW IP"""
            gw_ipv4_data = (
                {
                    "address": str(ipv4_address.network),
                    "assigned_object_id": switch_interface_id,
                    "assigned_object_type": gw_interface_type,
                    "status": reserva,
                    "role": "vip",
                    "description": "Gateway IPv4"
                }
            )
            create_ip_address(gw_ipv4_data) #Cria gateway da rede IPv4



    elif ip_type == "ipv6_eth0":
        ipv6_address = ipaddress.ip_interface(ip_addr)
        if ipv6_address.network.prefixlen == 64:
            print(f'Prefix {ipv6_address.network}: ',end='')
            prefix_data = [
                {
                    "prefix": str(ipv6_address.network),# Prefixo da rede
                    "site": site_id,
                    "status": reserva,
                    "description": ticket
                }
            ]
            if vlan:
                prefix_data[0]["vlan"]={"id": vlan}

            endpoint = f'ipam/prefixes/?within_include={ipv6_address.network}'
            response = get_netbox_data(url_api, token, endpoint)
            if not response:
                endpoint="ipam/prefixes/"
                response=create_netbox_data(url_api, token, endpoint, prefix_data)
            else:
                print("Prefix already exists")
            gw_ipv6 = f'{str(ipv6_address.network[1])}{"/64"}'
            gw_ipv6_data = (
                {
                    "address": gw_ipv6,
                    "assigned_object_id": switch_interface_id,
                    "assigned_object_type": gw_interface_type,
                    "status": reserva,
                    "role": "vip",
                    "description": "Gateway IPv6"
                }
            )
            create_ip_address(gw_ipv6_data)  # Cria gateway da rede IPv6


# Criar uma instância global do cache
netbox_cache = NetboxCache()



def main():
    # Load data from CSV
    payload_device_raw, ticket, site, payload_chassis_raw = csv_import_info(file_name)

    # Validate devices
    payload_final, site_id, chassis_payload = types_validation(payload_device_raw, payload_chassis_raw)

    #Cria Chassi, se ele existir:
    chassis_id=None
    if chassis_payload:
        print("\nCreating chassis...")
        response = create_device(chassis_payload,chassis_id)
        if response:
            chassis_id=response["id"]
            print(f"Chassis ID: {chassis_id}")

    # Update VLAN cache
    netbox_cache.get_vlan_groups(force_refresh=True)

    #Create Devices
    device_ids = []
    print("\nCreating devices...")
    for payload in payload_final:
        response = create_device(payload,chassis_id)
        if response:
            device_ids.append(response['id'])
    if not device_ids:
        print("\nNo devices created")
        return
    print(f"Created device IDs: {device_ids}")


    for device_id in device_ids:
        current_device = get_single_device(device_id)

        if not current_device:
            print(f"Could not find device with ID {device_id}")
            continue

        device_data = next((d for d in payload_device_raw if d['name'] == current_device['name']), None)
        if not device_data:
            continue

        print(f'\nCreating {current_device["name"]} related objects')

        interfaces = [
            {
                "device": device_id,
                "name": "IPMI",
                "type": "1000base-t",
                "enabled": True,
                "mgmt_only": True,
                # "mac_address": device_data["mac_ipmi"]
            },
            {
                "device": device_id,
                "name": "PXE",
                "type": "1000base-t",
                "enabled": True,
                "mgmt_only": True,
                # "mac_address": device_data["mac_pxe"]
            },
            {
                "device": device_id,
                "name": "ETH0",
                "type": "1000base-t",
                "enabled": True,
                "mgmt_only": False,
                # "mac_address": device_data["mac_eth0"]
            }
        ]
        interface_ids = {}
        for interface in interfaces:
            response = create_interface(interface)
            if response:
                interface_ids[response['name']] = response['id']

        #Create VLAN and VLAN Group
        if device_data["vlan_group"] and device_data["vlan"]:
            vlan, switch_interface_id = create_network_infrastructure(
                device_data["vlan_group"],
                int(device_data["vlan"])
            ) #Retorna id da VLAN como int
        else:
            vlan = None
            switch_interface_id = None


        # Create and assign IP addresses
        for ip_type, interface_name, tag_id in [
            ('ip_eth0', 'ETH0', 24),
            ('ipv6_eth0', 'ETH0', 25),
            ('ip_ipmi', 'IPMI', 26)
        ]:
            if device_data[ip_type] and interface_name in interface_ids:
                ip_payload = {
                    "address": device_data[ip_type],
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": interface_ids[interface_name],
                    "status": reserva,
                    "description": ticket,
                    "tags": [
                        {
                            "id":tag_id
                        }
                    ]
                }
                response = create_ip_address(ip_payload)
                if response and (ip_type == "ip_eth0"):
                    update_device_main_ip(device_id,response["id"],ip_version="ipv4")
                    create_prefix(response["display"], ip_type, vlan, site_id, ticket,switch_interface_id)
                elif response and ip_type == "ipv6_eth0":
                    update_device_main_ip(device_id,response["id"],ip_version="ipv6")
                    create_prefix(response["display"], ip_type, vlan, site_id, ticket,switch_interface_id)

    print("\nEnd of script")


if __name__ == "__main__":
    main()
