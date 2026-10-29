"""STEP 审查兼容包装（v1 接口）。

v2 架构：inspection/step_parser + feature_detector + manufacturability_checker + step_review。
本模块保留旧 review_step / extract_features 接口，供 backend 与既有调用方兼容。
"""

import logging

from inspection.step_review import review_step  # noqa: F401  主入口（新报告格式）
from inspection.step_parser import parse_step  # noqa: F401    实体解析

log = logging.getLogger("inspection.step_reviewer")


def extract_features(step_path: str, out_dir: str | None = None) -> dict:
    """兼容旧接口：仅返回特征提取结果（不含审查问题）。"""
    return parse_step(step_path, out_dir)
