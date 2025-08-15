import requests
import webbrowser
import json
import os
import time

# ==== CONFIG ====
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"  # Leave "" if public app
API_KEY = "b06d023210fa47a2ab752390507578cd"
REDIRECT_URL = "https://axxtur3l.github.io/destiny2/"
TOKEN_FILE = "tokens.json"

BASE_URL = "https://www.bungie.net/Platform"
HEADERS_API = {"X-API-Key": API_KEY}


# ------------------ TOKEN HANDLING ------------------ #
def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None

def save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

def oauth_login():
    auth_url = f"https://www.bungie.net/en/OAuth/Authorize?client_id={CLIENT_ID}&response_type=code"
    print("Opening Bungie login page...")
    webbrowser.open(auth_url)
    code = input("ea2e34a55cad79d00fb73aa5536d215b").strip()

    token_url = f"{BASE_URL}/app/oauth/token/"
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code
    }
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET

    res = requests.post(token_url, data=data)
    tokens = res.json()
    if "access_token" not in tokens:
        print("Error getting tokens:", tokens)
        exit()
    tokens["timestamp"] = int(time.time())
    save_tokens(tokens)
    return tokens

def refresh_tokens(refresh_token):
    token_url = f"{BASE_URL}/app/oauth/token/"
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET

    res = requests.post(token_url, data=data)
    tokens = res.json()
    if "access_token" not in tokens:
        print("Error refreshing token:", tokens)
        exit()
    tokens["timestamp"] = int(time.time())
    save_tokens(tokens)
    return tokens

def get_valid_tokens():
    tokens = load_tokens()
    if not tokens:
        return oauth_login()

    # refresh if expired
    if int(time.time()) - tokens["timestamp"] > tokens["expires_in"] - 60:
        return refresh_tokens(tokens["refresh_token"])
    return tokens


# ------------------ MANIFEST LOOKUP ------------------ #
def fetch_manifest_definitions():
    manifest = requests.get(f"{BASE_URL}/Destiny2/Manifest/", headers=HEADERS_API).json()["Response"]
    item_url = manifest["jsonWorldComponentContentPaths"]["en"]["DestinyInventoryItemDefinition"]
    return requests.get(f"https://www.bungie.net{item_url}").json()

def get_item_name(item_hash, manifest):
    return manifest.get(str(item_hash), {}).get("displayProperties", {}).get("name", f"Unknown Item ({item_hash})")


# ------------------ EXPORTER ------------------ #
def export_equipped(tokens):
    headers_auth = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-API-Key": API_KEY
    }

    # Get membership info
    user_res = requests.get(f"{BASE_URL}/User/GetMembershipsForCurrentUser/", headers=headers_auth).json()
    membership = user_res["Response"]["destinyMemberships"][0]
    membership_id = membership["membershipId"]
    membership_type = membership["membershipType"]

    # Get profile with characters
    params = {"components": "200,205,300,305"}
    profile_url = f"{BASE_URL}/Destiny2/{membership_type}/Profile/{membership_id}/"
    profile = requests.get(profile_url, headers=headers_auth, params=params).json()["Response"]

    # Find Hunter characterId
    hunter_id = None
    for char_id, char_data in profile["characters"]["data"].items():
        if char_data["classType"] == 1:  # 1 = Hunter
            hunter_id = char_id
            break
    if not hunter_id:
        print("No Hunter found on this account!")
        return

    equipment = profile["characterEquipment"]["data"][hunter_id]["items"]
    sockets_data = profile["itemSockets"]["data"]

    manifest_items = fetch_manifest_definitions()

    output = []
    for item in equipment:
        item_hash = item["itemHash"]
        item_name = get_item_name(item_hash, manifest_items)

        shaders = []
        ornaments = []

        if item["itemInstanceId"] in sockets_data:
            sockets = sockets_data[item["itemInstanceId"]]["sockets"]
            for s in sockets:
                plug_hash = s.get("plugHash")
                if plug_hash:
                    plug_name = get_item_name(plug_hash, manifest_items)
                    if "Shader" in plug_name:
                        shaders.append(plug_name)
                    elif "Ornament" in plug_name:
                        ornaments.append(plug_name)

        output.append({
            "item": item_name,
            "shaders": shaders,
            "ornaments": ornaments
        })

    with open("equipped_cosmetics.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n=== Hunter Equipped Items Exported ===")
    for o in output:
        print(f"- {o['item']}")
        if o["shaders"]:
            print(f"    Shader: {', '.join(o['shaders'])}")
        if o["ornaments"]:
            print(f"    Ornament: {', '.join(o['ornaments'])}")


if __name__ == "__main__":
    tokens = get_valid_tokens()
    export_equipped(tokens)
