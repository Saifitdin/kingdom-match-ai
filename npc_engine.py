"""
NPC Engine for Kingdom Match.
Диалоги, квесты, реакции на прогресс игрока — с личностью и памятью.
Поддерживает AI-генерацию через Qwen и локальные шаблоны.
"""

import json
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-plus")


# ----- Типы квестов -----

class QuestType(Enum):
    COLLECT = "collect"           # собрать N ресурсов
    REACH_LEVEL = "reach_level"   # достичь уровня
    BUILD = "build"               # построить здание
    DEFEAT = "defeat"             # победить врага N раз
    SURVIVE = "survive"           # выдержать N атак бота


@dataclass
class Quest:
    """Квест от NPC."""
    id: str
    giver: str                # имя NPC
    type: QuestType
    title: str
    description: str
    target: dict              # e.g. {"resource": "gold", "count": 500}
    progress: int = 0
    reward_coins: int = 0
    reward_resources: dict = field(default_factory=dict)
    completed: bool = False
    expires_at: float = 0     # timestamp (0 = бессрочный)


# ----- NPC определения -----

@dataclass
class NPC:
    """Неигровой персонаж."""
    id: str
    name: str
    kingdom: str               # "rus", "horde", "china"
    role: str                  # "guide", "merchant", "general", "sage", "spy"
    avatar: str                # эмодзи
    personality: str           # описание личности
    greeting: str
    farewell: str
    memory: list = field(default_factory=list)  # история диалогов


NPC_REGISTRY = {
    "rus": [
        NPC(
            id="velimir", name="Старец Велимир", kingdom="rus", role="guide",
            avatar="🧙", personality="Мудрый и терпеливый старец-волхв. Говорит загадками и пословицами.",
            greeting="Здрав буди, княже! Что тревожит душу твою?",
            farewell="Ступай с миром. Да хранят тебя предки."
        ),
        NPC(
            id="dobrynya", name="Воевода Добрыня", kingdom="rus", role="general",
            avatar="⚔️", personality="Суровый воин. Немногословен. Ценит доблесть и честь.",
            greeting="Докладывай, воевода. Что на рубежах?",
            farewell="Крепи стены. Враг не дремлет."
        ),
        NPC(
            id="marfa", name="Купчиха Марфа", kingdom="rus", role="merchant",
            avatar="👩‍🌾", personality="Хитрая торговка. Падка на золото, но держит слово.",
            greeting="Ой, княже! Товар заморский привезла — глянь-ка!",
            farewell="Заходи ещё! Серебро-золото всегда в цене."
        ),
    ],
    "horde": [
        NPC(
            id="batu", name="Темник Бату", kingdom="horde", role="guide",
            avatar="🤵", personality="Опытный полководец. Стратег. Говорит прямо, без лести.",
            greeting="Сайн байна уу, хан! Какие вести из степи?",
            farewell="Пусть твой конь будет быстрым, а сабля острой."
        ),
        NPC(
            id="altan", name="Алтан-шаман", kingdom="horde", role="sage",
            avatar="🪬", personality="Шаман, говорящий с духами. Видит знаки в дыму и звёздах.",
            greeting="Духи шепчут... Ты пришёл за советом, великий хан?",
            farewell="Дым рассеялся. Иди — Небо благоволит тебе."
        ),
        NPC(
            id="gulnara", name="Гульнара-бегим", kingdom="horde", role="merchant",
            avatar="👸", personality="Знатная бегим с караванами. Щедра, но цену себе знает.",
            greeting="Мой караван привёз шёлк и пряности. Интересует, хан?",
            farewell="Да будет твой достаток неисчерпаем, как песок в пустыне."
        ),
    ],
    "china": [
        NPC(
            id="libo", name="Мудрец Ли Бо", kingdom="china", role="guide",
            avatar="👲", personality="Поэт и философ. Говорит стихами. Видит гармонию во всём.",
            greeting="Луна над пагодой светла... Какие думы тревожат императора?",
            farewell="Путь в тысячу ли начинается с первого шага."
        ),
        NPC(
            id="zhen", name="Генерал Чжэнь", kingdom="china", role="general",
            avatar="🐉", personality="Дисциплинированный стратег. Почитает Сунь-Цзы. Носит нефритовый меч.",
            greeting="Войско построено, император. Жду приказа.",
            farewell="Победа — в подготовке. Я займусь войсками."
        ),
        NPC(
            id="mei", name="Госпожа Мэй", kingdom="china", role="spy",
            avatar="🪭", personality="Тайный агент императора. Знает всё и обо всех. Говорит шёпотом.",
            greeting="Тсс... у меня сведения о враге. Желаешь узнать?",
            farewell="Стены имеют уши, а ветер — глаза. Будь осторожен."
        ),
    ],
}


def get_npc(npc_id: str) -> Optional[NPC]:
    """Получить NPC по ID."""
    for kingdom_npcs in NPC_REGISTRY.values():
        for npc in kingdom_npcs:
            if npc.id == npc_id:
                return npc
    return None


def get_kingdom_npcs(kingdom: str) -> list:
    """Все NPC королевства."""
    return NPC_REGISTRY.get(kingdom, [])


# ----- Квесты -----

QUEST_TEMPLATES = {
    QuestType.COLLECT: [
        {"title": "Пополнить казну", "desc": "Собери {target} {resource} для казны королевства.",
         "resource": "gold", "count_range": (200, 800), "coins": 150, "res": {"faith": 5}},
        {"title": "Провиант для войска", "desc": "Воины голодают! Собери {target} {resource}.",
         "resource": "food", "count_range": (300, 1000), "coins": 100, "res": {"warrior": 10}},
        {"title": "Священный сбор", "desc": "Храм нуждается в подношениях: {target} {resource}.",
         "resource": "faith", "count_range": (100, 500), "coins": 200, "res": {"archer": 5}},
    ],
    QuestType.REACH_LEVEL: [
        {"title": "Покоритель рубежей", "desc": "Достигни уровня {target}.",
         "count_range": (5, 20), "coins": 300, "res": {"cavalry": 8}},
    ],
    QuestType.BUILD: [
        {"title": "Укрепить твердыню", "desc": "Построй {target} в своей крепости.",
         "building": "walls", "coins": 250, "res": {"warrior": 10, "archer": 5}},
        {"title": "Глубокая защита", "desc": "Построй {target} вокруг крепости.",
         "building": "moat", "coins": 350, "res": {"food": 20}},
        {"title": "Дозорные вышки", "desc": "Возведи {target} для обзора.",
         "building": "tower", "coins": 200, "res": {"archer": 10}},
    ],
    QuestType.DEFEAT: [
        {"title": "Разбить врага", "desc": "Победи {target} врагов в битвах.",
         "count_range": (3, 10), "coins": 400, "res": {"cavalry": 5, "gold": 30}},
    ],
    QuestType.SURVIVE: [
        {"title": "Выстоять осаду", "desc": "Переживи {target} атак бота-противника.",
         "count_range": (2, 6), "coins": 350, "res": {"warrior": 15}},
    ],
}


def generate_quest(npc: NPC, player_level: int, player_resources: dict) -> Quest:
    """Сгенерировать квест от NPC под текущий прогресс игрока."""
    # Выбираем тип квеста по роли NPC
    role_quest_map = {
        "guide": [QuestType.REACH_LEVEL, QuestType.BUILD],
        "merchant": [QuestType.COLLECT],
        "general": [QuestType.DEFEAT, QuestType.SURVIVE],
        "sage": [QuestType.COLLECT, QuestType.REACH_LEVEL],
        "spy": [QuestType.DEFEAT, QuestType.SURVIVE],
    }
    possible_types = role_quest_map.get(npc.role, [QuestType.COLLECT])
    quest_type = random.choice(possible_types)

    templates = QUEST_TEMPLATES[quest_type]
    template = random.choice(templates)

    # Генерируем цель
    target = {}
    if quest_type == QuestType.COLLECT:
        lo, hi = template["count_range"]
        count = random.randint(lo, hi) + player_level * 10
        resource = template["resource"]
        target = {"resource": resource, "count": count}
        title = template["title"]
        desc = template["desc"].format(target=count, resource=resource)
    elif quest_type == QuestType.REACH_LEVEL:
        lo, hi = template["count_range"]
        target_level = player_level + random.randint(lo, hi)
        target = {"level": target_level}
        title = template["title"]
        desc = template["desc"].format(target=target_level)
    elif quest_type == QuestType.BUILD:
        building = template["building"]
        target = {"building": building}
        title = template["title"]
        desc = template["desc"].format(target=building)
    elif quest_type == QuestType.DEFEAT:
        lo, hi = template["count_range"]
        count = random.randint(lo, hi)
        target = {"enemies_defeated": count}
        title = template["title"]
        desc = template["desc"].format(target=count)
    elif quest_type == QuestType.SURVIVE:
        lo, hi = template["count_range"]
        count = random.randint(lo, hi)
        target = {"attacks_survived": count}
        title = template["title"]
        desc = template["desc"].format(target=count)
    else:
        title = "Таинственное поручение"
        desc = "Выполни особое задание..."
        target = {}

    # Награда
    coins = template["coins"] + player_level * 25
    resources = template.get("res", {})

    quest_id = f"q_{npc.id}_{int(time.time())}"

    return Quest(
        id=quest_id,
        giver=npc.name,
        type=quest_type,
        title=title,
        description=desc,
        target=target,
        reward_coins=coins,
        reward_resources=resources,
    )


# ----- Диалоги -----

def generate_dialogue(
    npc: NPC,
    player_state: dict,
    context: str = "greeting",
    use_ai: bool = True,
) -> str:
    """
    Сгенерировать реплику NPC.
    
    Args:
        npc: NPC объект
        player_state: состояние игрока (level, coins, era, hp, resources...)
        context: "greeting", "quest_complete", "attack_warning", "era_up", "idle"
        use_ai: использовать Qwen для генерации
    
    Returns:
        Строка с репликой
    """
    # Сначала пробуем шаблоны
    template_reply = _dialogue_template(npc, player_state, context)
    
    if not use_ai or not DASHSCOPE_API_KEY:
        return template_reply
    
    # AI-генерация
    try:
        ai_reply = _dialogue_ai(npc, player_state, context, template_reply)
        return ai_reply if ai_reply else template_reply
    except Exception:
        return template_reply


def _dialogue_template(npc: NPC, state: dict, context: str) -> str:
    """Шаблонные реплики NPC."""
    era_names = ["Раннее средневековье", "Высокое средневековье", 
                 "Позднее средневековье", "Ренессанс"]
    era = era_names[min(state.get("era", 0), 3)]
    level = state.get("level", 1)
    hp_pct = max(0, state.get("hp", 100) / max(1, state.get("hp_max", 100))) * 100

    replies = {
        "greeting": [
            f"{npc.greeting}",
            f"А, это ты! Уровень {level} — растёшь на глазах.",
            f"Эпоха {era}... Помню, как всё начиналось.",
        ],
        "quest_complete": [
            f"Отлично! Ты справился. Держи награду — {npc.name} слов на ветер не бросает.",
            f"Я знал, что ты сможешь. Королевство крепнет с каждым днём.",
            f"Великие дела вершатся малыми шагами. Ты доказал это.",
        ],
        "attack_warning": [
            f"⚠️ Враг у ворот! HP крепости: {hp_pct:.0f}%. Готовься к битве!",
            f"Разведка донесла: противник собирает силы. Укрепи стены!",
            f"{(npc.name)}: 'Лучшая защита — нападение. Ударь первым!'",
        ],
        "era_up": [
            f"Новая эпоха — {era}! Мир меняется, и ты вместе с ним.",
            f"Поздравляю с переходом в эру {era}! Твои враги трепещут.",
            f"Величие твоё растёт. {era} открывает новые горизонты.",
        ],
        "idle": [
            f"Сегодня тихо... Может, займёмся крепостью? Стены ждут.",
            f"Купцы спрашивают, не нужно ли чего. Казны хватает?",
            f"Звёзды шепчут: скоро грядёт великая битва.",
        ],
    }

    pool = replies.get(context, replies["idle"])
    npc.memory.append({"context": context, "time": time.time()})
    return random.choice(pool)


def _dialogue_ai(npc: NPC, state: dict, context: str, fallback: str) -> Optional[str]:
    """AI-генерация реплики через Qwen."""
    era_names = ["Раннее средневековье", "Высокое средневековье", 
                 "Позднее средневековье", "Ренессанс"]
    era = era_names[min(state.get("era", 0), 3)]

    prompt = f"""Ты — {npc.name}, {npc.role} в игре Kingdom Match.
Королевство: {npc.kingdom}.
Твоя личность: {npc.personality}

Контекст игрока:
- Уровень: {state.get('level', 1)}
- Эпоха: {era}
- HP крепости: {state.get('hp', 100)}/{state.get('hp_max', 100)}
- Монеты: {state.get('coins', 0)}
- Ресурсы: {json.dumps(state.get('resources', {}), ensure_ascii=False)}

Ситуация: {context}

Пример реплики (шаблон): "{fallback}"

Напиши ОДНУ короткую реплику (1-2 предложения) от лица {npc.name}, 
отражающую личность и текущую ситуацию. На русском языке. Только реплика, без пояснений."""

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DASHSCOPE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 120,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    npc.memory.append({"context": context, "time": time.time(), "ai": True})
    return content


# ----- Экспорт -----

def npc_to_dict(npc: NPC) -> dict:
    return {
        "id": npc.id,
        "name": npc.name,
        "kingdom": npc.kingdom,
        "role": npc.role,
        "avatar": npc.avatar,
        "personality": npc.personality,
        "greeting": npc.greeting,
        "farewell": npc.farewell,
        "memory_size": len(npc.memory),
    }


def quest_to_dict(quest: Quest) -> dict:
    return {
        "id": quest.id,
        "giver": quest.giver,
        "type": quest.type.value,
        "title": quest.title,
        "description": quest.description,
        "target": quest.target,
        "progress": quest.progress,
        "reward_coins": quest.reward_coins,
        "reward_resources": quest.reward_resources,
        "completed": quest.completed,
    }
