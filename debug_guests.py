
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("CHEKIN_EMAIL", "")
PASSWORD = os.getenv("CHEKIN_PASSWORD", "")
BASE_API = "https://a.chekin.io/api/v4"

def get_token():
    # Simplification: read from tokens file as the monitor does
    with open("chekin_tokens.json", "r") as f:
        tokens = json.load(f)
    return tokens["access_token"]

token = get_token()
headers = {
    "Authorization": f"JWT {token}",
    "Content-Type": "application/json",
    "x-source": "DASHBOARD",
}

# Test guest ID from report
guest_id = "f76eeea41a4e42f49f599b5173ad88bb"
print(f"Probing guest {guest_id}...")

# Try different endpoints
endpoints = [
    f"/guests/{guest_id}/",
    f"/guest-groups/guests/{guest_id}/",
]

for ep in endpoints:
    try:
        print(f"Trying {ep}...")
        r = requests.get(f"{BASE_API}{ep}", headers=headers, verify=False)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

# Also try to see what the group guests endpoint actually returns in full
ggid = "9d3b773b161f4e91a6ae858228fdd905"
print(f"\nProbing group {ggid}/guests...")
r = requests.get(f"{BASE_API}/guest-groups/{ggid}/guests/", headers=headers, verify=False)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    if isinstance(data, dict) and "results" in data:
        print(json.dumps(data["results"], indent=2))
    else:
        print(json.dumps(data, indent=2))
