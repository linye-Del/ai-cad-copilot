"""自然语言 → 结构化零件参数。优先 DeepSeek 大模型抽取，无 API Key 时回退到规则解析。"""

import json
import re

from openai import OpenAI

from agent import schema

FALLBACK_NAME = "智能解析（规则引擎）"


def _build_system_prompt() -> str:
    metas = schema.all_metas()
    lines = ["你是机械设计参数抽取引擎，根据用户的中文描述抽取零件参数，只输出一个JSON对象，不要输出任何其他内容。"]
    for meta in metas.values():
        fields = ", ".join(
            f"{f['name']}({f['label']},单位{f.get('unit','')})" for f in meta["fields"]
        )
        lines.append(
            f"- {meta['key']} {meta['name']} 标准:{meta['standard']} 可用字段: {fields}"
        )
    lines.append(
        'JSON格式: {"part_type": "零件key", "part_name": "简短中文名", "params": {"字段": 数值/字符串}}'
    )
    lines.append(
        "规则: 1.params只填用户明确提到或可合理推断的字段,未提到的省略 2.所有长度统一换算为mm数值,不带单位 3.分段尺寸用数组,如segments:[{\"d\":25,\"L\":60}] 4.键槽用keyway:{enabled:true,...} 5.part_name用中文简短命名"
    )
    return "\n".join(lines)


def parse_with_llm(text: str, api_key: str, base_url: str, model: str) -> dict:
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=1000,
    )
    data = json.loads(resp.choices[0].message.content)
    return data


def parse_with_rules(text: str) -> dict:
    ptype = None
    for kw, key in [("螺栓", "bolt"), ("螺钉", "bolt"), ("轴", "shaft"), ("法兰", "flange"), ("齿轮", "gear")]:
        if kw in text:
            ptype = key
            break
    if not ptype:
        raise ValueError("无法识别零件类型，请包含：螺栓/轴/法兰/齿轮 等关键词")

    params = {}
    if ptype == "bolt":
        m = re.search(r"[Mm](\d+(?:\.\d+)?)", text)
        if m:
            params["d"] = float(m.group(1))
        m = re.search(r"[Mm]\d+(?:\.\d+)?\s*[×xX*]\s*(\d+(?:\.\d+)?)", text)
        params["L"] = float(m.group(1)) if m else params.get("d", 10) * 4
        m = re.search(r"螺纹长(?:度)?[\s:：]?(\d+(?:\.\d+)?)", text)
        if m:
            params["b"] = float(m.group(1))
        m = re.search(r"螺距[\s:：]?(\d+(?:\.\d+)?)", text)
        if m:
            params["pitch"] = float(m.group(1))
    elif ptype == "shaft":
        segs = re.findall(r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)", text)
        params["segments"] = [{"d": float(a), "L": float(b)} for a, b in segs]
        if not params["segments"]:
            raise ValueError("未找到轴段尺寸，请用 直径×长度 描述，如 25×60、30×40")
    elif ptype == "flange":
        pairs = {"外径": "D", "内径": "d"}
        for kw, key in pairs.items():
            m = re.search(kw + r"[\s:：]?(\d+(?:\.\d+)?)", text)
            if m:
                params[key] = float(m.group(1))
        m = re.search(r"(?:厚度|厚)[\s:：]?(\d+(?:\.\d+)?)", text)
        if m:
            params["t"] = float(m.group(1))
        m = re.search(r"(\d+)\s*(?:个|只)?\s*(?:M\d+)?\s*螺栓孔", text)
        if m:
            params["n"] = int(m.group(1))
        m = re.search(r"分度圆(?:直径)?[\s:：]?(\d+(?:\.\d+)?)", text)
        if m:
            params["pcd"] = float(m.group(1))
        m = re.search(r"[Mm](\d+(?:\.\d+)?)\s*螺栓孔", text)
        if m:
            params["hole_d"] = float(m.group(1)) + 1.0
    elif ptype == "gear":
        for kw, key in [("模数", "m"), ("齿数", "z"), ("齿宽", "b"), ("孔径", "d_hub")]:
            m = re.search(kw + r"[\s:：]?(\d+(?:\.\d+)?)", text)
            if m:
                params[key] = float(m.group(1))
    return {"part_type": ptype, "params": params}


def parse(text: str, api_key: str = "", base_url: str = "", model: str = "") -> dict:
    source = FALLBACK_NAME
    try:
        if api_key:
            data = parse_with_llm(text, api_key, base_url, model)
            source = "DeepSeek 大模型"
            if data.get("part_type") not in schema.PART_KEYS:
                raise ValueError(f"大模型返回未知零件类型: {data.get('part_type')}")
        else:
            data = parse_with_rules(text)
    except Exception:
        data = parse_with_rules(text)

    ptype = data["part_type"]
    params = data.get("params") or {}
    params = schema.derive_params(ptype, params)
    name = data.get("part_name") or schema.part_name_for(ptype, params)
    return {"part_type": ptype, "part_name": name, "params": params, "source": source}