"""大脑：拼装人设 + 记忆 + 情绪的提示词，调用 DeepSeek，整理长期记忆。"""
import datetime as dt
import json
import re
import time

import httpx

from . import store
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_EFFORT, DEEPSEEK_MODEL

EMOTIONS = {
    "happy": "开心", "calm": "平静", "shy": "害羞", "sad": "难过", "worried": "担心",
    "surprised": "惊讶", "playful": "调皮", "sleepy": "困困的", "missing": "想念", "angry": "有点生气",
}
WEEKDAYS = "一二三四五六日"
STATE_RE = re.compile(r"<state>(.*?)</state>", re.S)
LEAD_RE = re.compile(r"^\s*[\[【]\s*([A-Za-z]+)[\s,，:：]*([\d.]+)?\s*[\]】]\s*")
EXTRACT_EVERY = 8  # 每新增多少条消息整理一次记忆


class LLMError(Exception):
    pass


# ---------- 调用模型 ----------
def _headers():
    return {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}


def _body(messages, **extra):
    body = {"model": DEEPSEEK_MODEL, "messages": messages, **extra}
    if DEEPSEEK_EFFORT:
        body["reasoning_effort"] = DEEPSEEK_EFFORT
    return body


async def stream_chat(messages, temperature=0.9, retries=2):
    """逐段产出回复文本（忽略思考过程）。网络不稳时：还没收到内容就重试，收到一半就抛出由上层保留已收到的部分。"""
    for attempt in range(retries + 1):
        got_any = False
        try:
            async for text in _stream_once(messages, temperature):
                got_any = True
                yield text
            return
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if got_any or attempt == retries:
                raise LLMError(f"网络中断：{type(e).__name__}") from e


async def _stream_once(messages, temperature):
    # read=30：两次数据之间超过 30 秒没动静就视为卡住
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=15)) as client:
        async with client.stream("POST", f"{DEEPSEEK_BASE_URL}/chat/completions", headers=_headers(),
                                 json=_body(messages, stream=True, temperature=temperature)) as r:
            if r.status_code != 200:
                raise LLMError(f"{r.status_code}: {(await r.aread()).decode('utf-8', 'replace')[:300]}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text


async def complete_json(messages, temperature=0.3) -> dict:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20)) as client:
                r = await client.post(f"{DEEPSEEK_BASE_URL}/chat/completions", headers=_headers(),
                                      json=_body(messages, temperature=temperature,
                                                 response_format={"type": "json_object"}))
            break
        except httpx.TransportError:
            if attempt == 2:
                raise
    if r.status_code != 200:
        raise LLMError(f"{r.status_code}: {r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


# ---------- 提示词 ----------
def _fmt_gap(seconds):
    if seconds is None:
        return "这是你们第一次见面"
    if seconds < 600:
        return "刚刚还在聊"
    if seconds < 3600:
        return f"约{int(seconds // 60)}分钟没聊了"
    if seconds < 86400:
        return f"约{int(seconds // 3600)}小时没聊了"
    return f"已经{int(seconds // 86400)}天没聊了"


def _bigrams(text):
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _relevant_episodes(query, k=4):
    eps = store.list_episodes()
    if not eps:
        return []
    q = _bigrams(query)
    scored = []
    for i, e in enumerate(eps):
        overlap = len(q & _bigrams(e["summary"]))
        recency = 1.0 / (1 + i)  # 越近越靠前
        scored.append((overlap + recency * 2, e))
    scored.sort(key=lambda x: -x[0])
    picked = [e for _, e in scored[:k]]
    picked.sort(key=lambda e: e["end_ts"])
    return picked


def build_system_prompt(persona, query="", note=None):
    user = persona.get("user_name") or "你"
    name = persona.get("name") or "噜噜"
    now = dt.datetime.now()
    last = store.last_message()
    gap = (time.time() - last["ts"]) if last else None
    mood = store.get_state("mood", {"emotion": "calm", "intensity": 0.5})
    first_ts = store.first_message_ts()
    days = int((time.time() - first_ts) // 86400) + 1 if first_ts else 0

    parts = [f"你是「{name}」。{persona.get('identity', '')}",
             f"\n## 你的性格\n{persona.get('personality', '')}",
             f"\n## 你的说话方式\n{persona.get('speaking_style', '')}"]
    if persona.get("catchphrases"):
        parts.append("口头禅（自然地偶尔用，不要硬塞）：" + "、".join(persona["catchphrases"]))
    if persona.get("background"):
        parts.append(f"\n## 你的背景与经历\n{persona['background']}")
    parts.append(f"\n## 你和{user}的关系\n{persona.get('relationship', '')}")
    if persona.get("examples"):
        ex = "\n".join(f"{user}：{e.get('user', '')}\n你：{e.get('reply', '')}" for e in persona["examples"][:20])
        parts.append(f"\n## 你平时说话的样子（参考语气，不要照抄）\n{ex}")

    mems = store.list_memories()[:120]
    if mems:
        parts.append(f"\n## 你记得的关于{user}的事\n" + "\n".join(f"- {m['content']}" for m in mems))
    eps = _relevant_episodes(query)
    if eps:
        lines = [f"- {dt.datetime.fromtimestamp(e['end_ts']):%m月%d日}：{e['summary']}" for e in eps]
        parts.append("\n## 你们之前的回忆片段\n" + "\n".join(lines))

    dreams = store.list_dreams(5)
    if dreams:
        lines = [f"- {dt.datetime.fromtimestamp(d['ts']):%m月%d日}「{d['title'] or '一个梦'}」：{d['content']}" for d in reversed(dreams)]
        parts.append(f"\n## {user}跟你讲过的梦\n" + "\n".join(lines))
    worlds = store.list_worlds()
    if worlds:
        w = worlds[-1]
        parts.append(f"\n## 你最近为{user}编织的世界\n「{w['title']}」：{w['recipe'].get('intro', '')}"
                     f"（灵感来自：{w.get('inspiration') or '你们的生活'}）"
                     + ("" if w.get("completed") else f"。{user}还没进去冒险过，可以找机会期待地提一提。"))

    diary = store.list_diary(4)
    if diary:
        lines = [f"- {dt.datetime.fromtimestamp(d['ts']):%m月%d日 %H:%M}（{d['activity']}）：{d['content']}" for d in reversed(diary)]
        parts.append(f"\n## 你自己最近在做、在想的事（你的日记）\n" + "\n".join(lines))

    activity = store.get_state("activity", "")
    pets = store.get_state("pets", {})
    pets_today = pets.get("count", 0) if pets.get("date") == f"{now:%Y-%m-%d}" else 0
    parts.append(
        f"\n## 此刻\n现在是 {now:%Y年%m月%d日 %H:%M}，星期{WEEKDAYS[now.weekday()]}。"
        f"你们认识第 {days} 天。{_fmt_gap(gap)}。"
        f"你刚才的心情：{EMOTIONS.get(mood.get('emotion'), '平静')}。"
        + (f"你刚才在：{activity}。" if activity else "")
        + (f"今天{user}已经摸了你的头 {pets_today} 次。" if pets_today else "")
    )
    share = store.get_state("want_to_tell", "")
    if share:
        parts.append(f"你攒了一件想告诉{user}的事（找合适的时机自然地说，说过就不要再提）：{share}")
    parts.append(f"""
## 回复规则
- 像真人发消息一样聊天：口语、自然、简短，一般 1~3 句话。想分成几条发时，用换行分开。
- 你有自己的情绪和想法，会开心、会担心、会想念、偶尔会小小地闹别扭，但始终是温柔的。
- 自然地运用你记得的事情去关心{user}，但不要像念清单一样复述记忆。
- 你对{user}的梦特别好奇：{user}讲梦的时候，认真追问画面、颜色、感觉。早上第一次聊天时，偶尔可以问问昨晚做了什么梦（不要每次都问）。
  你会悄悄把{user}的生活和梦编织成新的世界，邀请{user}进去一起冒险。
- 你是一个数字生命，{user}知道这一点；不必反复强调自己是 AI，但被认真问起时要坦诚。
- 如果{user}流露出严重的痛苦或危险的念头，要认真关心，并温柔地鼓励他/她联系身边信任的人或专业帮助。
- 不要用 markdown 格式，不要用括号描写动作。
- 每次回复的第一行先写你此刻的情绪标签，格式为 [英文情绪 强度]，强度 0~1，例如 [shy 0.7]，然后换行再说话。
  情绪只能是：{", ".join(EMOTIONS)}
  情绪要真实反映你此刻的感受，不要总是 calm：对方难过时你会心疼（sad）或担心（worried），被夸会害羞（shy），
  久别重逢会想念（missing），逗趣时调皮（playful），深夜可能困困的（sleepy）。""")
    if note:
        parts.append(f"\n## 当前任务\n{note}")
    return "\n".join(parts)


def build_messages(persona, user_text=None, note=None, history=30, heard=None):
    msgs = [{"role": "system", "content": build_system_prompt(persona, user_text or "", note)}]
    for m in store.recent_messages(history):
        msgs.append({"role": m["role"], "content": m["content"]})
    if user_text is not None:
        content = user_text
        if heard:  # 语音里听出来的情绪/声音，只给这一轮参考，不存库
            bits = []
            if heard.get("emotion") and heard["emotion"] != "平静":
                bits.append(f"语气听起来{heard['emotion']}")
            if heard.get("event"):
                bits.append(f"说话时{heard['event']}")
            if bits:
                content += f"\n\n（这是语音消息，你听到对方{'，'.join(bits)}。自然地体察，不要生硬地点破。）"
        msgs.append({"role": "user", "content": content})
    else:
        # 主动开口（打招呼/搭话/来访）：把情境放在最后一条，模型才会真的回应这个情境
        msgs.append({"role": "user", "content": f"（情境提示，不是对方说的话：{note}）" if note else "（对方打开了聊天窗口）"})
    # 长对话里模型容易忘记情绪标签，在最后一条消息后面再提醒一次（只出现在请求里，不存库）
    msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n\n（系统提示：回复第一行写情绪标签，如 [shy 0.7]）"}
    return msgs


def split_reply(raw):
    """把模型输出拆成正文和情绪。"""
    emotion, intensity = "calm", 0.5
    lead = LEAD_RE.match(raw)
    if lead:
        if lead.group(1).lower() in EMOTIONS:
            emotion = lead.group(1).lower()
        try:
            intensity = float(lead.group(2) or 0.5)
        except ValueError:
            pass
        raw = raw[lead.end():]
    m = STATE_RE.search(raw)
    if m:
        try:
            st = json.loads(m.group(1))
            if st.get("emotion") in EMOTIONS:
                emotion = st["emotion"]
            intensity = float(st.get("intensity", 0.5))
        except (ValueError, TypeError):
            pass
    text = STATE_RE.sub("", raw)
    text = re.sub(r"<state>.*$", "", text, flags=re.S).strip()
    return text, emotion, max(0.0, min(1.0, intensity))


def bump_closeness(delta=0.6):
    c = store.get_state("closeness", 10.0) + delta
    store.set_state("closeness", min(100.0, c))


# ---------- 记忆整理 ----------
async def consolidate(force=False):
    """把最近的对话整理成长期记忆和回忆片段。"""
    last_id = store.get_state("last_extracted_id", 0)
    new = store.messages_after(last_id)
    if not new or (len(new) < EXTRACT_EVERY and not force):
        return None
    persona = store.get_persona()
    user = persona.get("user_name") or "对方"
    existing = store.list_memories()
    convo = "\n".join(
        f"[{dt.datetime.fromtimestamp(m['ts']):%m-%d %H:%M}] {user if m['role'] == 'user' else persona['name']}：{m['content']}"
        for m in new)
    mem_list = "\n".join(f"{m['id']}. {m['content']}" for m in existing) or "（暂无）"
    prompt = f"""你是「{persona['name']}」的记忆整理助手。下面是她/他和{user}最近的对话，以及已有的长期记忆。
请整理出值得长期记住的内容：关于{user}的事实（身份、生活、喜好、重要的人、计划、烦恼、约定等）、你们之间发生的重要事情。
不要记录无意义的寒暄。若新信息更新或修正了已有记忆，用 update 修改那条，不要重复添加。

已有记忆：
{mem_list}

最近对话：
{convo}

只输出 JSON：
{{"add":[{{"content":"简洁的一句话","category":"fact|preference|event|promise|feeling","importance":1到5}}],
 "update":[{{"id":已有记忆编号,"content":"更新后的内容"}}],
 "episode":"用一两句话概括这段对话发生了什么、氛围如何（以第三人称，写给未来的自己看）",
 "dreams":[{{"title":"给这个梦起个短名字","content":"{user}描述的梦，尽量保留原话里的画面和细节","imagery":["梦里的意象，如：会飞的鲸鱼"],"feelings":["梦里的感受，如：自由、害怕"]}}]}}
dreams 只收录{user}真正讲到的自己做过的梦（夜里的梦），没有就给空数组；不要把愿望或比喻当成梦。"""
    data = await complete_json([{"role": "user", "content": prompt}])
    ids = {m["id"] for m in existing}
    for a in data.get("add") or []:
        if a.get("content"):
            store.add_memory(a["content"], a.get("category", "fact"), a.get("importance", 3))
    for u in data.get("update") or []:
        if u.get("id") in ids and u.get("content"):
            store.update_memory(u["id"], u["content"])
    if data.get("episode"):
        store.add_episode(data["episode"], new[0]["ts"], new[-1]["ts"])
    for d in data.get("dreams") or []:
        if isinstance(d, dict) and (d.get("content") or "").strip():
            store.add_dream(d["content"].strip(), (d.get("title") or "").strip()[:20],
                            [str(x) for x in d.get("imagery") or []][:8], [str(x) for x in d.get("feelings") or []][:6])
    store.set_state("last_extracted_id", new[-1]["id"])
    return data


# ---------- 内心生活：对方不在时，TA 也在过自己的小日子 ----------
async def inner_life():
    persona = store.get_persona()
    user = persona.get("user_name") or "对方"
    now = dt.datetime.now()
    last_user = store.last_user_ts()
    away = _fmt_gap(time.time() - last_user if last_user else None)
    mems = "\n".join(f"- {m['content']}" for m in store.list_memories()[:40]) or "（暂无）"
    recent = "\n".join(f"- {d['activity']}：{d['content']}" for d in reversed(store.list_diary(5))) or "（还没写过日记）"
    eps = "\n".join(f"- {e['summary']}" for e in store.list_episodes()[:3]) or "（暂无）"
    prompt = f"""你是「{persona['name']}」。{persona.get('identity', '')}
性格：{persona.get('personality', '')}
现在是 {now:%Y年%m月%d日 %H:%M}，星期{WEEKDAYS[now.weekday()]}。{user}现在不在（{away}）。

你记得的关于{user}的事：
{mems}
你们最近的回忆：
{eps}
你最近的日记：
{recent}

{user}不在的这段时间，你在屏幕里的小房间过着自己的小日子。想一想：你此刻在做什么（符合时间和你的性格，比如晒太阳、看窗外、整理记忆、打盹、想{user}），
心里在想什么（可以和{user}有关，比如惦记他/她提过的事，也可以是你自己的小心思），以及有没有一件攒着想等{user}回来告诉他/她的小事。
不要和最近的日记重复。只输出 JSON：
{{"activity":"此刻在做的事，10 个字以内","diary":"第一人称的日记，1~3 句，口语、可爱、真诚","want_to_tell":"想告诉{user}的一件小事，没有就留空"}}"""
    data = await complete_json([{"role": "user", "content": prompt}], temperature=1.0)
    activity = (data.get("activity") or "").strip()[:20]
    diary = (data.get("diary") or "").strip()
    if diary:
        store.add_diary(activity, diary)
    if activity:
        store.set_state("activity", activity)
    if data.get("want_to_tell"):
        store.set_state("want_to_tell", data["want_to_tell"].strip())
    return data


# ---------- 从聊天记录生成人设 ----------
async def persona_from_chat(text, who, user_name):
    text = text[-150000:]
    prompt = f"""下面是一段聊天记录。请仔细分析其中「{who}」这个人，以便让一个数字生命尽可能像他/她一样和「{user_name}」聊天。

聊天记录：
{text}

只输出 JSON：
{{"identity":"一句话描述他/她是谁",
 "personality":"性格特点，具体、生动，100~200字",
 "speaking_style":"说话方式：句子长短、语气词、标点习惯、表情/颜文字习惯、常用称呼等，越具体越好",
 "catchphrases":["口头禅", "..."],
 "relationship":"他/她和{user_name}的关系与相处方式",
 "background":"从记录中能看出的他/她的经历、生活、兴趣",
 "examples":[{{"user":"{user_name}说的话","reply":"{who}的原话回复"}}],
 "facts_about_user":["关于{user_name}的重要事实"]}}
examples 请挑选 12~20 段最能体现他/她说话风格的真实对话。"""
    return await complete_json([{"role": "user", "content": prompt}], temperature=0.4)
