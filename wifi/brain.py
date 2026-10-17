"""brain.py - 拿到识别出的文字，给出回复（以及可选的动作）

现在是本地规则版：不联网、不要 key，Demo 够用。
以后要接大模型，只要把 reply_for() 换成一次 API 调用即可，其它代码不用动。
"""

import random
import time


def reply_for(text, player=None):
    """返回 (回复文字, 动作)。动作可以是 None / play / pause / louder / quieter。"""
    t = (text or "").replace(" ", "").replace("，", "").replace("。", "")
    if not t:
        return None, None

    if any(w in t for w in ("你好", "哈喽", "在吗", "喂")):
        return random.choice(["你好，我在。", "你好呀，我在听。", "嗨，我在。"]), None

    if any(w in t for w in ("几点", "时间", "什么时候")):
        return "现在是 %s。" % time.strftime("%H点%M分"), None

    if any(w in t for w in ("你叫什么", "名字", "你是谁")):
        return "我叫噜噜，是这个音箱里的小助手。", None

    if any(w in t for w in ("放歌", "来一首", "音乐", "唱歌")):
        return "好，给你放一首。", "play"

    if any(w in t for w in ("暂停", "停一下", "别放了")):
        return "好，停了。", "pause"

    if any(w in t for w in ("大声", "音量高")):
        return "好，大一点。", "louder"

    if any(w in t for w in ("小声", "音量低", "太吵")):
        return "好，小一点。", "quieter"

    if any(w in t for w in ("再见", "拜拜")):
        return "再见，需要我就叫我。", None

    # 兜底：把听到的复述一遍，证明整条链路是通的
    return "我听到你说：%s。" % t, None
