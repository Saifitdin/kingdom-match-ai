"""
AI Level Generator for Kingdom Match.
Использует Qwen (DashScope) для генерации интересных конфигураций уровней.
"""

import json
import os
import random
import math
from dataclasses import dataclass, field
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
AI_MODEL = os.getenv("AI_MODEL") or os.getenv("DASHSCOPE_MODEL") or "deepseek-chat"
DASHSCOPE_API_KEY = AI_API_KEY
DASHSCOPE_MODEL = AI_MODEL


@dataclass
class LevelConfig:
    """Конфигурация одного уровня."""
    id: int
    name: str
    enemy_name: str
    enemy_hp: int
    timer: int                # секунд
    tiles: list               # типы тайлов на уровне (3-6 типов)
    goals: list               # [{type: "warrior", count: 15}, ...]
    star_thresholds: list     # [для 1★, для 2★, для 3★] в % HP врага
    min_moves: int            # минимальное число ходов
    board_size: int = 8
    special_rules: Optional[str] = None  # e.g. "no_faith", "double_cavalry"
    narrative: str = ""       # текстовое описание уровня


@dataclass
class LevelPack:
    """Пачка уровней (5-10 штук)."""
    kingdom: str
    era: int
    start_level: int
    difficulty: str           # "easy", "normal", "hard"
    levels: list = field(default_factory=list)


# ----- Автономный генератор (без API) -----

def generate_level_fast(level_id: int, era: int, kingdom: str) -> LevelConfig:
    """
    Быстрая генерация уровня без вызова API.
    Используется как fallback или для массовой генерации.
    """
    TILE_TYPES = ['warrior', 'archer', 'cavalry', 'faith', 'gold', 'food']

    era_names = {
        0: {"rus": "Киевский рубеж", "horde": "Край степи", "china": "Шёлковый тракт"},
        1: {"rus": "Новгородский торг", "horde": "Переправа через Итиль", "china": "Бамбуковая роща"},
        2: {"rus": "Ледовое побоище", "horde": "Курултай", "china": "Запретный город"},
        3: {"rus": "Взятие Казани", "horde": "Великий шёлковый путь", "china": "Императорский флот"},
    }

    enemy_pool = {
        "rus": ["Половец", "Хазар", "Печенег", "Варяг", "Литвин"],
        "horde": ["Хорезмиец", "Сельджук", "Кипчак", "Булгар", "Черкес"],
        "china": ["Чжурчжэнь", "Тибетец", "Уйгур", "Кореец", "Монгол"],
    }

    # Сложность растёт с уровнем
    enemy_hp = 80 + level_id * 25 + random.randint(-10, 10)
    timer = max(45, 120 - math.floor(level_id / 2) * 2 + random.randint(-5, 5))

    # Выбираем 3-4 типа тайлов из 6 как цели
    num_goals = min(3, 1 + level_id // 5)
    goal_types = random.sample(TILE_TYPES, num_goals)
    goals = []
    for t in goal_types:
        base = 8 + level_id * 3
        goals.append({"type": t, "count": base + random.randint(-2, 4)})

    # Звёзды: 60%, 85%, 100% HP
    star_thresholds = [
        int(enemy_hp * 0.6),
        int(enemy_hp * 0.85),
        enemy_hp,
    ]

    # Число ходов
    min_moves = sum(g["count"] for g in goals) // 3 + random.randint(2, 5)

    # Особое правило (шанс 15%)
    special_rules = None
    if random.random() < 0.15:
        rules_pool = [
            "no_faith",
            "double_cavalry",
            "only_3_types",
            "extra_timer",
            "boss_level",
        ]
        special_rules = random.choice(rules_pool)

    # Нарратив
    narratives = [
        f"Враг подошёл к стенам! Собери {goals[0]['count']} {goals[0]['type']}, чтобы отбросить его.",
        f"Караван с припасами в опасности. Защити его, собрав нужные тайлы!",
        f"Разведчики донесли: враг слаб против {goals[-1]['type']}. Используй это!",
        f"Битва за переправу! Время не ждёт — у тебя {timer} секунд.",
    ]

    return LevelConfig(
        id=level_id,
        name=era_names.get(era, era_names[0]).get(kingdom, f"Уровень {level_id}"),
        enemy_name=random.choice(enemy_pool.get(kingdom, enemy_pool["rus"])),
        enemy_hp=enemy_hp,
        timer=timer,
        tiles=TILE_TYPES,
        goals=goals,
        star_thresholds=star_thresholds,
        min_moves=min_moves,
        special_rules=special_rules,
        narrative=random.choice(narratives),
    )


# ----- AI генератор (через Qwen) -----

def generate_level_pack_ai(
    kingdom: str,
    era: int,
    start_level: int,
    count: int = 5,
    difficulty: str = "normal",
) -> Optional[LevelPack]:
    """
    AI-генерация пачки уровней через Qwen.
    Возвращает LevelPack или None при ошибке API.
    """
    if not DASHSCOPE_API_KEY:
        print("[!] DASHSCOPE_API_KEY не задан. Использую быстрый генератор.")
        return None

    prompt = f"""Ты — гейм-дизайнер Kingdom Match. Сгенерируй JSON-массив из {count} уровней.

Контекст:
- Королевство: {kingdom} (rus — Древняя Русь, horde — Великая Орда, china — Поднебесная)
- Эпоха: {era} (0-3, от раннего средневековья до ренессанса)
- Начальный номер уровня: {start_level}
- Сложность: {difficulty} (easy/normal/hard)

Формат каждого уровня:
{{
  "name": "название уровня на русском (до 30 символов)",
  "enemy_name": "имя врага (одно слово)",
  "enemy_hp": число (80–300),
  "timer": число секунд (45–120),
  "goals": [{{"type": "warrior/archer/cavalry/faith/gold/food", "count": число (5–40)}}],
  "min_moves": число (8–30),
  "special_rules": null или "no_faith"/"double_cavalry"/"only_3_types"/"extra_timer"/"boss_level",
  "narrative": "краткое описание битвы на русском (20-50 слов)"
}}

Требования:
- Каждый уровень должен быть сложнее предыдущего
- Чередуй типы целей (не повторяй один и тот же тип 2 уровня подряд)
- boss_level только на уровнях, кратных 5
- timer уменьшается, enemy_hp растёт к концу пачки
- narrative должен быть атмосферным, упоминать врага и локацию

Ответ: ТОЛЬКО JSON-массив, без markdown, без пояснений."""

    try:
        url = AI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": DASHSCOPE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 2000,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"]
        # Извлекаем JSON из ответа (может быть обёрнут в ```json)
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        data = json.loads(content)

        levels = []
        for i, item in enumerate(data):
            lvl = LevelConfig(
                id=start_level + i,
                name=item.get("name", f"Уровень {start_level + i}"),
                enemy_name=item.get("enemy_name", "Враг"),
                enemy_hp=item.get("enemy_hp", 100 + i * 25),
                timer=item.get("timer", 90),
                tiles=["warrior", "archer", "cavalry", "faith", "gold", "food"],
                goals=item.get("goals", [{"type": "warrior", "count": 10}]),
                star_thresholds=[
                    int(item.get("enemy_hp", 100) * 0.6),
                    int(item.get("enemy_hp", 100) * 0.85),
                    item.get("enemy_hp", 100),
                ],
                min_moves=item.get("min_moves", 15),
                special_rules=item.get("special_rules"),
                narrative=item.get("narrative", ""),
            )
            levels.append(lvl)

        return LevelPack(
            kingdom=kingdom,
            era=era,
            start_level=start_level,
            difficulty=difficulty,
            levels=levels,
        )

    except Exception as e:
        print(f"[!] Ошибка AI-генерации: {e}")
        return None


def generate_level_pack(
    kingdom: str,
    era: int,
    start_level: int,
    count: int = 5,
    difficulty: str = "normal",
    use_ai: bool = True,
) -> LevelPack:
    """
    Сгенерировать пачку уровней. Пробует AI, при неудаче — быстрый генератор.
    """
    pack = None
    if use_ai:
        pack = generate_level_pack_ai(kingdom, era, start_level, count, difficulty)

    if pack is None:
        pack = LevelPack(
            kingdom=kingdom,
            era=era,
            start_level=start_level,
            difficulty=difficulty,
        )
        for i in range(count):
            pack.levels.append(
                generate_level_fast(start_level + i, era, kingdom)
            )

    return pack


def validate_level(level: LevelConfig) -> dict:
    """
    Проверить уровень на решаемость.
    Возвращает словарь с результатами проверки.
    """
    issues = []

    # Проверка: хватает ли мин. ходов для целей
    total_goal_tiles = sum(g["count"] for g in level.goals)
    max_tiles_per_move = 8  # реалистичный максимум за ход (с каскадами)
    min_moves_needed = math.ceil(total_goal_tiles / max_tiles_per_move)

    if level.min_moves < min_moves_needed:
        issues.append(
            f"⚠️ Ходов ({level.min_moves}) может не хватить "
            f"для целей ({total_goal_tiles} тайлов). Минимум: {min_moves_needed}"
        )

    # Проверка: есть ли цели, которые невозможно выполнить
    if level.special_rules == "no_faith":
        if any(g["type"] == "faith" for g in level.goals):
            issues.append("❌ special_rules='no_faith', но faith в целях!")

    # Проверка: таймер
    if level.timer < 30:
        issues.append("⚠️ Слишком мало времени (таймер < 30 сек)")

    if level.timer > 180:
        issues.append("⚠️ Слишком много времени (таймер > 180 сек)")

    # Проверка: HP врага
    if level.enemy_hp < 30:
        issues.append("⚠️ Слишком мало HP врага")

    if level.enemy_hp > 500:
        issues.append("⚠️ Слишком много HP врага — уровень затянется")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "min_moves_needed": min_moves_needed,
        "total_goal_tiles": total_goal_tiles,
    }


# ----- Экспорт -----

def level_config_to_dict(level: LevelConfig) -> dict:
    return {
        "id": level.id,
        "name": level.name,
        "enemy_name": level.enemy_name,
        "enemy_hp": level.enemy_hp,
        "timer": level.timer,
        "tiles": level.tiles,
        "goals": level.goals,
        "star_thresholds": level.star_thresholds,
        "min_moves": level.min_moves,
        "board_size": level.board_size,
        "special_rules": level.special_rules,
        "narrative": level.narrative,
    }


def level_pack_to_dict(pack: LevelPack) -> dict:
    return {
        "kingdom": pack.kingdom,
        "era": pack.era,
        "start_level": pack.start_level,
        "difficulty": pack.difficulty,
        "levels": [level_config_to_dict(lvl) for lvl in pack.levels],
    }
