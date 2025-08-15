"""
Destiny 2 – Export equipped items (name, type, icon) + applied Shader & Ornament (+ key perks)

What this script does
- Uses your OAuth token to call Bungie.net.
- Finds your first Destiny profile + first character (or specify one).
- Pulls equipped items via GetProfile(components=Profiles,CharacterEquipment,ItemSockets).
- For each equipped item, inspects sockets to find the currently-plugged Shader and Ornament.
- Looks up human-readable names in the Manifest (using the single-entity endpoint; no DB download needed).
- Optionally grabs visible weapon perks.
- Writes a compact JSON file you can feed into a renderer later.

Setup
1) Set environment variables (or hardcode below):
   - BUNGIE_API_KEY = "your-api-key-from-dev-portal"
   - BUNGIE_CLIENT_ID = "your-client-id"
   - BUNGIE_CLIENT_SECRET = "your-client-secret"
2) Put your OAuth tokens in tokens.json with at least: {"access_token":"...","refresh_token":"..."}
   (Same ones you obtained in the OAuth step.)
3) Run:  python export_equipped_cosmetics.py --character latest  (or pass a specific characterId)

Notes
- Requires only the ReadDestinyInventoryAndVault (and basic profile read) scopes.
- Components used: Profiles(100), CharacterEquipment(205), ItemSockets(305). Reusable plugs (310) are *not* required.
- If your access token expires, the script will refresh it automatically using your refresh_token.
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Any, List, Optional, Tuple

import requests

BUNGIE_API_BASE = "https://www.bungie.net/Platform"
OAUTH_TOKEN_URL = "https://www.bungie.net/platform/app/oauth/token/"

HEADERS = {
    "X-API-Key": os.getenv("BUNGIE_API_KEY", ""),
}

CLIENT_ID = os.getenv("50562", "")
CLIENT_SECRET = os.getenv("8DlXmQeCvV2i2GFW3owx6Y8ghxbrR60qIisxOM2o8d4", "")
TOKENS_PATH = os.getenv("BUNGIE_TOKENS_PATH", "tokens.json")

# DestinyComponentType values we need (from official docs)
COMPONENT_PROFILES = 100
COMPONENT_CHAR_EQUIP = 205
COMPONENT_ITEM_SOCKETS = 305

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

class BungieError(RuntimeError):
    pass

def load_tokens(path: str = TOKENS_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Token file not found at {path}. Create it with your access_token & refresh_token.")
        sys.exit(1)


def save_tokens(tokens: Dict[str, Any], path: str = TOKENS_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def set_auth_header(access_token: str) -> None:
    SESSION.headers["Authorization"] = f"Bearer {access_token}"


def oauth_refresh(refresh_token: str) -> Dict[str, Any]:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise BungieError("CLIENT_ID/CLIENT_SECRET missing for token refresh.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    r = requests.post(OAUTH_TOKEN_URL, data=data, headers={"X-API-Key": HEADERS.get("X-API-Key", "")})
    if r.status_code != 200:
        raise BungieError(f"Refresh failed: {r.status_code} {r.text}")
    tokens = r.json()
    # Normalize some common field casing
    return tokens


def bnet_get(path: str, params: Optional[Dict[str, Any]] = None, retry_on_401: bool = True) -> Any:
    url = f"{BUNGIE_API_BASE}{path}"
    r = SESSION.get(url, params=params)
    if r.status_code == 401 and retry_on_401:
        # try refresh
        tokens = load_tokens()
        new_tokens = oauth_refresh(tokens.get("refresh_token", ""))
        # Bungie returns access_token, refresh_token, expires_in, etc.
        tokens.update(new_tokens)
        save_tokens(tokens)
        set_auth_header(tokens["access_token"])  # update header and retry once
        return bnet_get(path, params, retry_on_401=False)

    if r.status_code != 200:
        raise BungieError(f"HTTP {r.status_code}: {r.text}")

    j = r.json()
    if j.get("ErrorCode") != 1:
        raise BungieError(f"Bungie error {j.get('ErrorStatus')}: {j.get('Message')}")
    return j["Response"]


def get_memberships_for_current_user() -> Dict[str, Any]:
    return bnet_get("/User/GetMembershipsForCurrentUser/")


def pick_first_destiny_membership(memberships: Dict[str, Any]) -> Tuple[int, str]:
    # Returns (membershipType, destinyMembershipId)
    # Prefer the "destinyMemberships" array.
    for m in memberships.get("destinyMemberships", []):
        return m["membershipType"], m["membershipId"]
    raise BungieError("No Destiny memberships found on this account.")


def get_profile(membership_type: int, membership_id: str, components: List[int]) -> Dict[str, Any]:
    comp_str = ",".join(str(c) for c in components)
    return bnet_get(f"/Destiny2/{membership_type}/Profile/{membership_id}/", params={"components": comp_str})


def get_entity(entity_type: str, definition_hash: int) -> Dict[str, Any]:
    # Single-entity manifest lookup
    # entity_type examples: DestinyInventoryItemDefinition, DestinyClassDefinition, etc.
    return bnet_get(f"/Destiny2/Manifest/{entity_type}/{definition_hash}/")


def friendly_item_name(item_hash: int) -> str:
    try:
        ent = get_entity("DestinyInventoryItemDefinition", item_hash)
        return ent.get("displayProperties", {}).get("name", str(item_hash))
    except Exception:
        return str(item_hash)


def get_item_icon_and_type(item_hash: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        ent = get_entity("DestinyInventoryItemDefinition", item_hash)
        icon = ent.get("displayProperties", {}).get("icon")
        item_type = ent.get("itemTypeDisplayName") or ent.get("itemTypeAndTierDisplayName")
        return icon, item_type
    except Exception:
        return None, None


def find_applied_shader_and_ornament(sockets_component: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Return (shader_item_hash, ornament_item_hash) if found on this item's sockets."""
    shader_hash = None
    ornament_hash = None
    sockets = sockets_component.get("sockets") or []

    for s in sockets:
        plug = s.get("plug") or {}
        plug_hash = plug.get("plugItemHash")
        if not plug_hash:
            # Some responses use 'plugHash' on the socket state; handle both
            plug_hash = s.get("plugHash")
        if not plug_hash:
            continue
        try:
            pdef = get_entity("DestinyInventoryItemDefinition", plug_hash)
        except Exception:
            continue
        name = (pdef.get("displayProperties") or {}).get("name", "")
        item_cat_names = set(pdef.get("itemTypeDisplayName") or [])
        # Heuristics: shaders usually have plug.plugCategoryIdentifier like "shader" and itemTypeDisplayName == "Shader"
        plug_info = pdef.get("plug", {})
        cat_id = plug_info.get("plugCategoryIdentifier", "")
        type_name = pdef.get("itemTypeDisplayName") or ""
        if not shader_hash and ("shader" in cat_id.lower() or type_name.lower() == "shader"):
            shader_hash = plug_hash
        # Ornaments often have plugCategoryIdentifier containing "armor_skins" or "skins" or type display "Ornament"
        if not ornament_hash and ("ornament" in type_name.lower() or "skin" in cat_id.lower()):
            ornament_hash = plug_hash
    return shader_hash, ornament_hash


def extract_visible_perks(sockets_component: Dict[str, Any]) -> List[int]:
    """Return a small set of currently visible/active perk plug item hashes for weapons.
    This is optional and best-effort.
    """
    perks: List[int] = []
    sockets = sockets_component.get("sockets") or []
    for s in sockets:
        plug = s.get("plug") or {}
        plug_hash = plug.get("plugItemHash") or s.get("plugHash")
        if not plug_hash:
            continue
        # Skip if this is clearly a shader/ornament socket we already handle
        try:
            pdef = get_entity("DestinyInventoryItemDefinition", plug_hash)
        except Exception:
            continue
        type_name = (pdef.get("itemTypeDisplayName") or "").lower()
        cat_id = (pdef.get("plug", {}).get("plugCategoryIdentifier") or "").lower()
        if ("shader" in cat_id) or (type_name == "shader") or ("ornament" in type_name) or ("skin" in cat_id):
            continue
        # Keep perks that look like weapon/armor mods/perks
        if any(key in cat_id for key in ["intrinsics", "barrels", "magazines", "frames", "traits", "origin"]):
            perks.append(plug_hash)
    return perks[:6]  # keep it compact


def pick_character_id(profile: Dict[str, Any], choice: str) -> str:
    char_ids: List[str] = profile.get("profile", {}).get("data", {}).get("characterIds", [])
    if not char_ids:
        raise BungieError("No characters found.")
    if choice == "latest":
        latest = None
        latest_time = 0
        chars = profile.get("characters", {}).get("data", {})
        for cid in char_ids:
            cdata = chars.get(cid)
            if not cdata:
                continue
            mtime = int(time.mktime(time.strptime(cdata.get("dateLastPlayed")[:19], "%Y-%m-%dT%H:%M:%S")))
            if mtime > latest_time:
                latest_time = mtime
                latest = cid
        return latest or char_ids[0]
    else:
        # assume they passed an exact id
        return choice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", default="latest", help='Character ID to use, or "latest" (default).')
    parser.add_argument("--out", default="equipped_cosmetics.json", help="Output JSON filename")
    args = parser.parse_args()

    tokens = load_tokens(TOKENS_PATH)
    access_token = tokens.get("access_token")
    if not access_token:
        raise BungieError("access_token missing in tokens.json")

    if not HEADERS.get("X-API-Key"):
        raise BungieError("BUNGIE_API_KEY env var not set.")

    set_auth_header(access_token)

    # Who am I?
    mems = get_memberships_for_current_user()
    membership_type, membership_id = pick_first_destiny_membership(mems)

    # Fetch profile data with equipment + sockets
    profile = get_profile(
        membership_type,
        membership_id,
        components=[COMPONENT_PROFILES, COMPONENT_CHAR_EQUIP, COMPONENT_ITEM_SOCKETS],
    )

    # Decide character ID
    char_id = pick_character_id(profile, args.character)

    # Collect equipped item instance IDs for this character
    equip = profile.get("characterEquipment", {}).get("data", {}).get(char_id, {})
    equipped = equip.get("items", [])

    # Item-level sockets come in itemComponents.sockets.data[instanceId]
    sockets_by_item = profile.get("itemComponents", {}).get("sockets", {}).get("data", {})

    results = {
        "membershipType": membership_type,
        "membershipId": membership_id,
        "characterId": char_id,
        "items": [],
    }

    for it in equipped:
        instance_id = it.get("itemInstanceId")
        item_hash = it.get("itemHash")
        if not item_hash:
            continue
        icon, item_type = get_item_icon_and_type(item_hash)
        sockets_comp = sockets_by_item.get(str(instance_id), {}) if instance_id else {}
        shader_hash, ornament_hash = find_applied_shader_and_ornament(sockets_comp)
        perk_hashes = extract_visible_perks(sockets_comp)

        rec = {
            "itemHash": item_hash,
            "itemName": friendly_item_name(item_hash),
            "itemType": item_type,
            "icon": icon,  # relative bungie path, prefix with https://www.bungie.net
            "instanceId": instance_id,
            "appliedShader": {
                "itemHash": shader_hash,
                "name": friendly_item_name(shader_hash) if shader_hash else None,
            },
            "appliedOrnament": {
                "itemHash": ornament_hash,
                "name": friendly_item_name(ornament_hash) if ornament_hash else None,
            },
            "visiblePerks": [
                {"itemHash": h, "name": friendly_item_name(h)} for h in perk_hashes
            ],
        }
        results["items"].append(rec)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {args.out} with {len(results['items'])} equipped items.")


if __name__ == "__main__":
    try:
        main()
    except BungieError as e:
        print(f"Error: {e}")
        sys.exit(2)
