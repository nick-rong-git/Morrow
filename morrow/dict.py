"""
Morrow 即时查词引擎 (Instant Dictionary Engine)
支持在终端任意学习屏一键按 [/] 查词，集成有道翻译与权威英英释义。
"""

import json
import urllib.request
import urllib.parse
from typing import Dict, Any

_DICT_CACHE: Dict[str, Dict[str, Any]] = {}

def lookup_dictionary(word: str) -> Dict[str, Any]:
    w = word.strip().lower()
    if not w:
        return {}
    if w in _DICT_CACHE:
        return _DICT_CACHE[w]

    query = urllib.parse.quote(w, safe="")
    result: Dict[str, Any] = {
        "word": w,
        "phonetic": "",
        "explains": [],
        "web_trans": [],
        "definitions": [],
        "audio_url": f"https://dict.youdao.com/dictvoice?audio={query}&type=2"
    }

    # 1. 有道词典接口
    try:
        url = f"https://dict.youdao.com/suggest?num=5&doctype=json&q={query}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            entries = data.get("data", {}).get("entries", [])
            for entry in entries:
                exp = entry.get("explain")
                if entry.get("entry", "").lower() == w and exp:
                    result["explains"].append(exp)
                    break
    except Exception:
        pass

    # 2. 备用有道翻译
    if not result["explains"]:
        try:
            url = f"https://fanyi.youdao.com/translate?doctype=json&type=AUTO&i={query}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tgt_parts = []
                for para in data.get("translateResult", []):
                    for sent in para:
                        tgt = sent.get("tgt", "").strip()
                        if tgt:
                            tgt_parts.append(tgt)
                if tgt_parts:
                    result["explains"].append("; ".join(tgt_parts))
        except Exception:
            pass

    # 3. 权威英英词典 (dictionaryapi.dev)
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and data:
                entry = data[0]
                result["phonetic"] = entry.get("phonetic") or next(
                    (p["text"] for p in entry.get("phonetics", []) if p.get("text")), ""
                )
                meanings = entry.get("meanings", [])
                for m in meanings[:2]:
                    part = m.get("partOfSpeech", "")
                    for d in m.get("definitions", [])[:2]:
                        definition_text = d.get("definition", "")
                        if definition_text:
                            result["definitions"].append(f"({part}) {definition_text}")
    except Exception:
        pass

    if result["explains"] or result["definitions"]:
        _DICT_CACHE[w] = result
    return result
