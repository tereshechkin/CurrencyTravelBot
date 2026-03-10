# -*- coding: utf-8 -*-
"""
Конфигурация бота.
Первая переменная — access_key для api.exchangerate.host, вторая — Telegram-токен.
Можно задать через переменные окружения или в этом файле (не коммитить секреты).
"""

import os
from pathlib import Path

# Загрузка из .env если есть (опционально)
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

# 1) Ключ API exchangerate.host
EXCHANGERATE_ACCESS_KEY = os.environ.get("EXCHANGERATE_ACCESS_KEY", "")

# 2) Токен Telegram-бота
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# База данных (локально)
DB_PATH = Path(__file__).resolve().parent / "bot_data.db"
