"""
Kingdom Match AI Server — Flask API.
Эндпоинты:
  POST /api/generate-levels   — генерация пачки уровней
  POST /api/bot-attack        — симуляция атаки бота
  POST /api/npc-dialogue      — диалог с NPC
  POST /api/npc-quest         — получить квест от NPC
  GET  /api/npc-list          — список NPC королевства
  GET  /api/status            — статус сервера
  GET  /api/assets            — сгенерированные Replicate-ассеты
  GET  /api/assets-img/<path> — статика (изображения)
"""

import os
import json
import sys

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_opponent import (
    Difficulty, Strategy, BotState,
    create_bot, simulate_attack, bot_gets_stronger,
    get_next_attack_cooldown, bot_to_dict, attack_result_to_dict,
)
from level_generator import (
    generate_level_pack, validate_level,
    level_config_to_dict, level_pack_to_dict,
)
from npc_engine import (
    get_npc, get_kingdom_npcs, generate_quest,
    generate_dialogue, npc_to_dict, quest_to_dict,
)
try:
    from replicate_visuals import (
        generate_all_assets, generate_enemy_portraits,
        generate_kingdom_backgrounds, generate_era_backgrounds,
        generate_tile_icons, generate_fortress_elements,
        generate_npc_portraits,
        OUTPUT_DIR, ENEMY_PROMPTS,
    )
except ImportError:
    pass  # replicate не установлен
try:
    from comic_engine import (
        get_or_generate_story, get_story, story_to_dict,
        populate_panel_images,
    )
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

# ----- Хранилище активных ботов (в памяти) -----
active_bots: dict = {}   # key: "kingdom:difficulty" → BotState


# ===================== BOT OPPONENT =====================

@app.route("/api/bot-attack", methods=["POST"])
def bot_attack():
    """
    Симулировать атаку бота на крепость.
    
    Тело запроса:
    {
        "kingdom": "rus",
        "player_level": 5,
        "player_hp": 200,
        "player_defense": 15,
        "player_resources": {"warrior": 50, "gold": 300, ...},
        "player_era": 1,
        "difficulty": "medium",
        "bot_action": "attack" | "create" | "status"
    }
    """
    data = request.get_json() or {}
    kingdom = data.get("kingdom", "rus")
    difficulty_str = data.get("difficulty", "medium")
    action = data.get("bot_action", "attack")

    try:
        difficulty = Difficulty(difficulty_str)
    except ValueError:
        return jsonify({"error": f"Неизвестная сложность: {difficulty_str}"}), 400

    bot_key = f"{kingdom}:{difficulty_str}"

    if action == "create":
        bot = create_bot(kingdom, data.get("player_level", 1), difficulty)
        active_bots[bot_key] = bot
        return jsonify({"bot": bot_to_dict(bot), "cooldown": get_next_attack_cooldown(bot)})

    if action == "status":
        bot = active_bots.get(bot_key)
        if not bot:
            return jsonify({"error": "Бот не создан. Сначала POST с bot_action=create"}), 404
        return jsonify({"bot": bot_to_dict(bot)})

    # action == "attack"
    bot = active_bots.get(bot_key)
    if not bot:
        bot = create_bot(kingdom, data.get("player_level", 1), difficulty)
        active_bots[bot_key] = bot

    result = simulate_attack(
        bot=bot,
        player_hp=data.get("player_hp", 100),
        player_defense=data.get("player_defense", 0),
        player_resources=data.get("player_resources", {}),
        player_era=data.get("player_era", 0),
    )

    bot_gets_stronger(bot, player_won_last=data.get("player_won_last", False))
    cooldown = get_next_attack_cooldown(bot)
    bot.cooldown = cooldown

    return jsonify({
        "attack": attack_result_to_dict(result),
        "bot": bot_to_dict(bot),
        "next_attack_in": cooldown,
    })


# ===================== LEVEL GENERATOR =====================

@app.route("/api/generate-levels", methods=["POST"])
def generate_levels():
    """
    Сгенерировать пачку уровней.
    
    Тело запроса:
    {
        "kingdom": "rus",
        "era": 0,
        "start_level": 1,
        "count": 5,
        "difficulty": "normal",
        "use_ai": true
    }
    """
    data = request.get_json() or {}

    pack = generate_level_pack(
        kingdom=data.get("kingdom", "rus"),
        era=data.get("era", 0),
        start_level=data.get("start_level", 1),
        count=data.get("count", 5),
        difficulty=data.get("difficulty", "normal"),
        use_ai=data.get("use_ai", True),
    )

    result = level_pack_to_dict(pack)

    # Добавляем валидацию
    validations = []
    for lvl in pack.levels:
        v = validate_level(lvl)
        validations.append({"id": lvl.id, "valid": v["valid"], "issues": v["issues"]})

    result["validations"] = validations
    return jsonify(result)


# ===================== NPC =====================

@app.route("/api/npc-list", methods=["GET"])
def npc_list():
    """Список NPC для королевства."""
    kingdom = request.args.get("kingdom", "rus")
    npcs = get_kingdom_npcs(kingdom)
    return jsonify({"kingdom": kingdom, "npcs": [npc_to_dict(n) for n in npcs]})


@app.route("/api/npc-dialogue", methods=["POST"])
def npc_dialogue():
    """
    Получить реплику NPC.
    
    Тело запроса:
    {
        "npc_id": "velimir",
        "player_state": {"level": 5, "era": 1, "hp": 200, "hp_max": 250, ...},
        "context": "greeting",
        "use_ai": true
    }
    """
    data = request.get_json() or {}
    npc_id = data.get("npc_id", "")
    npc = get_npc(npc_id)

    if not npc:
        return jsonify({"error": f"NPC '{npc_id}' не найден"}), 404

    reply = generate_dialogue(
        npc=npc,
        player_state=data.get("player_state", {}),
        context=data.get("context", "greeting"),
        use_ai=data.get("use_ai", True),
    )

    return jsonify({
        "npc": npc_to_dict(npc),
        "reply": reply,
        "context": data.get("context", "greeting"),
    })


@app.route("/api/npc-quest", methods=["POST"])
def npc_quest():
    """
    Получить квест от NPC.
    
    Тело запроса:
    {
        "npc_id": "velimir",
        "player_level": 5,
        "player_resources": {"gold": 300, ...}
    }
    """
    data = request.get_json() or {}
    npc_id = data.get("npc_id", "")
    npc = get_npc(npc_id)

    if not npc:
        return jsonify({"error": f"NPC '{npc_id}' не найден"}), 404

    quest = generate_quest(
        npc=npc,
        player_level=data.get("player_level", 1),
        player_resources=data.get("player_resources", {}),
    )

    return jsonify({
        "npc": npc_to_dict(npc),
        "quest": quest_to_dict(quest),
    })


# ===================== STATUS =====================

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "server": "Kingdom Match AI",
        "version": "0.1.0",
        "active_bots": len(active_bots),
        "bots": {k: bot_to_dict(v) for k, v in active_bots.items()},
        "modules": {
            "bot_opponent": True,
            "level_generator": True,
            "npc_engine": True,
        },
        "ai_enabled": bool(os.getenv("AI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")),
        "ai_provider": os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1"),
        "ai_model": os.getenv("AI_MODEL") or os.getenv("DASHSCOPE_MODEL") or "deepseek-chat",
    })

# ===================== REPLICATE VISUALS =====================

@app.route("/api/assets", methods=["GET"])
def get_assets():
    import os as _os

    base = request.host_url.rstrip("/") + "/api/assets-img/"

    # 1. Try assets.json
    assets_path = _os.path.join(OUTPUT_DIR, "assets.json")
    if _os.path.exists(assets_path):
        with open(assets_path) as f:
            return jsonify(json.load(f))

    # 2. Build from PNGs on disk
    if not _os.path.exists(OUTPUT_DIR):
        return jsonify({"error": "No assets"}), 404

    pngs = [f for f in _os.listdir(OUTPUT_DIR) if f.endswith(".png")]
    if not pngs:
        return jsonify({"error": "No PNGs generated yet"}), 404

    enemies = {"rus": [], "horde": [], "china": []}
    kingdom_bgs = {}
    era_bgs = []
    tiles = {}
    fortress = {}
    npcs = {"rus": [], "horde": [], "china": []}

    npc_name_map = {
        "velimir": "Старец Велимир", "dobrynya": "Воевода Добрыня", "marfa": "Купчиха Марфа",
        "batu": "Темник Бату", "altan": "Алтан-шаман", "gulnara": "Гульнара-бегим",
        "libo": "Мудрец Ли Бо", "zhen": "Генерал Чжэнь", "mei": "Госпожа Мэй",
    }
    npc_kd_map = {
        "velimir": "rus", "dobrynya": "rus", "marfa": "rus",
        "batu": "horde", "altan": "horde", "gulnara": "horde",
        "libo": "china", "zhen": "china", "mei": "china",
    }

    for png in pngs:
        url = base + png
        if png.startswith("enemy_"):
            eid = png.replace("enemy_", "").rsplit("_", 1)[0]
            name_map = {"polovets":"Половецкий хан","khazar":"Хазарский каган","pecheneg":"Печенежский вождь","varangian":"Ярл Рюрик","khwarezm":"Шах Хорезма","seljuk":"Сельджукский эмир","kipchak":"Кипчакский хан","teutonic":"Тевтонский магистр","jurchen":"Чжурчжэньский воевода","tibetan":"Тибетский царь","korean":"Корейский ван","japanese":"Японский даймё"}
            kd_map = {"polovets":"rus","khazar":"rus","pecheneg":"rus","varangian":"rus","khwarezm":"horde","seljuk":"horde","kipchak":"horde","teutonic":"horde","jurchen":"china","tibetan":"china","korean":"china","japanese":"china"}
            kd = kd_map.get(eid, "rus")
            enemies[kd].append({"id": eid, "name": name_map.get(eid, eid), "url": url})
        elif png.startswith("npc_"):
            nid = png.replace("npc_", "").rsplit("_", 1)[0]
            kd = npc_kd_map.get(nid)
            if kd:
                npcs[kd].append({"id": nid, "name": npc_name_map.get(nid, nid), "url": url})
        elif png.startswith("bg_"):
            kd = png.replace("bg_", "").rsplit("_", 1)[0]
            kingdom_bgs[kd] = url
        elif png.startswith("era_"):
            try:
                era = int(png.replace("era_", "").split("_")[0])
                era_bgs.append({"era": era, "url": url})
            except ValueError:
                pass
        elif png.startswith("tile_"):
            parts = png.replace("tile_", "").replace(".png", "").rsplit("_era", 1)
            if len(parts) == 2:
                tile_type = parts[0]
                era_num = parts[1].split("_")[0]
                if tile_type not in tiles:
                    tiles[tile_type] = []
                tiles[tile_type].append({"era": int(era_num), "url": url})
        elif png.startswith("fortress_"):
            elem = png.replace("fortress_", "").rsplit("_", 1)[0]
            fortress[elem] = url

    era_bgs.sort(key=lambda e: e["era"])
    return jsonify({"enemies": enemies, "kingdom_bgs": kingdom_bgs, "era_bgs": era_bgs, "tiles": tiles, "fortress": fortress, "npcs": npcs})


@app.route("/api/generate-visuals", methods=["POST"])
def generate_visuals():
    data = request.get_json() or {}
    asset_type = data.get("type", "all")
    try:
        if asset_type == "enemies":
            result = generate_enemy_portraits(data.get("kingdom", "all"))
        elif asset_type == "kingdom_bgs":
            result = generate_kingdom_backgrounds()
        elif asset_type == "era_bgs":
            result = generate_era_backgrounds()
        elif asset_type == "tiles":
            result = generate_tile_icons()
        elif asset_type == "fortress":
            result = generate_fortress_elements()
        elif asset_type == "npcs":
            result = generate_npc_portraits(data.get("kingdom", "all"))
        else:
            result = generate_all_assets()
        return jsonify({"status": "ok", "assets": result})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Generation error: {e}"}), 500


@app.route("/api/assets-img/<path:filename>", methods=["GET"])
def serve_asset(filename):
    import os as _os
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/api/assets-status", methods=["GET"])
def assets_status():
    import os as _os
    assets_path = _os.path.join(OUTPUT_DIR, "assets.json")
    generated = _os.path.exists(assets_path)
    png_count = 0
    if _os.path.exists(OUTPUT_DIR):
        png_count = len([f for f in _os.listdir(OUTPUT_DIR) if f.endswith(".png")])
    return jsonify({
        "generated": generated,
        "png_count": png_count,
        "output_dir": OUTPUT_DIR,
        "replicate_configured": bool(os.getenv("REPLICATE_API_TOKEN")),
    })


# ===================== COMIC =====================

@app.route("/api/comic-story", methods=["GET"])
def comic_story():
    kingdom = request.args.get("kingdom", "rus")
    trigger = request.args.get("trigger", "kingdom_select")
    player_state = {
        "level": int(request.args.get("level", 1)),
        "era": int(request.args.get("era", 0)),
        "coins": int(request.args.get("coins", 0)),
    }
    story = get_or_generate_story(kingdom, trigger, player_state)
    # Картинки панелей:
    #   * Всегда подгружаем из ЛОКАЛЬНОГО КЕША (allow_remote=False) — мгновенно, без сети.
    #   * Если KM_COMIC_IMAGES=1 в .env — для недостающих идём в Replicate (платно).
    try:
        url_base = request.host_url.rstrip("/") + "/api/assets-img/"
        allow_remote = os.getenv("KM_COMIC_IMAGES", "0") == "1"
        populate_panel_images(story, url_base, allow_remote=allow_remote)
    except Exception as e:
        print(f"[ComicAPI] populate_panel_images failed: {e}")
    return jsonify(story_to_dict(story))


# ===================== MAIN =====================

if __name__ == "__main__":
    port = int(os.getenv("KM_AI_PORT", "5050"))
    debug = os.getenv("KM_AI_DEBUG", "0") == "1"
    print(f"""
╔══════════════════════════════════════════╗
║      Kingdom Match AI Server v0.1        ║
╠══════════════════════════════════════════╣
║  Endpoints:                              ║
║  POST /api/generate-levels               ║
║  POST /api/bot-attack                    ║
║  POST /api/npc-dialogue                  ║
║  POST /api/npc-quest                     ║
║  GET  /api/npc-list                      ║
║  GET  /api/status                        ║
║  GET  /api/assets                        ║
║  POST /api/generate-visuals              ║
║  GET  /api/assets-img/<path>             ║
║  GET  /api/assets-status                 ║
╠══════════════════════════════════════════╣
║  AI (LLM):  {"ENABLED" if (os.getenv('AI_API_KEY') or os.getenv('DEEPSEEK_API_KEY') or os.getenv('DASHSCOPE_API_KEY')) else "DISABLED":<32}║
║  Replicate: {"ENABLED" if os.getenv('REPLICATE_API_TOKEN') else "DISABLED":<32}║
║  Port: {port:<34}║
╚══════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=debug)