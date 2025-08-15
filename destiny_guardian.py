import requests
import webbrowser

# ==== CONFIG ====
CLIENT_ID = "50562"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"  # Leave "" if public app
API_KEY = "b06d023210fa47a2ab752390507578cd"
REDIRECT_URL = "https://axxtur3l.github.io/destiny2/"  # Your GitHub Pages redirect

# ==== STEP 1: Authorize ====
auth_url = f"https://www.bungie.net/en/OAuth/Authorize?client_id={CLIENT_ID}&response_type=code"
print("Opening Bungie login page...")
print("If it doesn't open automatically, go to this URL:\n", auth_url)
webbrowser.open(auth_url)

# ==== STEP 2: Get Code from Redirect ====
code = input("ea2e34a55cad79d00fb73aa5536d215b").strip()

# ==== STEP 3: Exchange Code for Token ====
token_url = "https://www.bungie.net/platform/app/oauth/token/"
data = {
    "client_id": CLIENT_ID,
    "grant_type": "authorization_code",
    "code": code
}
if CLIENT_SECRET:
    data["client_secret"] = CLIENT_SECRET

token_res = requests.post(token_url, data=data)
tokens = token_res.json()

if "access_token" not in tokens:
    print("Error getting token:", tokens)
    exit()

access_token = tokens["access_token"]
print("\nAccess token acquired!")

# ==== STEP 4: Get Profile ====
# First, get membership info
headers = {
    "Authorization": f"Bearer {access_token}",
    "X-API-Key": API_KEY
}

user_res = requests.get("https://www.bungie.net/Platform/User/GetMembershipsForCurrentUser/", headers=headers)
user_data = user_res.json()

if "Response" not in user_data:
    print("Error getting membership:", user_data)
    exit()

membership = user_data["Response"]["destinyMemberships"][0]
membership_id = membership["membershipId"]
membership_type = membership["membershipType"]

print(f"\nMembership Type: {membership_type}, ID: {membership_id}")

# ==== STEP 5: Get Guardian Gear ====
profile_url = f"https://www.bungie.net/Platform/Destiny2/{membership_type}/Profile/{membership_id}/"
params = {"components": "200,205"}  # Equipment + Appearance
profile_res = requests.get(profile_url, headers=headers, params=params)
profile_data = profile_res.json()

print("\n=== Guardian Data ===")
print(profile_data)
