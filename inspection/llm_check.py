"""LLM 图纸审查：结合决策系统输出与零件参数，由大模型给出带标准依据的工程审查意见。"""

import json

from openai import OpenAI

from agent import schema


def llm_review(part_type: str, params: dict, rule_issues: list, api_key: str, base_url: str, model: str) -> dict:
    meta = schema.get_meta(part_type)
    rules_txt = "\n".join(
        f"- [{i.get('level')}/{i.get('risk_cn', i.get('risk'))}] {i.get('item')}：{i.get('detail')}"
        f"（建议：{i.get('suggestion')}；依据：{i.get('standard', '')}）"
        for i in rule_issues
    ) or "（无）"
    prompt = f"""你是资深机械设计工程师，请审查以下零件设计，输出JSON数组，每个元素:{{"level":"error|warning|info","item":"问题项","detail":"问题描述","suggestion":"修改建议","standard":"依据标准编号(如GB/T 5782-2016)"}}。只输出JSON数组。

零件类型: {meta['name']} ({meta['standard']})
设计参数: {json.dumps(params, ensure_ascii=False)}

规则引擎已识别的问题（不要复述，请在其基础上深入）:
{rules_txt}

审查要点（每项都要给出工程解释与标准依据）:
1. 尺寸链合理性、国家标准符合性（引用 GB/T / ISO 具体条文号）
2. 材料与热处理选择的合理性（许用应力、硬度范围）
3. 加工工艺性（倒角、退刀槽、定位基准、深孔/薄壁加工难度）
4. 强度/刚度隐患（扭转/弯曲校核、应力集中系数、薄壁、悬臂）
5. 装配与配合合理性（配合公差 H7/k6 等、轴承定位轴肩、间隙）
6. 遗漏的必要设计要素（公差、粗糙度、中心孔、表面处理）
7. 对规则引擎已列问题的工程解释与量化校核（如 τ=16T/(πd³) 计算）

输出要求：detail 必须包含力学/工艺机理分析，standard 必须给出具体标准编号。"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是资深机械设计审查专家，输出严格JSON，每个问题必须带标准编号依据。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2000,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("issues") or data.get("results") or []
        if isinstance(data, list):
            return {"issues": data, "raw": content}
        return {"issues": [], "raw": content}
    except Exception as e:
        return {"issues": [], "error": str(e), "raw": ""}
