import json
import re
import datetime
from pathlib import Path
from collections import Counter

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CommandHandler,
    CallbackQueryHandler,
)

# ================== НАСТРОЙКИ ==================
TOKEN = "8771634921:AAFbVzleb6nKcTFgFTR6ArFcMpmSg0Q-o2E"

# Главный админ (только он может добавлять/удалять админов)
OWNER_ID = 6292502212  # <-- твой user_id

CHANGES_DIR = Path("changes")
CHANGES_DIR.mkdir(exist_ok=True)

ADMINS_FILE = Path("admins.json")


def load_admins() -> set[int]:
    ids: set[int] = set()
    if ADMINS_FILE.exists():
        try:
            data = json.loads(ADMINS_FILE.read_text(encoding="utf-8"))
            ids = set(int(x) for x in data.get("admins", []))
        except Exception:
            ids = set()
    ids.add(OWNER_ID)
    return ids


def save_admins(admins: set[int]) -> None:
    admins = set(admins)
    admins.add(OWNER_ID)
    ADMINS_FILE.write_text(
        json.dumps({"admins": sorted(admins)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


ADMIN_IDS = load_admins()

# ================== НАСТРОЙКА НЕДЕЛЬ ==================
# Привязка: 23.02.2026 (ПН) = 7-я учебная неделя
BASE_MONDAY = datetime.date(2026, 2, 23)
BASE_WEEK_NUMBER = 7


def get_study_week(d: datetime.date) -> int:
    monday = d - datetime.timedelta(days=d.weekday())
    diff_weeks = (monday - BASE_MONDAY).days // 7
    return BASE_WEEK_NUMBER + diff_weeks


def weeks_from(*specs: str) -> set[int]:
    out = set()
    for spec in specs:
        spec = spec.replace(" ", "")
        parts = spec.split(",")
        for p in parts:
            if not p:
                continue
            if "-" in p:
                a, b = p.split("-")
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(p))
    return out


# ================== ВРЕМЯ ПАР ==================
TIME_SLOTS = {
    "Понедельник": {
        "flag": "08:25 - 08:30",
        "talk": "08:30 - 09:00",
        1: "09:10 - 10:40",
        2: "10:50 - 12:20",
        3: "12:50 - 14:20",
        4: "14:30 - 16:00",
        5: "16:10 - 17:40",
        6: "17:50 - 19:20",
    },
    "Вторник": {1: "08:30 - 10:00", 2: "10:10 - 11:40", 3: "12:10 - 13:40", 4: "13:50 - 15:20",
                5: "15:30 - 17:00", 6: "17:10 - 18:40", 7: "18:50 - 20:20"},
    "Среда": {1: "08:30 - 10:00", 2: "10:10 - 11:40", 3: "12:10 - 13:40", 4: "13:50 - 15:20",
              5: "15:30 - 17:00", 6: "17:10 - 18:40", 7: "18:50 - 20:20"},
    "Четверг": {1: "08:30 - 10:00", 2: "10:10 - 11:40", "org": "12:10 - 12:55", 3: "13:00 - 14:30",
                4: "14:40 - 16:10", 5: "16:20 - 17:50", 6: "18:00 - 19:30"},
    "Пятница": {1: "08:30 - 10:00", 2: "10:10 - 11:40", 3: "12:10 - 13:40", 4: "13:50 - 15:20",
                5: "15:30 - 17:00", 6: "17:10 - 18:40", 7: "18:50 - 20:20"},
}

DAYS_MAP = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

# ================== СЛОВАРЬ СОКРАЩЕНИЙ ==================
ABBREV = {
    "ОФГ": "Основы финансовой грамотности",

    "А И ЦУ": "Аналоговые и ЦУ",
    "АИЦУ": "Аналоговые и ЦУ",
    "АНАЛОГОВЫЕ И ЦУ": "Аналоговые и ЦУ",

    "ОА И УЭС": "ОА и УЭС",
    "ОАИУЭС": "ОА и УЭС",

    "ОЭ И ДЭУ": "ОЭ и ДЭУ",
    "ОЭИДЭУ": "ОЭ и ДЭУ",

    "ММРТПЗ": "ММРТПЗ (математические методы)",

    "ОМ И ЭРИ": "ОМ и ЭРИ (метрология)",
    "ОМ ИЭРИ": "ОМ и ЭРИ (метрология)",

    "БЖ": "БЖ",

    "ИН.ЯЗЫК": "Английский язык (1и2п/гр)",
    "ИН. ЯЗЫК": "Английский язык (1и2п/гр)",
    "АНГЛ": "Английский язык (1и2п/гр)",
    "АНГЛИЙСКИЙ": "Английский язык (1и2п/гр)",
    "АНГЛИЙСКИЙ ЯЗЫК": "Английский язык (1и2п/гр)",

    "ФИЗРА": "Физкультура",
    "ФИЗКУЛЬТУРА": "Физкультура",

    "ИЗМ. ТЕХНИКА": "Измерительная техника",
    "ИЗМЕРИТЕЛЬНАЯ ТЕХНИКА": "Измерительная техника",
}


def normalize_subject(user_text: str) -> str:
    s = (user_text or "").strip()
    s = re.sub(r"\s+", " ", s)
    key = s.upper().replace("Ё", "Е")
    return ABBREV.get(key, s)


# ================== БАЗОВОЕ РАСПИСАНИЕ ==================
SCHEDULE = {
    "Понедельник": [
        ("flag", "Поднятие Государственного флага России", "—", "—", weeks_from("1-22")),
        ("talk", "Разговоры о важном / Классный час", "—", "—", weeks_from("1-22")),

        (1, "МДК 01.01", "306", "Федоренко С.В.", weeks_from("1-21")),

        (2, "МДК 01.02", "312", "Черкашин Г.А.", weeks_from("1-6", "8-22")),
        (2, "Физкультура", "—", "Кобзев М.В.", weeks_from("7")),

        (3, "ММРТПЗ (математические методы)", "231", "Иванова О.В.", weeks_from("1", "6", "12", "21")),
        (3, "Основы финансовой грамотности", "318", "Кобзаренко Л.Н.", weeks_from("2", "4", "5", "7", "8")),
        (3, "Физкультура", "—", "Кобзев М.В.", weeks_from("3", "9-11", "16")),
        (3, "Измерительная техника", "312", "Черкашин Г.А.", weeks_from("13-15", "17-20")),

        (4, "БЖ", "418", "Боброва О.В.", weeks_from("1-21")),
    ],

    "Вторник": [
        (1, "ОА и УЭС", "312л", "Самойленко Д.В.", weeks_from("1-20")),
        (2, "ОЭ и ДЭУ", "301л", "Денисенко Д.Т.", weeks_from("1-22")),
        (3, "Аналоговые и ЦУ", "301л", "Денисенко Д.Т.", weeks_from("1-21")),

        (4, "ММРТПЗ (математические методы)", "231", "Иванова О.В.", weeks_from("2", "4", "5", "7-10")),
        (4, "Английский язык (1и2п/гр)", "302/413", "Рахимова/Сорокина", weeks_from("6")),
        (4, "Аналоговые и ЦУ", "301л", "Денисенко Д.Т.", weeks_from("15", "20-21")),
    ],

    "Среда": [
        (1, "Основы финансовой грамотности", "318", "Кобзаренко Л.Н.", weeks_from("1-21")),
        (2, "ММРТПЗ (математические методы)", "231", "Иванова О.В.", weeks_from("1-21")),

        (3, "Аналоговые и ЦУ", "301л", "Денисенко Д.Т.", weeks_from("1-11", "13-21")),
        (3, "Физкультура", "—", "Кобзев М.В.", weeks_from("12")),

        (4, "МДК 01.01", "306", "Федоренко С.В.", weeks_from("1", "3-4", "6-13", "16", "19-21")),
    ],

    "Четверг": [
        (1, "ОА и УЭС", "312л", "Самойленко Д.В.", weeks_from("1", "3", "5", "10", "14", "16", "18-20")),
        (1, "БЖ", "418", "Боброва О.В.", weeks_from("7", "9", "11-13", "17", "21")),

        (2, "Английский язык (1и2п/гр)", "302/413", "Рахимова/Сорокина", weeks_from("1-4", "6-19")),
        (2, "Физкультура", "—", "Кобзев М.В.", weeks_from("5")),

        ("org", "Классный час / Россия — мои горизонты", "—", "—", weeks_from("1-22")),

        (3, "ОМ и ЭРИ (метрология)", "306", "Федоренко С.В.", weeks_from("1-3", "5-9", "11-21")),
        (3, "Физкультура", "—", "Кобзев М.В.", weeks_from("4")),
        (3, "Английский язык (1и2п/гр)", "302/413", "Рахимова/Сорокина", weeks_from("10")),

        (4, "БЖ", "418", "Боброва О.В.", weeks_from("1", "3", "5", "16", "18", "20")),
        (4, "Физкультура", "—", "Кобзев М.В.", weeks_from("2", "14", "15", "17")),
    ],

    "Пятница": [
        (1, "ОЭ и ДЭУ", "301л", "Денисенко Д.Т.", weeks_from("2", "4", "6", "12-15", "17", "19")),
        (1, "Физкультура", "—", "Кобзев М.В.", weeks_from("8", "18")),

        (2, "ОА и УЭС", "312л", "Самойленко Д.В.", weeks_from("1-5", "8-11", "14-20")),
        (2, "Физкультура", "—", "Кобзев М.В.", weeks_from("6", "7", "12", "13")),

        (3, "Физкультура", "—", "Кобзев М.В.", weeks_from("1")),
        (3, "МДК 02.02", "301л", "Денисенко Д.Т.", weeks_from("2", "4", "6", "8", "10-21")),
        (3, "Измерительная техника", "312", "Черкашин Г.А.", weeks_from("3", "5", "7", "9", "11")),

        (4, "МДК 01.02", "312", "Черкашин Г.А.", weeks_from("1-22")),
    ],
}


# ================== СПРАВОЧНИК: предмет -> (кабинет, преподаватель) ==================
def build_subject_defaults() -> dict[str, tuple[str, str]]:
    rooms: dict[str, list[str]] = {}
    teachers: dict[str, list[str]] = {}

    for _day, lessons in SCHEDULE.items():
        for num, subj, room, teacher, _wset in lessons:
            if not isinstance(num, int):
                continue
            subj_key = (subj or "").strip()
            if not subj_key:
                continue
            rooms.setdefault(subj_key, []).append((room or "—").strip())
            teachers.setdefault(subj_key, []).append((teacher or "—").strip())

    defaults: dict[str, tuple[str, str]] = {}
    for subj_key in rooms.keys():
        room = Counter(rooms[subj_key]).most_common(1)[0][0]
        teacher = Counter(teachers[subj_key]).most_common(1)[0][0]
        defaults[subj_key] = (room, teacher)

    return defaults


SUBJECT_DEFAULTS = build_subject_defaults()

# ================== КНОПКИ ==================
KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("Сегодня"), KeyboardButton("Завтра")],
        [KeyboardButton("Неделя"), KeyboardButton("След. неделя")],
        [KeyboardButton("✍️ Изменения (текст)")],
    ],
    resize_keyboard=True,
)

# ================== ИЗМЕНЕНИЯ: файлы ==================
def changes_path(date_iso: str) -> Path:
    return CHANGES_DIR / f"{date_iso}.json"


def load_changes(date_iso: str) -> dict:
    p = changes_path(date_iso)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_changes(date_iso: str, data: dict) -> None:
    changes_path(date_iso).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ================== ИЗМЕНЕНИЯ: парсер текста ==================
def parse_text_changes(message: str):
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    if not lines:
        return None, None

    m = re.search(r"(\d{2}\.\d{2}\.\d{4})", lines[0])
    if not m:
        return None, None

    try:
        date_obj = datetime.datetime.strptime(m.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None, None

    pairs = {}
    for ln in lines[1:]:
        mm = re.match(r"^(\d)\s+(.+)$", ln)
        if not mm:
            continue
        num = int(mm.group(1))
        rest = mm.group(2).strip()

        if rest in ("-", "—"):
            pairs[num] = {"remove": True}
        else:
            subj = normalize_subject(rest)
            pairs[num] = {"remove": False, "subject": subj}

    return date_obj, pairs


# ================== ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ К ДНЮ ==================
def apply_changes_to_filtered(filtered_lessons: list[tuple], date_obj: datetime.date) -> list[tuple]:
    date_iso = date_obj.isoformat()
    data = load_changes(date_iso)
    pairs = (data.get("pairs") or {})
    if not pairs:
        return filtered_lessons

    by_num: dict[int, tuple] = {}
    specials: list[tuple] = []
    for num, subject, room, teacher in filtered_lessons:
        if isinstance(num, int):
            by_num[num] = (num, subject, room, teacher)
        else:
            specials.append((num, subject, room, teacher))

    for k, v in pairs.items():
        try:
            num = int(k)
        except ValueError:
            continue

        if v.get("remove") is True:
            by_num.pop(num, None)
            continue

        new_subject = (v.get("subject") or "—").strip()
        if not new_subject:
            new_subject = "—"

        if new_subject in SUBJECT_DEFAULTS:
            room, teacher = SUBJECT_DEFAULTS[new_subject]
        else:
            room, teacher = "—", "—"

        by_num[num] = (num, new_subject, room, teacher)

    out = specials + list(by_num.values())

    order_map = {"flag": -3, "talk": -2, "org": -1}
    def sort_key(item):
        num = item[0]
        return order_map.get(num, num if isinstance(num, int) else 99)

    out.sort(key=sort_key)
    return out


# ================== ФОРМАТИРОВАНИЕ ==================
def format_day(date_obj: datetime.date) -> str:
    day_name = DAYS_MAP[date_obj.weekday()]
    week_no = get_study_week(date_obj)
    date_str = date_obj.strftime("%d.%m.%y")
    date_iso = date_obj.isoformat()

    text = f"📅 Расписание на {date_str}:\n\n"

    day_lessons = SCHEDULE.get(day_name, [])

    # Выходной: если базы нет, но есть изменения — покажем изменения
    if not day_lessons:
        if not load_changes(date_iso).get("pairs"):
            return text + "Пар нет 🎉"

        filtered = apply_changes_to_filtered([], date_obj)
        text += "⚠️ Есть изменения\n\n"

        filtered.sort(key=lambda x: x[0] if isinstance(x[0], int) else 99)
        for num, subject, room, teacher in filtered:
            t = TIME_SLOTS.get(day_name, {}).get(num, "—")
            text += (
                f"📌 {num} пара\n"
                f"📖 {subject}\n"
                f"🕰️ {t}\n"
                f"🚪 {room}\n"
                f"🎓 {teacher}\n\n"
            )
        return text.rstrip()

    # Будни: фильтр по неделе
    filtered = []
    for num, subj, room, teacher, wset in day_lessons:
        if week_no in wset:
            filtered.append((num, subj, room, teacher))

    filtered = apply_changes_to_filtered(filtered, date_obj)

    if not filtered and not load_changes(date_iso).get("pairs"):
        return text + "Пар нет 🎉"

    if load_changes(date_iso).get("pairs"):
        text += "⚠️ Есть изменения\n\n"

    order_map = {"flag": -3, "talk": -2, "org": -1}
    def sort_key(item):
        num = item[0]
        return order_map.get(num, num if isinstance(num, int) else 99)
    filtered.sort(key=sort_key)

    for num, subject, room, teacher in filtered:
        if num == "flag":
            t = TIME_SLOTS["Понедельник"]["flag"]
            text += f"📌 Поднятие флага\n📖 {subject}\n🕰️ {t}\n\n"
            continue
        if num == "talk":
            t = TIME_SLOTS["Понедельник"]["talk"]
            text += f"📌 Разговоры о важном\n📖 {subject}\n🕰️ {t}\n\n"
            continue
        if num == "org":
            t = TIME_SLOTS["Четверг"]["org"]
            text += f"📌 Классный час\n📖 {subject}\n🕰️ {t}\n\n"
            continue

        t = TIME_SLOTS.get(day_name, {}).get(num, "—")
        text += (
            f"📌 {num} пара\n"
            f"📖 {subject}\n"
            f"🕰️ {t}\n"
            f"🚪 {room}\n"
            f"🎓 {teacher}\n\n"
        )

    return text.rstrip()


def format_week(week_offset: int = 0) -> str:
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    monday = monday + datetime.timedelta(days=7 * week_offset)

    week_no = get_study_week(monday)
    separator = "────────────────────────\n"
    out = [f"📅 Неделя {week_no}\n"]

    for i in range(5):
        d = monday + datetime.timedelta(days=i)
        day_name = DAYS_MAP[d.weekday()]
        wn = get_study_week(d)

        day_lessons = SCHEDULE.get(day_name, [])
        filtered = []
        for num, subj, room, teacher, wset in day_lessons:
            if wn in wset:
                filtered.append((num, subj, room, teacher))

        filtered = apply_changes_to_filtered(filtered, d)

        out.append(separator)
        if not filtered:
            out.append(f"📌 {day_name.upper()} (пар нет)\n")
            continue

        times = []
        for num, *_ in filtered:
            if num == "flag":
                t = TIME_SLOTS["Понедельник"]["flag"]
            elif num == "talk":
                t = TIME_SLOTS["Понедельник"]["talk"]
            elif num == "org":
                t = TIME_SLOTS["Четверг"]["org"]
            else:
                t = TIME_SLOTS.get(day_name, {}).get(num, None)
            if t and " - " in t:
                start, end = t.split(" - ")
                times.append((start, end))

        day_range = f"{min(t[0] for t in times)} - {max(t[1] for t in times)}" if times else "—"
        out.append(f"📌 {day_name.upper()} ({day_range})\n")

        if load_changes(d.isoformat()).get("pairs"):
            out.append("⚠️ Есть изменения\n")

        order_map = {"flag": -3, "talk": -2, "org": -1}
        def sort_key(item):
            num = item[0]
            return order_map.get(num, num if isinstance(num, int) else 99)
        filtered.sort(key=sort_key)

        for num, subject, room, teacher in filtered:
            if num == "flag":
                t = TIME_SLOTS["Понедельник"]["flag"]
                out.append(f"📌 Поднятие флага\n📖 {subject}\n🕰️ {t}\n")
                continue
            if num == "talk":
                t = TIME_SLOTS["Понедельник"]["talk"]
                out.append(f"📌 Разговоры о важном\n📖 {subject}\n🕰️ {t}\n")
                continue
            if num == "org":
                t = TIME_SLOTS["Четверг"]["org"]
                out.append(f"📌 Классный час\n📖 {subject}\n🕰️ {t}\n")
                continue

            t = TIME_SLOTS.get(day_name, {}).get(num, "—")
            out.append(
                f"📌 {num} пара\n"
                f"📖 {subject}\n"
                f"🕰️ {t}\n"
                f"🚪 {room}\n"
                f"🎓 {teacher}\n"
            )

    out.append(separator)
    return "\n".join(out).strip()


# ================== ВВОД ИЗМЕНЕНИЙ ==================
WAITING_TEXT = set()
PENDING = {}


def confirm_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Применить", callback_data="apply_text_changes")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_text_changes")],
        ]
    )


# ================== КОМАНДЫ АДМИНОВ ==================
async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("Нет прав.")
        return
    await update.message.reply_text("👮 Админы:\n" + "\n".join(str(x) for x in sorted(ADMIN_IDS)))


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Добавлять админов может только главный админ.")
        return
    if not context.args:
        await update.message.reply_text("Формат: /addadmin 123456789")
        return
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    ADMIN_IDS.add(new_id)
    save_admins(ADMIN_IDS)
    await update.message.reply_text(f"✅ Добавил админа: {new_id}")


async def cmd_deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Удалять админов может только главный админ.")
        return
    if not context.args:
        await update.message.reply_text("Формат: /deladmin 123456789")
        return
    try:
        del_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return
    if del_id == OWNER_ID:
        await update.message.reply_text("❌ Нельзя удалить главного админа.")
        return
    if del_id in ADMIN_IDS:
        ADMIN_IDS.remove(del_id)
        save_admins(ADMIN_IDS)
        await update.message.reply_text(f"✅ Удалил админа: {del_id}")
    else:
        await update.message.reply_text("Такого админа нет.")


# ================== ХЭНДЛЕРЫ ==================
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш user_id: {update.effective_user.id}")


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if uid not in PENDING:
        await q.edit_message_text("Нет ожидающих изменений.")
        return

    if q.data == "cancel_text_changes":
        PENDING.pop(uid, None)
        WAITING_TEXT.discard(uid)
        await q.edit_message_text("❌ Отменено.")
        return

    if q.data == "apply_text_changes":
        payload = PENDING.pop(uid)
        date_iso = payload["date_iso"]
        pairs = payload["pairs"]

        data = {"date": date_iso, "pairs": pairs}
        save_changes(date_iso, data)

        WAITING_TEXT.discard(uid)
        await q.edit_message_text(f"✅ Применено! Изменения сохранены на {date_iso}.")
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text_raw = update.message.text or ""
    msg = text_raw.strip().lower()

    if msg in ("/start", "start"):
        await update.message.reply_text("Выбирай 👇", reply_markup=KEYBOARD)
        return

    if msg == "сегодня":
        await update.message.reply_text(format_day(datetime.date.today()), reply_markup=KEYBOARD)
        return

    if msg == "завтра":
        d = datetime.date.today() + datetime.timedelta(days=1)
        await update.message.reply_text(format_day(d), reply_markup=KEYBOARD)
        return

    if msg == "неделя":
        await update.message.reply_text(format_week(0), reply_markup=KEYBOARD)
        return

    if msg in ("след. неделя", "след неделя", "следующая неделя"):
        await update.message.reply_text(format_week(1), reply_markup=KEYBOARD)
        return

    if msg == "✍️ изменения (текст)":
        if uid not in ADMIN_IDS:
            await update.message.reply_text("Эту кнопку может использовать только админ.")
            return
        WAITING_TEXT.add(uid)
        await update.message.reply_text(
            "Пришли изменения одним сообщением по шаблону:\n\n"
            "изменения 27.02.2026\n"
            "2 ОФГ\n"
            "3 А и ЦУ\n"
            "4 -\n\n"
            "Где '-' значит пару снять.\n"
            "Кабинет и преподаватель бот возьмёт по предмету из обычного расписания.",
            reply_markup=KEYBOARD,
        )
        return

    if uid in WAITING_TEXT:
        if uid not in ADMIN_IDS:
            WAITING_TEXT.discard(uid)
            await update.message.reply_text("Нет прав администратора.")
            return

        date_obj, pairs = parse_text_changes(text_raw)
        if not date_obj:
            await update.message.reply_text("❌ Не вижу дату. Напиши как: изменения 27.02.2026")
            return
        if not pairs:
            await update.message.reply_text("❌ Не вижу строк вида '2 ОФГ' или '4 -'. Попробуй ещё раз.")
            return

        date_iso = date_obj.isoformat()
        pairs_payload = {str(k): v for k, v in pairs.items()}
        PENDING[uid] = {"date_iso": date_iso, "pairs": pairs_payload}

        lines = [f"Нашёл изменения на {date_obj.strftime('%d.%m.%Y')}:\n"]
        for k in sorted(pairs.keys()):
            if pairs[k].get("remove"):
                lines.append(f"📌 {k} пара → СНЯТЬ")
            else:
                subj = pairs[k].get("subject", "—")
                if subj in SUBJECT_DEFAULTS:
                    r, t = SUBJECT_DEFAULTS[subj]
                    lines.append(f"📌 {k} пара → {subj}  (🚪 {r}, 🎓 {t})")
                else:
                    lines.append(f"📌 {k} пара → {subj}  (🚪 —, 🎓 —)")
        lines.append("\nПрименить?")
        await update.message.reply_text("\n".join(lines), reply_markup=confirm_kb())
        return

    await update.message.reply_text("Нажми кнопку в меню 👇", reply_markup=KEYBOARD)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # базовые команды
    app.add_handler(CommandHandler("id", cmd_id))

    # команды админов
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("deladmin", cmd_deladmin))

    # подтверждение изменений
    app.add_handler(CallbackQueryHandler(on_confirm))

    # текст/кнопки
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, on_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()