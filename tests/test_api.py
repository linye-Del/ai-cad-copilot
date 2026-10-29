"""API 冒烟测试（TestClient，无需外部服务）。

FreeCAD 相关接口在无 FreeCAD 环境（CI）自动跳过。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from config import settings


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_part_types(client):
    r = client.get("/api/part-types")
    assert r.status_code == 200
    parts = r.json()["parts"]
    assert set(parts) == {"bolt", "shaft", "flange", "gear"}
    assert parts["bolt"]["standard"] == "GB/T 5782-2016"


def test_parse_fallback_rules(client):
    """无 Key 环境（CI）parse 回退规则引擎。"""
    r = client.post("/api/parse", json={"text": "生成一个M10×40的六角头螺栓，8.8级"})
    assert r.status_code == 200
    spec = r.json()["spec"]
    assert spec["part_type"] == "bolt"
    assert spec["params"]["d"] == 10


def test_parse_invalid_text(client):
    r = client.post("/api/parse", json={"text": "你好"})
    assert r.status_code in (200, 422)  # 规则回退失败则 422


def test_session_crud(client):
    sid = client.post("/api/sessions").json()["id"]
    assert sid
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    r = client.delete(f"/api/sessions/{sid}")
    assert r.json()["closed"] is True


def test_session_not_found(client):
    r = client.get("/api/sessions/nonexistent123")
    assert r.status_code == 404


@pytest.mark.skipif(not settings.find_freecad_cmd(), reason="FreeCAD 不可用（CI）")
def test_model_generation(client):
    """FreeCAD 可用时验证建模链路。"""
    sid = client.post("/api/sessions").json()["id"]
    r = client.post(f"/api/sessions/{sid}/parts",
                    json={"part_type": "bolt", "part_name": "M10x40",
                          "params": {"d": 10, "L": 40}})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert set(r.json()["files"]) >= {"fcstd", "step", "stl"}
