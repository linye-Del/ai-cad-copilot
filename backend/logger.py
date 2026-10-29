"""统一日志系统：控制台 + 滚动文件，配置来自 config.yaml。"""

import logging
import logging.handlers
import sys

from config import settings


def setup_logging(level: str | None = None, file: str | None = None) -> None:
    """初始化根日志器。幂等：重复调用仅补缺失的 handler。"""
    level = (level or settings.get("logging", "level", "INFO")).upper()
    file = file or settings.get("logging", "file", "output/logs/app.log")
    log_file = settings.ROOT_DIR / file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if not root.handlers:
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)

    # 文件 handler 每次 setup 只加一个（按路径去重）
    existing = {getattr(h, "baseFilename", None) for h in root.handlers}
    if str(log_file) not in existing:
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=int(settings.get("logging", "max_bytes", 5242880)),
            backupCount=int(settings.get("logging", "backup_count", 3)),
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
        root.addHandler(fh)

    root.setLevel(getattr(logging, level, logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """获取模块级日志器。"""
    setup_logging()
    return logging.getLogger(name)
