"""
Replicate Visuals Generator for Kingdom Match.
Генерирует игровую графику: портреты врагов, фоны королевств,
иконки тайлов и элементы крепости через Flux/SDXL на Replicate.
"""

import os
import json
import time
import hashlib
import base64
from dataclasses import dataclass
from typing import Optional

import replicate
import requests
from dotenv import load_dotenv

load_dotenv()

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
MODEL_FAST = "black-forest-labs/flux-schnell"
MODEL_QUALITY = "black-forest-labs/flux-dev"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _hash_prompt(prompt: str, model: str) -> str:
    return hashlib.md5((prompt + model).encode()).hexdigest()[:12]


def _cached_path(hash_key: str, prefix: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{prefix}_{hash_key}.png")


def _download_image(url: str, filepath: str) -> str:
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    return filepath


def _image_to_base64(filepath: str) -> str:
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def generate_if_missing(prompt: str, model: str = MODEL_FAST,
                        width: int = 512, height: int = 512,
                        prefix: str = "img") -> str:
    """Сгенерировать изображение, если его нет в кеше."""
    if not REPLICATE_API_TOKEN:
        raise RuntimeError("REPLICATE_API_TOKEN не задан в .env")

    hash_key = _hash_prompt(prompt, model)
    cached = _cached_path(hash_key, prefix)
    if os.path.exists(cached):
        return cached

    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN
    input_params = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_outputs": 1,
        "output_format": "png",
    }
    if model == MODEL_FAST:
        input_params["num_inference_steps"] = 4

    # Пауза чтобы не сработал rate-limit (6 req/min)
    time.sleep(12)
    output = replicate.run(model, input=input_params)
    urls = output if isinstance(output, list) else [output]
    _download_image(urls[0], cached)
    return cached


# ======================== ПРОМПТЫ ========================

ENEMY_PROMPTS = {
    "rus": [
        {"id": "polovets", "name": "Половецкий хан",
         "prompt": "Portrait of a fierce Cuman-Kipchak khan, 12th century, steppe warrior, fur hat, leather armor, scarred face, dramatic lighting, oil painting style, highly detailed"},
        {"id": "khazar", "name": "Хазарский каган",
         "prompt": "Portrait of a Khazar khagan, medieval ruler, long dark beard, jeweled crown, silk robe, stern expression, rich colors, oil painting"},
        {"id": "pecheneg", "name": "Печенежский вождь",
         "prompt": "Portrait of a Pecheneg warlord, wild steppe raider, wolf fur cloak, painted face, windswept hair, fantasy art style"},
        {"id": "varangian", "name": "Ярл Рюрик",
         "prompt": "Portrait of a Varangian viking jarl, Norse warrior, chainmail, horned helmet, braided red beard, epic fantasy style, cold blue tones"},
    ],
    "horde": [
        {"id": "khwarezm", "name": "Шах Хорезма",
         "prompt": "Portrait of a Khwarezmian Shah, Persian ruler, ornate turban, silk robes, calculating eyes, desert palace background, golden hour, oil painting"},
        {"id": "seljuk", "name": "Сельджукский эмир",
         "prompt": "Portrait of a Seljuk emir, turkic warrior-noble, lamellar armor, curved sword, mountain steppe background, epic fantasy art"},
        {"id": "kipchak", "name": "Кипчакский хан",
         "prompt": "Portrait of a Kipchak khan, nomadic steppe lord, weathered face, leather and fur, endless grassland background, cinematic lighting"},
        {"id": "teutonic", "name": "Тевтонский магистр",
         "prompt": "Portrait of a Teutonic Grand Master, crusader knight, white cloak, full plate armor, gothic cathedral background, dramatic chiaroscuro"},
    ],
    "china": [
        {"id": "jurchen", "name": "Чжурчжэньский воевода",
         "prompt": "Portrait of a Jurchen Jin dynasty warlord, heavy fur armor, iron helmet, fierce expression, snowy mountains, Chinese ink painting style"},
        {"id": "tibetan", "name": "Тибетский царь",
         "prompt": "Portrait of a Tibetan king, ornate golden headdress, red robes, snow-capped mountain background, thangka painting style"},
        {"id": "korean", "name": "Корейский ван",
         "prompt": "Portrait of a Korean Joseon king, elegant silk robes, scholarly presence, jade crown, palace courtyard, traditional Korean painting style"},
        {"id": "japanese", "name": "Японский даймё",
         "prompt": "Portrait of a Japanese daimyo, samurai lord, elaborate kabuto helmet, lacquered armor, cherry blossom background, ukiyo-e style"},
    ],
}

KINGDOM_BG_PROMPTS = {
    "rus": "Beautiful landscape of Ancient Rus, wooden kremlin on hill, golden church domes, birch forest, wide river, sunrise, fantasy art style, rich colors",
    "horde": "Vast great steppe landscape, golden grass, yurts, horses running, eagle in sky, orange sunset, mongol empire aesthetic, epic fantasy art, warm colors",
    "china": "Ancient Tang dynasty landscape, pagodas on misty mountains, cherry blossoms, silk banners, soft morning light, traditional Chinese painting, ethereal",
}

ERA_BG_PROMPTS = [
    "Dark ages village, wooden palisade, early medieval, misty morning, fantasy art style, moody",
    "Medieval stone castle on hill, knights, banners, golden afternoon light, epic fantasy, detailed",
    "Renaissance fortified city, bastion walls, merchant ships, rich colors, oil painting style",
    "Futuristic sci-fi fortress, holographic shields, neon, cyberpunk medieval fusion, dramatic",
]

TILE_PROMPTS = {
    "warrior": ["medieval swordsman game icon pixel art flat design white bg",
                "knight in plate armor game icon pixel art flat design",
                "musketeer with rifle game icon pixel art flat design",
                "futuristic soldier energy rifle game icon pixel art flat design"],
    "archer": ["medieval archer bow game icon pixel art flat design white bg",
               "crossbowman aiming game icon pixel art flat design",
               "rifle marksman game icon pixel art flat design",
               "futuristic sniper laser game icon pixel art flat design"],
    "cavalry": ["horse rider spear game icon pixel art flat design white bg",
                "heavy cavalry knight warhorse game icon pixel art flat design",
                "dragoon horseback sabre game icon pixel art flat design",
                "futuristic hover tank game icon pixel art flat design"],
    "faith": ["orthodox cross golden glow game icon pixel art flat design white bg",
              "medieval cathedral game icon pixel art flat design",
              "prayer beads book game icon pixel art flat design",
              "holographic dove peace game icon pixel art flat design"],
    "gold": ["gold coins pile game icon pixel art flat design white bg",
             "treasure chest gems game icon pixel art flat design",
             "paper money stack game icon pixel art flat design",
             "glowing crypto coin game icon pixel art flat design"],
    "food": ["bread loaf wheat game icon pixel art flat design white bg",
             "feast platter meat game icon pixel art flat design",
             "military ration pack game icon pixel art flat design",
             "futuristic nutrient capsule game icon pixel art flat design"],
}

FORTRESS_PROMPTS = {
    "castle": "medieval castle keep game icon pixel art flat design 256x256",
    "walls": "stone fortress walls battlements game icon pixel art flat design",
    "tower": "defensive tower flag game icon pixel art flat design",
    "gate": "reinforced castle gate game icon pixel art flat design",
    "moat": "water moat around castle game icon pixel art flat design",
}

# Портреты советников по королевствам — у каждого королевства 3 советника.
NPC_PROMPTS = {
    "rus": [
        {"id": "velimir",  "name": "Старец Велимир",
         "prompt": "portrait of an old slavic wise man with long white beard, embroidered linen robe, holding a wooden staff, ancient rus orthodox icon style, painted illustration, soft warm light, head and shoulders only, neutral background, game character portrait"},
        {"id": "dobrynya", "name": "Воевода Добрыня",
         "prompt": "portrait of a stern slavic warrior boyar, heavy chain mail armor, conical helmet with nose guard, braided brown beard, holding sword hilt, kievan rus 12th century, painted illustration, game character portrait, head and shoulders, neutral background"},
        {"id": "marfa",    "name": "Купчиха Марфа",
         "prompt": "portrait of a cheerful russian merchant woman in red sarafan and kokoshnik headdress, holding silver coins, ancient novgorod trader, painted illustration, warm colors, game character portrait, head and shoulders, neutral background"},
    ],
    "horde": [
        {"id": "batu",     "name": "Темник Бату",
         "prompt": "portrait of a mongol general in lamellar steppe armor, fur trimmed pointed helmet, long thin black moustache, confident stern face, mongol empire 13th century, painted illustration, game character portrait, head and shoulders, neutral background"},
        {"id": "altan",    "name": "Алтан-шаман",
         "prompt": "portrait of a tengri steppe shaman, deer-antler headdress, painted face, bone necklaces, holding a small drum, dramatic mystical lighting, painted illustration, game character portrait, head and shoulders, neutral background"},
        {"id": "gulnara",  "name": "Гульнара-бегим",
         "prompt": "portrait of a noble central asian woman in silk caftan, embroidered pillbox hat with veil, golden earrings, kindly intelligent expression, silk road merchant noble, painted illustration, game character portrait, head and shoulders, neutral background"},
    ],
    "china": [
        {"id": "libo",     "name": "Мудрец Ли Бо",
         "prompt": "portrait of an elderly tang dynasty chinese sage in flowing hanfu robes, long white beard, holding a scroll, gentle wise expression, traditional ink and color painting style, game character portrait, head and shoulders, neutral background"},
        {"id": "zhen",     "name": "Генерал Чжэнь",
         "prompt": "portrait of a tang dynasty chinese general in red lacquered armor with dragon motifs, jade hairpin, stern noble face, holding ceremonial sword, painted illustration, game character portrait, head and shoulders, neutral background"},
        {"id": "mei",      "name": "Госпожа Мэй",
         "prompt": "portrait of a beautiful tang dynasty noblewoman in elaborate silk hanfu, decorative hair pins, holding a folding fan partially covering her face, intriguing knowing smile, painted illustration, game character portrait, head and shoulders, neutral background"},
    ],
}


# ======================== ГЕНЕРАТОРЫ ========================

def generate_enemy_portraits(kingdom: str = "all") -> dict:
    results = {}
    kingdoms = [kingdom] if kingdom != "all" else list(ENEMY_PROMPTS.keys())
    for kd in kingdoms:
        results[kd] = []
        for enemy in ENEMY_PROMPTS[kd]:
            path = generate_if_missing(enemy["prompt"], MODEL_FAST, 512, 512, f"enemy_{enemy['id']}")
            results[kd].append({"id": enemy["id"], "name": enemy["name"], "b64": _image_to_base64(path)})
    return results


def generate_kingdom_backgrounds() -> dict:
    results = {}
    for kd, prompt in KINGDOM_BG_PROMPTS.items():
        path = generate_if_missing(prompt, MODEL_FAST, 1024, 512, f"bg_{kd}")
        results[kd] = _image_to_base64(path)
    return results


def generate_era_backgrounds() -> list:
    results = []
    for i, prompt in enumerate(ERA_BG_PROMPTS):
        path = generate_if_missing(prompt, MODEL_FAST, 1024, 512, f"era_{i}")
        results.append({"era": i, "b64": _image_to_base64(path)})
    return results


def generate_tile_icons() -> dict:
    results = {}
    for tile_type, era_prompts in TILE_PROMPTS.items():
        results[tile_type] = []
        for era, prompt in enumerate(era_prompts):
            path = generate_if_missing(prompt, MODEL_FAST, 256, 256, f"tile_{tile_type}_era{era}")
            results[tile_type].append(_image_to_base64(path))
    return results


def generate_fortress_elements() -> dict:
    results = {}
    for elem_id, prompt in FORTRESS_PROMPTS.items():
        path = generate_if_missing(prompt, MODEL_FAST, 256, 256, f"fortress_{elem_id}")
        results[elem_id] = _image_to_base64(path)
    return results


def generate_npc_portraits(kingdom: str = "all") -> dict:
    """Сгенерировать портреты советников (по 3 на королевство)."""
    results = {}
    kingdoms = [kingdom] if kingdom != "all" else list(NPC_PROMPTS.keys())
    for kd in kingdoms:
        results[kd] = []
        for npc in NPC_PROMPTS[kd]:
            path = generate_if_missing(npc["prompt"], MODEL_FAST, 512, 512, f"npc_{npc['id']}")
            results[kd].append({"id": npc["id"], "name": npc["name"], "b64": _image_to_base64(path)})
    return results


def generate_all_assets() -> dict:
    if not REPLICATE_API_TOKEN:
        raise RuntimeError("REPLICATE_API_TOKEN не задан. Добавь в .env: REPLICATE_API_TOKEN=r8_...")

    print("Generating enemy portraits...")
    enemies = generate_enemy_portraits("all")
    print("Generating kingdom backgrounds...")
    kingdom_bgs = generate_kingdom_backgrounds()
    print("Generating era backgrounds...")
    era_bgs = generate_era_backgrounds()
    print("Generating tile icons...")
    tiles = generate_tile_icons()
    print("Generating fortress elements...")
    fortress = generate_fortress_elements()

    result = {
        "enemies": enemies,
        "kingdom_bgs": kingdom_bgs,
        "era_bgs": era_bgs,
        "tiles": tiles,
        "fortress": fortress,
    }

    json_path = os.path.join(OUTPUT_DIR, "assets.json")
    with open(json_path, "w") as f:
        json.dump(result, f)
    print(f"Saved: {json_path}")
    return result


if __name__ == "__main__":
    import sys
    if "--enemies" in sys.argv:
        kd = sys.argv[-1] if sys.argv[-1] in ENEMY_PROMPTS else "all"
        print(json.dumps(generate_enemy_portraits(kd), indent=2))
    else:
        generate_all_assets()