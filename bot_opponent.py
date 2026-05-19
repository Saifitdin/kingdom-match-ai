"""
AI Bot Opponent for Kingdom Match.
Атакует крепость игрока с разными стратегиями и уровнями сложности.
"""

import random
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    NIGHTMARE = "nightmare"


class Strategy(Enum):
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"
    RESOURCE_RAID = "resource_raid"
    BALANCED = "balanced"
    SIEGE = "siege"


@dataclass
class BotState:
    name: str
    difficulty: Difficulty
    strategy: Strategy
    level: int = 1
    power: int = 50
    siege_bonus: int = 0
    attacks_launched: int = 0
    resources_stolen: dict = field(default_factory=lambda: {
        "warrior": 0, "archer": 0, "cavalry": 0,
        "faith": 0, "gold": 0, "food": 0
    })
    cooldown: int = 0
    rage: float = 0.0


BOT_POOL = {
    "rus": [
        {"name": "Половецкий хан Котян",     "strategy": Strategy.AGGRESSIVE,     "power": 45},
        {"name": "Хазарский каган",          "strategy": Strategy.RESOURCE_RAID,  "power": 55},
        {"name": "Печенежский вождь Куря",    "strategy": Strategy.BALANCED,       "power": 50},
        {"name": "Византийский стратиг",      "strategy": Strategy.SIEGE,          "power": 65},
        {"name": "Ярл Рюрик",                "strategy": Strategy.DEFENSIVE,      "power": 70},
    ],
    "horde": [
        {"name": "Шах Хорезма Мухаммед",     "strategy": Strategy.AGGRESSIVE,     "power": 55},
        {"name": "Султан Бейбарс",           "strategy": Strategy.BALANCED,       "power": 60},
        {"name": "Китайский генерал",         "strategy": Strategy.SIEGE,          "power": 50},
        {"name": "Тевтонский магистр",        "strategy": Strategy.DEFENSIVE,      "power": 65},
        {"name": "Сельджукский эмир",         "strategy": Strategy.RESOURCE_RAID,  "power": 45},
    ],
    "china": [
        {"name": "Чжурчжэньский воевода",    "strategy": Strategy.AGGRESSIVE,     "power": 50},
        {"name": "Тибетский царь",            "strategy": Strategy.SIEGE,          "power": 60},
        {"name": "Корейский ван",            "strategy": Strategy.DEFENSIVE,      "power": 45},
        {"name": "Уйгурский каган",           "strategy": Strategy.RESOURCE_RAID,  "power": 55},
        {"name": "Японский даймё",           "strategy": Strategy.BALANCED,       "power": 65},
    ],
}


def create_bot(kingdom: str, player_level: int, difficulty: Difficulty) -> BotState:
    pool = BOT_POOL.get(kingdom, BOT_POOL["rus"])
    template = random.choice(pool)

    diff_mult = {
        Difficulty.EASY: 0.6,
        Difficulty.MEDIUM: 1.0,
        Difficulty.HARD: 1.5,
        Difficulty.NIGHTMARE: 2.2,
    }
    level_scale = 1.0 + (player_level - 1) * 0.08
    power = int(template["power"] * diff_mult[difficulty] * level_scale)

    return BotState(
        name=template["name"],
        difficulty=difficulty,
        strategy=template["strategy"],
        level=player_level,
        power=power,
    )


@dataclass
class AttackResult:
    bot_name: str
    strategy: str
    raw_damage: int
    actual_damage: int
    resources_stolen: dict
    special_effect: Optional[str]
    narrative: str
    siege_bonus_applied: int


def simulate_attack(
    bot: BotState,
    player_hp: int,
    player_defense: int,
    player_resources: dict,
    player_era: int = 0,
) -> AttackResult:
    bot.attacks_launched += 1

    strategy_dmg = {
        Strategy.AGGRESSIVE:     (0.8, 1.4),
        Strategy.DEFENSIVE:      (0.4, 0.7),
        Strategy.RESOURCE_RAID:  (0.3, 0.6),
        Strategy.BALANCED:       (0.5, 0.9),
        Strategy.SIEGE:          (0.3, 0.5),
    }
    lo, hi = strategy_dmg[bot.strategy]
    raw_damage = int(bot.power * random.uniform(lo, hi))

    siege_bonus_applied = 0
    if bot.strategy == Strategy.SIEGE:
        bot.siege_bonus += random.randint(3, 8)
        siege_bonus_applied = bot.siege_bonus
        raw_damage += bot.siege_bonus

    if bot.rage > 0:
        raw_damage = int(raw_damage * (1.0 + bot.rage))
        bot.rage = max(0, bot.rage - 0.15)

    defense_factor = max(0.1, 1.0 - player_defense / (player_defense + 100))
    actual_damage = max(1, int(raw_damage * defense_factor))

    resources_stolen = {}
    if bot.strategy in (Strategy.RESOURCE_RAID, Strategy.BALANCED):
        steal_pct = 0.05 if bot.strategy == Strategy.BALANCED else 0.12
        for res, amount in player_resources.items():
            if amount > 0 and random.random() < 0.4:
                stolen = max(1, int(amount * steal_pct))
                resources_stolen[res] = stolen
                bot.resources_stolen[res] = bot.resources_stolen.get(res, 0) + stolen

    special_effect = None
    special_roll = random.random()
    if special_roll < 0.08:
        special_effect = "fire_arrows"
        actual_damage = int(actual_damage * 1.3)
    elif special_roll < 0.16:
        special_effect = "poison"
    elif special_roll < 0.22:
        special_effect = "sabotage"
        for res in random.sample(list(player_resources.keys()), min(2, len(player_resources))):
            if player_resources.get(res, 0) > 0:
                extra = max(1, int(player_resources[res] * 0.08))
                resources_stolen[res] = resources_stolen.get(res, 0) + extra

    narratives = _generate_narrative(bot, actual_damage, resources_stolen, special_effect)

    return AttackResult(
        bot_name=bot.name,
        strategy=bot.strategy.value,
        raw_damage=raw_damage,
        actual_damage=actual_damage,
        resources_stolen=resources_stolen,
        special_effect=special_effect,
        narrative=narratives,
        siege_bonus_applied=siege_bonus_applied,
    )


def _generate_narrative(bot: BotState, dmg: int, stolen: dict, effect: Optional[str]) -> str:
    lines = [f"⚔️ **{bot.name}** атакует твою крепость!"]

    strategy_flavor = {
        Strategy.AGGRESSIVE: "Стремительная атака! Враг бросает все силы на штурм.",
        Strategy.DEFENSIVE: "Враг строит осадные орудия и ждёт...",
        Strategy.RESOURCE_RAID: "Налётчики обходят стены — они охотятся за ресурсами!",
        Strategy.BALANCED: "Враг наступает расчётливо, прикрывая фланги.",
        Strategy.SIEGE: f"Осада усиливается! Накопленный бонус: +{bot.siege_bonus}.",
    }
    lines.append(strategy_flavor.get(bot.strategy, ""))

    if effect == "fire_arrows":
        lines.append("🔥 Огненные стрелы! Урон увеличен на 30%!")
    elif effect == "poison":
        lines.append("☠️ Отравленные клинки! Твоя крепость будет терять HP 3 хода.")
    elif effect == "sabotage":
        lines.append("🕵️ Диверсанты проникли в крепость и украли дополнительные ресурсы!")

    lines.append(f"🛡️ Твоя крепость получает **{dmg} ед. урона**.")

    if stolen:
        stolen_str = ", ".join(f"{v}×{k}" for k, v in stolen.items())
        lines.append(f"📦 Украдено: {stolen_str}")

    return "\n".join(lines)


def bot_gets_stronger(bot: BotState, player_won_last: bool):
    if player_won_last:
        bot.rage = min(1.0, bot.rage + 0.2)
        bot.power += random.randint(2, 5)
    else:
        bot.power += random.randint(1, 3)
        bot.rage = max(0, bot.rage - 0.1)


def get_next_attack_cooldown(bot: BotState) -> int:
    base = {
        Strategy.AGGRESSIVE: (2, 5),
        Strategy.DEFENSIVE: (5, 10),
        Strategy.RESOURCE_RAID: (3, 7),
        Strategy.BALANCED: (4, 8),
        Strategy.SIEGE: (6, 12),
    }
    lo, hi = base[bot.strategy]
    diff_factor = {
        Difficulty.EASY: 1.5,
        Difficulty.MEDIUM: 1.0,
        Difficulty.HARD: 0.7,
        Difficulty.NIGHTMARE: 0.5,
    }
    lo = max(1, int(lo * diff_factor[bot.difficulty]))
    hi = max(2, int(hi * diff_factor[bot.difficulty]))
    return random.randint(lo, hi)


def bot_to_dict(bot: BotState) -> dict:
    return {
        "name": bot.name,
        "difficulty": bot.difficulty.value,
        "strategy": bot.strategy.value,
        "level": bot.level,
        "power": bot.power,
        "siege_bonus": bot.siege_bonus,
        "attacks_launched": bot.attacks_launched,
        "rage": round(bot.rage, 2),
        "cooldown": bot.cooldown,
        "resources_stolen": bot.resources_stolen,
    }


def attack_result_to_dict(result: AttackResult) -> dict:
    return {
        "bot_name": result.bot_name,
        "strategy": result.strategy,
        "raw_damage": result.raw_damage,
        "actual_damage": result.actual_damage,
        "resources_stolen": result.resources_stolen,
        "special_effect": result.special_effect,
        "narrative": result.narrative,
        "siege_bonus_applied": result.siege_bonus_applied,
    }
