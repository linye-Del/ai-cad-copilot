"""全局配置：config.yaml + .env + 内置默认值 三级加载。

优先级：环境变量(.env) > config.yaml > 默认值。
敏感信息（DEEPSEEK_API_KEY）仅从 .env 读取。
"""

import glob
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"
OUTPUT_DIR = ROOT_DIR / "output"
PARTS_DIR = ROOT_DIR / "cad_engine" / "parts"
SCRIPTS_DIR = ROOT_DIR / "scripts"

load_dotenv(ROOT_DIR / ".env")

_DEFAULTS = {
    "app": {"name": "AI CAD Copilot", "version": "0.2.0", "host": "127.0.0.1", "port": 8000,
            "cors_origins": ["http://127.0.0.1:8000", "http://localhost:8000",
                             "http://127.0.0.1:5173", "http://localhost:5173"]},
    "freecad": {"bin": "", "run_timeout": 900, "max_retries": 2},
    "output": {"dir": "output", "sessions_ttl_sec": 7200},
    "llm": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
            "temperature": 0.1, "timeout": 180, "agent_recursion_limit": 50},
    "logging": {"level": "INFO", "file": "output/logs/app.log", "max_bytes": 5242880, "backup_count": 3},
}

_config = dict(_DEFAULTS)
if CONFIG_PATH.is_file():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    for section, values in loaded.items():
        if isinstance(values, dict) and section in _config:
            _config[section].update(values)
        else:
            _config[section] = values


def get(section: str, key: str, default=None):
    return _config.get(section, {}).get(key, default)


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def find_freecad_cmd() -> str:
    """定位 FreeCADCmd.exe：env FREECAD_BIN > config.yaml freecad.bin > 常见安装路径。"""
    env_bin = get_env("FREECAD_BIN", get("freecad", "bin", ""))
    if env_bin and os.path.isfile(env_bin):
        return env_bin
    candidates = [
        Path(env_bin),
        Path("D:/applicant/bin/freecadcmd.exe"),
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "FreeCAD 1.1" / "bin" / "FreeCADCmd.exe",
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "FreeCAD 1.0" / "bin" / "FreeCADCmd.exe",
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "FreeCAD" / "bin" / "FreeCADCmd.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    hits = sorted(
        glob.glob(
            os.path.join(
                os.environ.get("ProgramFiles", "C:\\Program Files"), "FreeCAD*", "bin", "FreeCADCmd.exe"
            )
        )
    )
    if hits:
        return hits[-1]
    return ""


def get_api_key() -> str:
    return get_env("DEEPSEEK_API_KEY")


def get_api_base() -> str:
    return get_env("DEEPSEEK_BASE_URL", get("llm", "base_url", "https://api.deepseek.com"))


def get_model() -> str:
    return get_env("DEEPSEEK_MODEL", get("llm", "model", "deepseek-chat"))


def get_llm_temperature() -> float:
    return float(get("llm", "temperature", 0.1))


def get_llm_timeout() -> float:
    return float(get("llm", "timeout", 180))


def get_agent_recursion_limit() -> int:
    return int(get("llm", "agent_recursion_limit", 50))


def get_reports_dir() -> Path:
    """审查报告输出目录（自动创建）。"""
    d = ROOT_DIR / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d
