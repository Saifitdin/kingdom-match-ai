"""
Comic Engine for Kingdom Match.
Generates story-driven comic panels for the game narrative.
"""

import os
import json
import random
from dataclasses import dataclass, field
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
# Универсальный OpenAI-совместимый клиент: DeepSeek/Qwen/OpenAI/любой
AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
AI_MODEL = os.getenv("AI_MODEL") or os.getenv("DASHSCOPE_MODEL") or "deepseek-chat"
# Алиасы для обратной совместимости в коде ниже
DASHSCOPE_API_KEY = AI_API_KEY
DASHSCOPE_MODEL = AI_MODEL


@dataclass
class ComicPanel:
    index: int
    trigger: str
    layout: str
    caption: str
    speaker: str
    dialogue: str
    image_prompt: str
    image_url: str = ""


@dataclass
class ComicStory:
    kingdom: str
    title: str
    panels: list = field(default_factory=list)


STORY_TEMPLATES = {
    "rus": {
        "title": "Князь и Степь",
        "kingdom_select": [
            {"layout": "top_banner", "caption": "Русь, XII век. Земли, раздробленные на княжества...",
             "speaker": "Narrator", "dialogue": "Враг у ворот. Половецкая орда идёт с юга. Кто встанет на защиту?",
             "prompt": "Comic book panel, Ancient Rus 12th century, young prince on horseback on hill overlooking wooden kremlin, dramatic sky, ink style, bold lines, color"},
            {"layout": "full", "speaker": "Старец Велимир",
             "dialogue": "Княже! Ты — последняя надежда. Возьми меч предков. Веди дружину!",
             "prompt": "Comic panel, old wise man with long white beard in slavic robes, pointing at ancient sword on stone altar, dramatic lighting, dark forest bg"},
            {"layout": "full", "speaker": "Narrator",
             "dialogue": "Так начинается путь... От деревянного частокола — до каменных стен. От дружины — до великой армии.",
             "prompt": "Comic book splash page, epic medieval battle scene, knights clashing, dramatic composition, comic book style, heavy inks"},
        ],
    },
    "horde": {
        "title": "Хан Великой Степи",
        "kingdom_select": [
            {"layout": "top_banner", "caption": "Великая Степь, XIII век. Бескрайние просторы под Вечным Небом...",
             "speaker": "Narrator", "dialogue": "Хан собирает тумены. Шах Хорезма бросил вызов. Кто ответит?",
             "prompt": "Comic book panel, vast mongolian steppe at sunset, warrior on horseback holding banner, epic scale, comic style bold lines"},
            {"layout": "full", "speaker": "Темник Бату",
             "dialogue": "Великий хан! Твои воины готовы. Конница ждёт сигнала. Покажи врагу силу Орды!",
             "prompt": "Comic panel, mongol general in ornate armor, pointing at map on camp table, yurts and horses in background, dramatic lighting"},
            {"layout": "full", "speaker": "Narrator",
             "dialogue": "От юрты до каменного дворца. От сотни всадников — до великой армады. Степь помнит своих героев.",
             "prompt": "Comic book splash, massive cavalry charge across steppe, dust clouds, warriors with bows, epic battle, comic style"},
        ],
    },
    "china": {
        "title": "Император Поднебесной",
        "kingdom_select": [
            {"layout": "top_banner", "caption": "Империя Тан. Золотой век Поднебесной...",
             "speaker": "Narrator", "dialogue": "Чжурчжэни у северных границ. Император должен защитить свой народ.",
             "prompt": "Comic book panel, Tang dynasty palace with pagodas in misty mountains, lone figure in imperial robes, ink wash and bold lines"},
            {"layout": "full", "speaker": "Мудрец Ли Бо",
             "dialogue": "Император! Путь в тысячу ли начинается с первого шага. Твоя армия ждёт.",
             "prompt": "Comic panel, elderly chinese sage with long white beard holding scroll, cherry blossoms falling, temple garden background"},
            {"layout": "full", "speaker": "Narrator",
             "dialogue": "От бамбукового частокола — до Великой стены. От ополчения — до армии дракона. Небеса наблюдают.",
             "prompt": "Comic book splash, ancient Chinese army in formation, dragon banners, dramatic, traditional ink meets modern comic art"},
        ],
    },
}


def get_story(kingdom: str, trigger: str = "kingdom_select") -> ComicStory:
    tpl = STORY_TEMPLATES.get(kingdom, STORY_TEMPLATES["rus"])
    panels_data = tpl.get(trigger, tpl.get("kingdom_select", []))
    story = ComicStory(kingdom=kingdom, title=tpl["title"])
    for i, p in enumerate(panels_data):
        story.panels.append(ComicPanel(
            index=i, trigger=trigger, layout=p["layout"],
            caption=p.get("caption", ""), speaker=p["speaker"],
            dialogue=p["dialogue"], image_prompt=p["prompt"],
        ))
    return story


def generate_story_ai(kingdom: str, trigger: str, player_state: dict) -> Optional[ComicStory]:
    if not DASHSCOPE_API_KEY:
        return None
    era_names = ["Раннее средневековье", "Высокое средневековье", "Позднее средневековье", "Ренессанс"]
    era = era_names[min(player_state.get("era", 0), 3)]

    prompt = f"""You are a comic book writer for Kingdom Match game. Create 2-3 comic panels.

Kingdom: {kingdom}
Event: {trigger}
Era: {era}
Player level: {player_state.get('level', 1)}

For each panel provide:
- layout: "full" or "split_left" or "top_banner"
- caption: narrator text (1 sentence, optional)
- speaker: character name or "Narrator"
- dialogue: speech bubble text (1-2 sentences, in Russian)
- image_prompt: AI illustration description in English (comic style, bold lines)

Output ONLY JSON array:
[{{"layout":"full","caption":"...","speaker":"...","dialogue":"...","image_prompt":"..."}}]

Tone: epic, energetic, cinematic. Characters speak short and punchy."""

    try:
        url = AI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": DASHSCOPE_MODEL, "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9, "max_tokens": 800}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:-1])
        data = json.loads(content)
        story = ComicStory(kingdom=kingdom, title=f"Хроники {kingdom}")
        for i, p in enumerate(data):
            story.panels.append(ComicPanel(
                index=i, trigger=trigger, layout=p.get("layout", "full"),
                caption=p.get("caption", ""), speaker=p.get("speaker", "Narrator"),
                dialogue=p.get("dialogue", "..."), image_prompt=p.get("image_prompt", "comic panel, fantasy medieval"),
            ))
        return story
    except Exception as e:
        print(f"[Comic] AI failed: {e}")
        return None


def get_or_generate_story(kingdom: str, trigger: str = "kingdom_select",
                          player_state: dict = None) -> ComicStory:
    player_state = player_state or {}
    # Вступительные истории (kingdom_select) — всегда статика: их промпты совпадают
    # с предгенерированными PNG и могут быть закешированы. AI-генерация — только для
    # динамических триггеров (бой, событие и т.п.).
    if trigger != "kingdom_select" and DASHSCOPE_API_KEY:
        ai = generate_story_ai(kingdom, trigger, player_state)
        if ai and ai.panels:
            return ai
    return get_story(kingdom, trigger)


def panel_to_dict(p: ComicPanel) -> dict:
    return {"index": p.index, "trigger": p.trigger, "layout": p.layout,
            "caption": p.caption, "speaker": p.speaker, "dialogue": p.dialogue,
            "image_prompt": p.image_prompt, "image_url": p.image_url}


def story_to_dict(s: ComicStory) -> dict:
    return {"kingdom": s.kingdom, "title": s.title, "panels": [panel_to_dict(p) for p in s.panels]}


# --- Генерация картинок панелей через Replicate ----------------------

def generate_panel_image_path(prompt: str, allow_remote: bool = True) -> Optional[str]:
    """Сгенерировать или вернуть из кеша PNG для одной панели.
    При allow_remote=False — НЕ зовём Replicate, только проверяем кеш на диске.
    Возвращает абсолютный путь к файлу или None если нет."""
    if not prompt:
        return None
    try:
        from replicate_visuals import generate_if_missing, MODEL_FAST, _hash_prompt, _cached_path
        full = prompt + ", comic book art, bold inked lines, dynamic composition, dramatic lighting"
        if not allow_remote:
            # Только проверяем кеш — никаких внешних запросов
            cached = _cached_path(_hash_prompt(full, MODEL_FAST), "comic")
            return cached if os.path.exists(cached) else None
        return generate_if_missing(full, MODEL_FAST, 768, 512, "comic")
    except Exception as e:
        print(f"[Comic] image generation failed: {e}")
        return None


def populate_panel_images(story: ComicStory, url_base: str, allow_remote: bool = True) -> ComicStory:
    """Для каждой панели, у которой пустой image_url, проставить URL.
    allow_remote=False → берём только закешированные картинки, не дёргаем Replicate."""
    if not url_base.endswith("/"):
        url_base += "/"
    for p in story.panels:
        if p.image_url:
            continue
        path = generate_panel_image_path(p.image_prompt, allow_remote=allow_remote)
        if not path:
            continue
        p.image_url = url_base + os.path.basename(path)
    return story
