import requests

try:
    print("Sending login request...")
    r = requests.post("http://127.0.0.1:8000/api/auth/login", json={"username": "op_017", "pin": "1234"}, timeout=5)
    print("Status:", r.status_code)
    print("Response:", r.json())
except Exception as e:
    print("Error:", type(e), e)
