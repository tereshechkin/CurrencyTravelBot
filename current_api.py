# -*- coding: utf-8 -*-
"""
Модуль для работы с API api.exchangerate.host.
Все запросы идут на указанные endpoint с параметром access_key.
"""

import requests
from typing import Optional, Tuple, Dict, Any

BASE_URL = "http://api.exchangerate.host"


def _get_access_key() -> str:
    """Читает access_key из конфигурации."""
    from config import EXCHANGERATE_ACCESS_KEY
    return EXCHANGERATE_ACCESS_KEY


def get_currencies_list() -> Tuple[bool, Optional[Dict[str, str]], Optional[str]]:
    """
    Запрашивает список поддерживаемых валют (код -> название).
    Возвращает: (success, currencies_dict, error_message).
    """
    try:
        r = requests.get(
            f"{BASE_URL}/list",
            params={"access_key": _get_access_key()},
            timeout=10,
        )
        data = r.json()
        if not data.get("success"):
            err = data.get("error", {})
            info = err.get("info", "Неизвестная ошибка API")
            return False, None, info
        return True, data.get("currencies"), None
    except requests.RequestException as e:
        return False, None, f"Ошибка сети: {e}"
    except Exception as e:
        return False, None, str(e)


def is_currency_available(code: str) -> bool:
    """Проверяет, что валюта есть в списке API."""
    ok, currencies, _ = get_currencies_list()
    if not ok or not currencies:
        return False
    return (code or "").upper() in currencies


def convert(
    from_currency: str,
    to_currency: str,
    amount: float,
) -> Tuple[bool, Optional[float], Optional[float], Optional[str]]:
    """
    Конвертирует сумму из одной валюты в другую через endpoint /convert.
    Возвращает: (success, result_amount, rate_used, error_message).
    """
    if amount <= 0:
        return False, None, None, "Сумма должна быть положительной."
    try:
        r = requests.get(
            f"{BASE_URL}/convert",
            params={
                "access_key": _get_access_key(),
                "from": from_currency.upper(),
                "to": to_currency.upper(),
                "amount": amount,
            },
            timeout=10,
        )
        data = r.json()
        if not data.get("success"):
            err = data.get("error", {})
            info = err.get("info", "Неизвестная ошибка API")
            return False, None, None, info
        result = data.get("result")
        rate = None
        if "info" in data and isinstance(data["info"], dict):
            rate = data["info"].get("quote")
        return True, result, rate, None
    except requests.RequestException as e:
        return False, None, None, f"Ошибка сети: {e}"
    except Exception as e:
        return False, None, None, str(e)


def get_rate(from_currency: str, to_currency: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Получает текущий курс from -> to (сколько to за 1 from).
    Возвращает: (success, rate, error_message).
    """
    ok, result, rate, err = convert(from_currency, to_currency, 1.0)
    if not ok:
        return False, None, err
    return True, result, None  # result для amount=1 и есть курс
