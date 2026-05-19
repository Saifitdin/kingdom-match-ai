"""
Kenney Asset Downloader for Kingdom Match.
Downloads free CC0 game assets from kenney.nl.
"""

import os
import io
import zipfile
import fnmatch
import requests

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)

KENNEY_PACKS = {
    "medieval_rts": "https://github.com/KenneyNL/Starter-Kit-Medieval-RTS/archive/refs/heads/main.zip",
    "tower_defense": "https://github.com/KenneyNL/Starter-Kit-Tower-Defense/archive/refs/heads/main.zip",
    "game_icons": "https://github.com/KenneyNL/kenney-voxel-pack/archive/refs/heads/main.zip",
}

FILE_MAP = {
    "*sword*":      "tile_warrior",
    "*knight*":     "tile_warrior",
    "*bow*":        "tile_archer",
    "*archer*":     "tile_archer",
    "*horse*":      "tile_cavalry",
    "*cavalry*":    "tile_cavalry",
    "*cross*":      "tile_faith",
    "*church*":     "tile_faith",
    "*coin*":       "tile_gold",
    "*gold*":       "tile_gold",
    "*bread*":      "tile_food",
    "*food*":       "tile_food",
    "*meat*":       "tile_food",
    "*wheat*":      "tile_food",
    "*castle*":     "fortress_castle",
    "*keep*":       "fortress_castle",
    "*wall*":       "fortress_walls",
    "*tower*":      "fortress_tower",
    "*gate*":       "fortress_gate",
    "*water*":      "fortress_moat",
    "*moat*":       "fortress_moat",
    "*enemy*":      "enemy",
    "*boss*":       "enemy",
    "*orc*":        "enemy",
    "*grass*":      "bg",
    "*landscape*":  "bg",
    "*background*": "bg",
}


def download_zip(url):
    print(f"  Downloading {url[:70]}...")
    r = requests.get(url, timeout=60, headers={"User-Agent": "KM/1.0"})
    r.raise_for_status()
    return r.content


def process_pack(name, url):
    print(f"\n--- {name} ---")
    try:
        data = download_zip(url)
    except Exception as e:
        print(f"  FAIL: {e}")
        return

    era_count = {}
    copied = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for fname in zf.namelist():
            if not fname.lower().endswith(".png"):
                continue
            info = zf.getinfo(fname)
            if info.file_size > 500000:
                continue
            png = zf.read(fname)
            if len(png) < 100:
                continue
            base = os.path.basename(fname).lower()

            for pattern, target in FILE_MAP.items():
                if fnmatch.fnmatch(base, pattern):
                    if target.startswith("tile_"):
                        key = target.replace("tile_", "")
                        era = era_count.get(key, 0)
                        if era > 3:
                            continue
                        era_count[key] = era + 1
                        h = str(abs(hash(base)))[:8]
                        out = f"{target}_era{era}_{h}.png"
                    else:
                        out = f"{target}_{str(abs(hash(base)))[:8]}.png"
                        era_count[target] = era_count.get(target, 0) + 1

                    path = os.path.join(OUTPUT_DIR, out)
                    if not os.path.exists(path):
                        with open(path, "wb") as f:
                            f.write(png)
                        copied += 1
                        print(f"    -> {out}")
                    break
    print(f"  Copied: {copied}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] != "all":
        name = sys.argv[1]
        if name in KENNEY_PACKS:
            process_pack(name, KENNEY_PACKS[name])
        else:
            print(f"Unknown: {name}. Available: {list(KENNEY_PACKS.keys())}")
    else:
        for name, url in KENNEY_PACKS.items():
            process_pack(name, url)
    print(f"\nDone. Files in: {OUTPUT_DIR}")