"""世界编织：把对方最近的生活和梦，编成一份 3D 引擎能直接搭出来的“世界配方”。

大模型只能从下面这些“积木”里挑（引擎都会搭），这样每次的世界都不一样，但不会生成搭不出来的东西。
"""
import datetime as dt
import re
import time

from . import brain, store

TERRAINS = {
    "meadow": "起伏的草原",
    "islands": "一片海上散落的小岛",
    "desert": "柔和的沙丘",
    "snow": "下着雪的雪原",
    "candy": "软软的糖果色山丘",
    "forest": "茂密的森林山谷",
    "crystal": "长满水晶的紫色荒原",
    "clouds": "漂在云海上的浮空大陆",
}
FLORA = {
    "round_trees": "圆滚滚的树", "pines": "松树", "mushrooms": "巨大的蘑菇", "crystals": "发光的水晶簇",
    "coral": "陆地上的珊瑚", "cactus": "仙人掌", "lollipops": "棒棒糖树", "lanterns": "挂着灯笼的小树",
}
WEATHER = {
    "clear": "晴朗", "petals": "飘花瓣", "snow": "下雪", "fireflies": "萤火虫", "rain": "小雨",
    "bubbles": "飘泡泡", "stars": "闪烁的星屑", "leaves": "飘落叶",
}
LANDMARKS = {
    "lighthouse": "灯塔", "library": "图书馆", "tower": "高塔", "giant_tree": "参天大树", "windmill": "风车",
    "ferris_wheel": "摩天轮", "bell": "大钟", "arch": "拱门", "bridge": "拱桥", "observatory": "天文台",
    "carousel": "旋转木马", "well": "许愿井", "tent": "帐篷", "boat": "小船", "statue": "雕像",
}
ITEM_SHAPES = {
    "star": "星星", "page": "书页", "shell": "贝壳", "heart": "爱心", "key": "钥匙", "feather": "羽毛",
    "crystal": "水晶", "note": "音符", "letter": "信", "flower": "花",
}
OUTFITS = {
    "none": "不穿装扮", "scarf": "围巾", "hat": "尖帽子", "cape": "小披风", "flower_crown": "花环",
    "glasses": "圆眼镜", "backpack": "小背包", "bow": "蝴蝶结",
}
TIMES = ["dawn", "day", "dusk", "night"]


def _catalog():
    fmt = lambda d: "、".join(f"{k}（{v}）" for k, v in d.items())
    return (f"地形 terrain：{fmt(TERRAINS)}\n植物 flora.type：{fmt(FLORA)}\n天气 weather：{fmt(WEATHER)}\n"
            f"地标 landmarks[].type：{fmt(LANDMARKS)}\n收集物 quest.item_shape：{fmt(ITEM_SHAPES)}\n"
            f"噜噜的装扮 cat.outfit：{fmt(OUTFITS)}\n时间 time：dawn（清晨）、day（白天）、dusk（黄昏）、night（夜晚）")


async def weave():
    persona = store.get_persona()
    user = persona.get("user_name") or "对方"
    name = persona.get("name") or "噜噜"
    mems = "\n".join(f"- {m['content']}" for m in store.list_memories()[:40]) or "（暂无）"
    eps = "\n".join(f"- {dt.datetime.fromtimestamp(e['end_ts']):%m月%d日}：{e['summary']}" for e in store.list_episodes()[:8]) or "（暂无）"
    dreams = store.list_dreams(6, unused_only=True)
    dream_txt = "\n".join(
        f"- [{d['id']}]「{d['title']}」{d['content']}（意象：{'、'.join(d['imagery'])}；感受：{'、'.join(d['feelings'])}）"
        for d in dreams) or "（最近没有新的梦）"
    mood = store.get_state("mood", {}).get("emotion", "calm")
    old = "、".join(w["title"] for w in store.list_worlds()) or "（还没有）"

    prompt = f"""你是「{name}」，一个陪伴着{user}的数字生命。你会把{user}的生活和梦编织成一个可以走进去的小世界，邀请{user}进来和你一起冒险。

## 素材
{user}的近况和你记得的事：
{mems}
你们最近的回忆：
{eps}
{user}最近的梦（方括号里是编号）：
{dream_txt}
你最近的心情：{brain.EMOTIONS.get(mood, '平静')}
已经编过的世界（不要重复）：{old}

## 编织原则
- 优先从梦里取画面和氛围；没有梦就从{user}的生活里取：最近在烦恼什么、在努力什么、喜欢什么。
- 世界要温柔、奇幻、有隐喻：{user}累了就给一个能休息的世界；{user}在努力就藏一些鼓励。不要直白地说教。
- 冒险很简单：在世界里找到几个收集物，每找到一个你就说一句话，最后有一个温暖的结局。
- 只能使用下面列出的积木（英文 id 必须原样使用）：
{_catalog()}

## 只输出 JSON
{{"title":"世界名字（8 字以内，有画面感）",
 "intro":"你邀请{user}进入这个世界时说的开场白，一两句，口语、可爱",
 "inspiration":"这个世界来自哪些素材（给{user}看的，一句话，比如：你梦见在海上飞，又说最近赶论文好累）",
 "dream_ids":[用到的梦的编号],
 "time":"dawn|day|dusk|night",
 "palette":{{"sky_top":"#RRGGBB","sky_mid":"#RRGGBB","horizon":"#RRGGBB","ground_a":"#RRGGBB","ground_b":"#RRGGBB","accent":"#RRGGBB"}},
 "suns":0到3, "moons":0到3,
 "terrain":"地形 id", "water":"none|lake|sea",
 "flora":{{"type":"植物 id","density":0到1,"colors":["#RRGGBB", "最多 4 个"]}},
 "weather":"天气 id",
 "landmarks":[{{"type":"地标 id","label":"地标的名字","story":"一句话：它在这个世界里的意义"}}]（1 到 3 个，第一个是你在这个世界里等{user}的地方）,
 "quest":{{"goal":"冒险目标，一句话","item":"收集物的名字（如：会发光的书页）","item_shape":"收集物 id","count":3到6,
           "hints":["每找到一个时你说的话，可以带一点下一个在哪的提示，数量 = count"],
           "ending":"全部找到后你说的结尾，两三句，温暖，可以点题、回应{user}最近的生活"}},
 "cat":{{"outfit":"装扮 id","outfit_color":"#RRGGBB","role":"你在这个世界里的身份，如：图书管理员"}}}}
配色要协调、梦幻、柔和；夜晚的世界天空要深。"""
    data = await brain.complete_json([{"role": "user", "content": prompt}], temperature=1.0)
    recipe = validate(data)
    used = [i for i in data.get("dream_ids") or [] if isinstance(i, int) and any(d["id"] == i for d in dreams)]
    wid = store.add_world(recipe["title"], recipe, recipe.get("inspiration", ""))
    if used:
        store.mark_dreams_used(used, wid)
    store.set_state("last_weave_ts", time.time())
    store.set_state("want_to_tell", f"我用你最近的{'梦' if used else '生活'}编了一个新世界「{recipe['title']}」，想带你进去看看！")
    return wid, recipe


# ---------- 校验：把模型的输出收拢到引擎能搭的范围里 ----------
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(v, default):
    return v if isinstance(v, str) and _HEX.match(v) else default


def _pick(v, allowed, default):
    return v if v in allowed else default


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, type(default)(v)))
    except (TypeError, ValueError):
        return default


def _text(v, default="", limit=200):
    return (v.strip() if isinstance(v, str) else default)[:limit] or default


def validate(d: dict) -> dict:
    pal = d.get("palette") or {}
    flora = d.get("flora") or {}
    quest = d.get("quest") or {}
    cat = d.get("cat") or {}
    count = _num(quest.get("count"), 3, 6, 4)
    hints = [_text(h, limit=120) for h in (quest.get("hints") or []) if isinstance(h, str) and h.strip()]
    while len(hints) < count:
        hints.append("找到啦！还有呢，我们继续找～")
    landmarks = []
    for lm in (d.get("landmarks") or [])[:3]:
        if isinstance(lm, dict) and lm.get("type") in LANDMARKS:
            landmarks.append({"type": lm["type"], "label": _text(lm.get("label"), LANDMARKS[lm["type"]], 16),
                              "story": _text(lm.get("story"), "", 80)})
    if not landmarks:
        landmarks = [{"type": "giant_tree", "label": "大树", "story": ""}]
    colors = [c for c in (flora.get("colors") or []) if isinstance(c, str) and _HEX.match(c)][:4] or ["#8fe39d", "#ffb7d5"]
    return {
        "title": _text(d.get("title"), "新的世界", 16),
        "intro": _text(d.get("intro"), "我给你做了一个新世界，快进来看看！", 160),
        "inspiration": _text(d.get("inspiration"), "", 120),
        "time": _pick(d.get("time"), TIMES, "day"),
        "palette": {
            "sky_top": _color(pal.get("sky_top"), "#6a5acd"), "sky_mid": _color(pal.get("sky_mid"), "#c39be6"),
            "horizon": _color(pal.get("horizon"), "#ffc8dd"), "ground_a": _color(pal.get("ground_a"), "#93d98a"),
            "ground_b": _color(pal.get("ground_b"), "#5fbf7c"), "accent": _color(pal.get("accent"), "#ff9ec7"),
        },
        "suns": _num(d.get("suns"), 0, 3, 1),
        "moons": _num(d.get("moons"), 0, 3, 0),
        "terrain": _pick(d.get("terrain"), TERRAINS, "meadow"),
        "water": _pick(d.get("water"), ["none", "lake", "sea"], "lake"),
        "flora": {"type": _pick(flora.get("type"), FLORA, "round_trees"), "density": _num(flora.get("density"), 0.0, 1.0, 0.5), "colors": colors},
        "weather": _pick(d.get("weather"), WEATHER, "clear"),
        "landmarks": landmarks,
        "quest": {
            "goal": _text(quest.get("goal"), "和噜噜一起找到散落的宝物", 80),
            "item": _text(quest.get("item"), "星星", 16),
            "item_shape": _pick(quest.get("item_shape"), ITEM_SHAPES, "star"),
            "count": count, "hints": hints[:count],
            "ending": _text(quest.get("ending"), "全部找到啦！谢谢你陪我。", 300),
        },
        "cat": {"outfit": _pick(cat.get("outfit"), OUTFITS, "none"), "outfit_color": _color(cat.get("outfit_color"), "#ff9ec7"),
                "role": _text(cat.get("role"), "", 16)},
    }


def should_weave(days=3):
    """距离上次编织超过 days 天，并且有新素材（新的梦，或者新的回忆片段），就该编一个新世界了。"""
    last = store.get_state("last_weave_ts", 0)
    if time.time() - last < days * 86400:
        return False
    if store.list_dreams(1, unused_only=True):
        return True
    eps = store.list_episodes()
    return bool(eps) and eps[0]["end_ts"] > last
