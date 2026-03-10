# -*- coding: utf-8 -*-
"""
Telegram-бот «Миникошелёк для путешественника».
API: api.exchangerate.host (только он). Локальное хранилище: SQLite.
"""

import json
import re
import logging
import telebot
from telebot import types

from config import BOT_TOKEN
from current_api import get_currencies_list, convert, get_rate, is_currency_available
from country_currency import country_to_currency
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# --- Inline callback prefixes
CB_MAIN = "main"
CB_NEWTRIP = "newtrip"
CB_MYTRIPS = "mytrips"
CB_SWITCH = "switch"
CB_BALANCE = "balance"
CB_HISTORY = "history"
CB_SETRATE = "setrate"
CB_EXPENSE_YES = "exp_yes"
CB_EXPENSE_NO = "exp_no"


def _main_keyboard():
    """Главное меню — inline-кнопки."""
    return types.InlineKeyboardMarkup(row_width=1).add(
        types.InlineKeyboardButton("Создать новое путешествие", callback_data=CB_NEWTRIP),
        types.InlineKeyboardButton("Мои путешествия", callback_data=CB_MYTRIPS),
        types.InlineKeyboardButton("Баланс", callback_data=CB_BALANCE),
        types.InlineKeyboardButton("История расходов", callback_data=CB_HISTORY),
        types.InlineKeyboardButton("Изменить курс", callback_data=CB_SETRATE),
    )


def _format_balance(trip):
    """Форматирует баланс в двух валютах."""
    b_from = trip["balance_from"]
    b_to = trip["balance_to"]
    return "Остаток: {} {} = {:,.0f} {}".format(
        _fmt_num(b_to), trip["to_currency"], b_from, trip["from_currency"]
    ).replace(",", " ")


def _fmt_num(x):
    """Число с пробелами как разделителями тысяч."""
    s = "{:,.2f}".format(round(float(x), 2))
    return s.replace(",", " ").rstrip("0").rstrip(".")


def _parse_number(text):
    """Парсит число из текста (допускает запятую/точку). Возвращает float или None."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip().replace(",", ".")
    if not re.match(r"^-?\d*\.?\d+$", text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def send_main_menu(chat_id, text=None):
    if text is None:
        text = "Выберите действие:"
    bot.send_message(chat_id, text, reply_markup=_main_keyboard())


# --- /start и приветствие
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    db.ensure_user(uid)
    db.clear_user_state(uid)
    active = db.get_active_trip(uid)
    if active:
        send_main_menu(
            message.chat.id,
            "Добро пожаловать! Активное путешествие: «{}». Выберите действие:".format(active["name"]),
        )
    else:
        text = (
            "Добро пожаловать! Это миникошелёк для путешественника. "
            "Создайте путешествие, чтобы начать учёт расходов в двух валютах."
        )
        send_main_menu(message.chat.id, text)


# --- Inline: главное меню и пункты
@bot.callback_query_handler(func=lambda c: c.data == CB_MAIN)
def cb_main(callback):
    bot.answer_callback_query(callback.id)
    db.clear_user_state(callback.from_user.id)
    send_main_menu(callback.message.chat.id, "Выберите действие:")
    try:
        bot.edit_message_reply_markup(callback.message.chat.id, callback.message.message_id, reply_markup=None)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == CB_NEWTRIP)
def cb_newtrip(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    db.ensure_user(uid)
    db.set_user_state(uid, "newtrip_from", None)
    bot.send_message(
        callback.message.chat.id,
        "Введите страну отправления (домашняя валюта), например: Россия или RUB:",
    )


def _ask_destination(chat_id):
    bot.send_message(chat_id, "Введите страну назначения (валюта поездки), например: Китай или CNY:")


def _trip_created(chat_id, uid, trip_name):
    db.clear_user_state(uid)
    send_main_menu(chat_id, "Путешествие «{}» создано. Выберите действие:".format(trip_name))


@bot.callback_query_handler(func=lambda c: c.data == CB_MYTRIPS)
def cb_mytrips(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    trips = db.get_trips(uid)
    if not trips:
        bot.send_message(
            callback.message.chat.id,
            "У вас пока нет путешествий. Создайте новое — кнопка «Создать новое путешествие».",
            reply_markup=_main_keyboard(),
        )
        return
    lines = ["Ваши путешествия:\n"]
    kb = types.InlineKeyboardMarkup(row_width=1)
    active = db.get_active_trip(uid)
    for t in trips:
        mark = " ✓" if active and active["id"] == t["id"] else ""
        lines.append("• {} — {} / {}{}".format(t["name"], t["from_currency"], t["to_currency"], mark))
        kb.add(types.InlineKeyboardButton(
            "{} {} / {}".format(t["name"], t["from_currency"], t["to_currency"]),
            callback_data="{}:{}".format(CB_SWITCH, t["id"]),
        ))
    kb.add(types.InlineKeyboardButton("← В главное меню", callback_data=CB_MAIN))
    bot.send_message(callback.message.chat.id, "\n".join(lines), reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith(CB_SWITCH + ":"))
def cb_switch(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    try:
        trip_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        bot.send_message(callback.message.chat.id, "Ошибка выбора.", reply_markup=_main_keyboard())
        return
    trip = db.get_trip(trip_id, uid)
    if not trip:
        bot.send_message(callback.message.chat.id, "Путешествие не найдено.", reply_markup=_main_keyboard())
        return
    db.set_active_trip(uid, trip_id)
    bot.send_message(
        callback.message.chat.id,
        "Активное путешествие: «{}». Теперь суммы в сообщениях будут считаться в {}.".format(trip["name"], trip["to_currency"]),
        reply_markup=_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda c: c.data == CB_BALANCE)
def cb_balance(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(
            callback.message.chat.id,
            "Нет активного путешествия. Выберите или создайте путешествие в «Мои путешествия».",
            reply_markup=_main_keyboard(),
        )
        return
    bot.send_message(
        callback.message.chat.id,
        "«{}»\n{}".format(active["name"], _format_balance(active)),
        reply_markup=_main_keyboard(),
    )


@bot.callback_query_handler(func=lambda c: c.data == CB_HISTORY)
def cb_history(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(
            callback.message.chat.id,
            "Нет активного путешествия. Выберите путешествие в «Мои путешествия».",
            reply_markup=_main_keyboard(),
        )
        return
    expenses = db.get_expenses(active["id"])
    if not expenses:
        bot.send_message(
            callback.message.chat.id,
            "В путешествии «{}» пока нет учтённых расходов.".format(active["name"]),
            reply_markup=_main_keyboard(),
        )
        return
    lines = ["История расходов («{}»):\n".format(active["name"])]
    for e in expenses[:20]:
        lines.append("{} {} = {} {}".format(
            _fmt_num(e["amount_to"]), active["to_currency"],
            _fmt_num(e["amount_from"]), active["from_currency"],
        ))
    bot.send_message(callback.message.chat.id, "\n".join(lines), reply_markup=_main_keyboard())


@bot.callback_query_handler(func=lambda c: c.data == CB_SETRATE)
def cb_setrate(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(
            callback.message.chat.id,
            "Нет активного путешествия. Выберите путешествие в «Мои путешествия».",
            reply_markup=_main_keyboard(),
        )
        return
    db.set_user_state(uid, "setrate", str(active["id"]))
    bot.send_message(
        callback.message.chat.id,
        "Текущий курс: 1 {} = {} {}.\nВведите новый курс (сколько {} за 1 {}):".format(
            active["to_currency"], _fmt_num(active["rate"]), active["from_currency"],
            active["from_currency"], active["to_currency"],
        ),
    )


# --- Подтверждение расхода
@bot.callback_query_handler(func=lambda c: c.data == CB_EXPENSE_YES)
def cb_expense_yes(callback):
    bot.answer_callback_query(callback.id)
    uid = callback.from_user.id
    state, state_data = db.get_user_state(uid)
    if state != "expense_confirm" or not state_data:
        bot.send_message(callback.message.chat.id, "Сессия устарела. Введите сумму заново.")
        db.clear_user_state(uid)
        return
    try:
        data = json.loads(state_data)
        trip_id = data["trip_id"]
        amount_to = data["amount_to"]
        amount_from = data["amount_from"]
    except (json.JSONDecodeError, KeyError):
        db.clear_user_state(uid)
        bot.send_message(callback.message.chat.id, "Ошибка данных. Введите сумму заново.")
        return
    trip = db.get_trip(trip_id, uid)
    if not trip:
        db.clear_user_state(uid)
        bot.send_message(callback.message.chat.id, "Путешествие не найдено.")
        return
    if not db.add_expense(trip_id, amount_to, amount_from):
        bot.send_message(callback.message.chat.id, "Недостаточно средств на балансе.")
    else:
        updated = db.get_trip(trip_id, uid)
        bot.send_message(
            callback.message.chat.id,
            "Расход учтён. {}".format(_format_balance(updated)),
            reply_markup=_main_keyboard(),
        )
    db.clear_user_state(uid)
    try:
        bot.edit_message_reply_markup(callback.message.chat.id, callback.message.message_id, reply_markup=None)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == CB_EXPENSE_NO)
def cb_expense_no(callback):
    bot.answer_callback_query(callback.id)
    db.clear_user_state(callback.from_user.id)
    bot.send_message(callback.message.chat.id, "Расход не учтён. Можете ввести другую сумму.", reply_markup=_main_keyboard())
    try:
        bot.edit_message_reply_markup(callback.message.chat.id, callback.message.message_id, reply_markup=None)
    except Exception:
        pass


# --- Обработка текстовых сообщений (FSM и числа как расходы)
@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message):
    try:
        _on_text_impl(message)
    except Exception as e:
        logger.exception("Ошибка при обработке сообщения")
        bot.send_message(
            message.chat.id,
            "Произошла ошибка. Попробуйте ещё раз или выберите пункт в меню.",
            reply_markup=_main_keyboard(),
        )


def _on_text_impl(message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    chat_id = message.chat.id
    db.ensure_user(uid)

    state, state_data = db.get_user_state(uid)

    # --- Создание путешествия: страна отправления
    if state == "newtrip_from":
        from_cur = country_to_currency(text)
        if not from_cur:
            bot.send_message(chat_id, "Не удалось определить валюту по введённой стране. Введите страну или код валюты (3 буквы), например: Россия, RUB.")
            return
        ok = is_currency_available(from_cur)
        if not ok:
            bot.send_message(chat_id, "К сожалению, валюта {} недоступна в API. Попробуйте другую страну или код валюты.".format(from_cur))
            return
        db.set_user_state(uid, "newtrip_to", from_cur)
        _ask_destination(chat_id)
        return

    # --- Создание путешествия: страна назначения
    if state == "newtrip_to":
        if not state_data:
            db.set_user_state(uid, "newtrip_from", None)
            send_main_menu(chat_id, "Начните заново: введите страну отправления.")
            return
        from_cur = state_data
        to_cur = country_to_currency(text)
        if not to_cur:
            bot.send_message(chat_id, "Не удалось определить валюту. Введите страну или код валюты (3 буквы).")
            return
        if to_cur == from_cur:
            bot.send_message(chat_id, "Валюта назначения должна отличаться от домашней. Введите другую страну.")
            return
        ok = is_currency_available(to_cur)
        if not ok:
            bot.send_message(chat_id, "Валюта {} недоступна в API. Попробуйте другую страну.".format(to_cur))
            return
        # Получаем курс: 1 to_cur = ? from_cur
        ok, rate, err = get_rate(to_cur, from_cur)
        if not ok:
            bot.send_message(chat_id, "Не удалось получить курс: {}. Введите курс вручную (сколько {} за 1 {}):".format(err or "", from_cur, to_cur))
            db.set_user_state(uid, "newtrip_manual_rate", json.dumps({"from": from_cur, "to": to_cur, "name": text}))
            return
        # Показываем курс и спрашиваем подходит ли
        db.set_user_state(uid, "newtrip_rate_ok", json.dumps({"from": from_cur, "to": to_cur, "name": text, "rate": rate}))
        bot.send_message(
            chat_id,
            "Курс: 1 {} = {} {}.\nПодходит? (да / нет)".format(to_cur, _fmt_num(rate), from_cur),
        )
        return

    # --- Подтверждение курса (да/нет)
    if state == "newtrip_rate_ok" and state_data:
        try:
            data = json.loads(state_data)
        except json.JSONDecodeError:
            db.clear_user_state(uid)
            send_main_menu(chat_id, "Ошибка. Начните создание путешествия заново.")
            return
        yes = text.lower() in ("да", "yes", "y", "подходит")
        no = text.lower() in ("нет", "no", "n", "не подходит")
        if yes:
            db.set_user_state(uid, "newtrip_initial_sum", state_data)
            bot.send_message(chat_id, "Введите начальную сумму в домашней валюте ({}):".format(data["from"]))
            return
        if no:
            db.set_user_state(uid, "newtrip_manual_rate", state_data)
            bot.send_message(
                chat_id,
                "Введите курс вручную: сколько {} за 1 {} (например, курс обменника):".format(data["from"], data["to"]),
            )
            return
        bot.send_message(chat_id, "Ответьте «да» или «нет».")
        return

    # --- Ручной ввод курса
    if state == "newtrip_manual_rate" and state_data:
        num = _parse_number(text)
        if num is None or num <= 0:
            bot.send_message(chat_id, "Введите положительное число (курс).")
            return
        try:
            data = json.loads(state_data)
        except json.JSONDecodeError:
            db.clear_user_state(uid)
            send_main_menu(chat_id, "Ошибка. Начните заново.")
            return
        data["rate"] = num
        db.set_user_state(uid, "newtrip_initial_sum", json.dumps(data))
        bot.send_message(chat_id, "Введите начальную сумму в домашней валюте ({}):".format(data["from"]))
        return

    # --- Начальная сумма и создание путешествия
    if state == "newtrip_initial_sum" and state_data:
        num = _parse_number(text)
        if num is None or num <= 0:
            bot.send_message(chat_id, "Введите положительное число (сумма в домашней валюте).")
            return
        try:
            data = json.loads(state_data)
        except json.JSONDecodeError:
            db.clear_user_state(uid)
            send_main_menu(chat_id, "Ошибка. Создайте путешествие заново.")
            return
        from_cur = data["from"]
        to_cur = data["to"]
        rate = data["rate"]
        name = data.get("name", to_cur)
        ok, balance_to, _, err = convert(from_cur, to_cur, num)
        if not ok:
            bot.send_message(chat_id, "Ошибка конвертации: {}. Путешествие не создано.".format(err or ""))
            db.clear_user_state(uid)
            send_main_menu(chat_id)
            return
        db.create_trip(uid, name, from_cur, to_cur, rate, num, balance_to)
        _trip_created(chat_id, uid, name)
        return

    # --- Ожидание подтверждения расхода (кнопка Да/Нет)
    if state == "expense_confirm":
        bot.send_message(chat_id, "Подтвердите или отмените расход кнопками выше (✅ Да / ❌ Нет).")
        return

    # --- Смена курса
    if state == "setrate" and state_data:
        try:
            trip_id = int(state_data)
        except (ValueError, TypeError):
            db.clear_user_state(uid)
            send_main_menu(chat_id, "Ошибка. Выберите «Изменить курс» снова.")
            return
        num = _parse_number(text)
        if num is None or num <= 0:
            bot.send_message(chat_id, "Введите положительное число (новый курс).")
            return
        if db.update_trip_rate(trip_id, uid, num):
            trip = db.get_trip(trip_id, uid)
            bot.send_message(
                chat_id,
                "Курс обновлён: 1 {} = {} {}.".format(trip["to_currency"], _fmt_num(num), trip["from_currency"]),
                reply_markup=_main_keyboard(),
            )
        else:
            bot.send_message(chat_id, "Не удалось обновить курс. Путешествие не найдено.", reply_markup=_main_keyboard())
        db.clear_user_state(uid)
        return

    # --- Число в обычном режиме = расход в валюте пребывания
    active = db.get_active_trip(uid)
    if not active:
        send_main_menu(chat_id, "Сначала выберите или создайте путешествие в меню.")
        return

    num = _parse_number(text)
    if num is None:
        send_main_menu(chat_id, "Не понял. Введите число для учёта расхода в {} или выберите действие в меню.".format(active["to_currency"]))
        return
    if num <= 0:
        bot.send_message(chat_id, "Введите положительную сумму расхода.")
        return

    amount_to = num
    # Конвертируем в домашнюю по текущему курсу путешествия
    amount_from = amount_to * active["rate"]
    ok, api_result, _, err = convert(active["to_currency"], active["from_currency"], amount_to)
    if ok and api_result is not None:
        amount_from = api_result

    msg = "{} {} = {} {}\nУчесть как расход?".format(
        _fmt_num(amount_to), active["to_currency"], _fmt_num(amount_from), active["from_currency"],
    )
    kb = types.InlineKeyboardMarkup(row_width=2).add(
        types.InlineKeyboardButton("✅ Да", callback_data=CB_EXPENSE_YES),
        types.InlineKeyboardButton("❌ Нет", callback_data=CB_EXPENSE_NO),
    )
    db.set_user_state(uid, "expense_confirm", json.dumps({
        "trip_id": active["id"], "amount_to": amount_to, "amount_from": amount_from,
    }))
    bot.send_message(chat_id, msg, reply_markup=kb)


# --- Слэш-команды как альтернатива
@bot.message_handler(commands=["newtrip"])
def cmd_newtrip(message):
    db.ensure_user(message.from_user.id)
    db.set_user_state(message.from_user.id, "newtrip_from", None)
    bot.send_message(
        message.chat.id,
        "Введите страну отправления (домашняя валюта), например: Россия или RUB:",
    )


@bot.message_handler(commands=["switch"])
def cmd_switch(message):
    uid = message.from_user.id
    trips = db.get_trips(uid)
    if not trips:
        bot.send_message(message.chat.id, "Нет путешествий. Создайте: /newtrip или кнопка «Создать новое путешествие».", reply_markup=_main_keyboard())
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for t in trips:
        kb.add(types.InlineKeyboardButton("{} {} / {}".format(t["name"], t["from_currency"], t["to_currency"]), callback_data="{}:{}".format(CB_SWITCH, t["id"])))
    kb.add(types.InlineKeyboardButton("← В главное меню", callback_data=CB_MAIN))
    bot.send_message(message.chat.id, "Выберите путешествие:", reply_markup=kb)


@bot.message_handler(commands=["balance"])
def cmd_balance(message):
    uid = message.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(message.chat.id, "Нет активного путешествия. /switch — выбрать.", reply_markup=_main_keyboard())
        return
    bot.send_message(message.chat.id, "«{}»\n{}".format(active["name"], _format_balance(active)), reply_markup=_main_keyboard())


@bot.message_handler(commands=["history"])
def cmd_history(message):
    uid = message.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(message.chat.id, "Нет активного путешествия. /switch — выбрать.", reply_markup=_main_keyboard())
        return
    expenses = db.get_expenses(active["id"])
    if not expenses:
        bot.send_message(message.chat.id, "В путешествии «{}» пока нет расходов.".format(active["name"]), reply_markup=_main_keyboard())
        return
    lines = ["История («{}»):\n".format(active["name"])]
    for e in expenses[:20]:
        lines.append("{} {} = {} {}".format(_fmt_num(e["amount_to"]), active["to_currency"], _fmt_num(e["amount_from"]), active["from_currency"]))
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=_main_keyboard())


@bot.message_handler(commands=["setrate"])
def cmd_setrate(message):
    uid = message.from_user.id
    active = db.get_active_trip(uid)
    if not active:
        bot.send_message(message.chat.id, "Нет активного путешествия. /switch — выбрать.", reply_markup=_main_keyboard())
        return
    db.set_user_state(uid, "setrate", str(active["id"]))
    bot.send_message(
        message.chat.id,
        "Текущий курс: 1 {} = {} {}. Введите новый курс:".format(active["to_currency"], _fmt_num(active["rate"]), active["from_currency"]),
    )


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан. Укажите в .env или переменной окружения BOT_TOKEN.")
        return
    from config import EXCHANGERATE_ACCESS_KEY
    if not EXCHANGERATE_ACCESS_KEY:
        logger.error("EXCHANGERATE_ACCESS_KEY не задан. Укажите в .env или переменной окружения.")
        return
    db.init_db()
    logger.info("Бот запущен.")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
