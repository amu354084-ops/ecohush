import urllib.request
import json
url = "http://127.0.0.1:1833/openapi.json"
print(url)
response = urllib.request.urlopen(url)
openapi = json.loads(response.read().decode())
prefixes = [
    "/api/v1/dashboard",
    "/api/v1/clients",
    "/api/v1/backup",
    "/api/v1/formulas",
    "/api/v1/finance",
    "/api/v1/warehouse",
]
for path in sorted(openapi["paths"]):
    if any(prefix in path for prefix in prefixes):
        print(path)
