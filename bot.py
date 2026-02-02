import os
import logging
from datetime import datetime, date, time

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("birthday-bot")

DAYS_BEFORE = 3
CHECK_TIME = time(9, 0)  # ежедневная проверка (время машины)


def help_text() -> str:
    return (
        "🎂 Я помогу хранить дни рождения и напоминать о них.\n\n"
        "Команды:\n"
        "• /add Имя Дата — добавить/обновить (пример: /add Маша 14.02 или /add Маша 14.02.2004)\n"
        "• /delete Имя — удалить запись (пример: /delete Маша)\n"
        "• /list — показать все сохранённые\n"
        "• /help — помощь\n\n"
        "Форматы даты: DD.MM, DD.MM.YYYY, YYYY-MM-DD (также с '-' или '/')"
    )


def parse_date(raw: str):
    s = raw.strip()

    # ISO: YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y-%m-%d").date()
        return dt.day, dt.month, dt.year
    except ValueError:
        pass

    for sep in (".", "-", "/"):
        parts = s.split(sep)
        if len(parts) == 2:
            dd, mm = parts
            day = int(dd)
            month = int(mm)
            _ = date(2000, month, day)  # проверка валидности
            return day, month, None
        if len(parts) == 3:
            dd, mm, yyyy = parts
            day = int(dd)
            month = int(mm)
            year = int(yyyy)
            _ = date(year, month, day)
            return day, month, year

    raise ValueError("bad date format")


def next_occurrence(day: int, month: int, today: date) -> date:
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def format_bday(name: str, day: int, month: int, year):
    if year is None:
        return f"• {name}: {day:02d}.{month:02d}"
    return f"• {name}: {day:02d}.{month:02d}.{year}"


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /add Имя Дата\nПример: /add Маша 14.02")
        return

    name = context.args[0].strip()
    date_raw = context.args[1].strip()

    if not name:
        await update.message.reply_text("Имя не должно быть пустым.")
        return

    try:
        day, month, year = parse_date(date_raw)
    except Exception:
        await update.message.reply_text(
            "Не понял дату 😿\nФорматы: DD.MM, DD.MM.YYYY, YYYY-MM-DD\nПример: /add Маша 14.02"
        )
        return

    user_id = update.effective_user.id
    db.upsert_birthday(user_id, name, day, month, year)

    shown = f"{day:02d}.{month:02d}" + (f".{year}" if year else "")
    await update.message.reply_text(f"✅ Сохранил: {name} — {shown}")


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /delete Имя\nПример: /delete Маша")
        return

    name = context.args[0].strip()
    if not name:
        await update.message.reply_text("Имя не должно быть пустым.")
        return

    user_id = update.effective_user.id
    deleted = db.delete_birthday(user_id, name)

    if deleted:
        await update.message.reply_text(f"🗑️ Удалил: {name}")
    else:
        await update.message.reply_text(f"Не нашёл «{name}». Проверь имя или посмотри /list.")


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    items = db.list_birthdays(user_id)

    if not items:
        await update.message.reply_text("Пока пусто. Добавь: /add Имя Дата")
        return

    today = date.today()
    lines = ["🎂 Твои дни рождения:\n"]
    for it in items:
        lines.append(format_bday(it["name"], it["day"], it["month"], it["year"]))

    # ближайшее
    nearest = min(
        ((next_occurrence(it["day"], it["month"], today) - today).days, it["name"], it)
        for it in items
    )
    diff, nm, it = nearest
    occ = next_occurrence(it["day"], it["month"], today)

    if diff == 0:
        tail = f"\n\n🔥 Ближайшее: сегодня у {nm} ({occ.strftime('%d.%m')})"
    elif diff == 1:
        tail = f"\n\n✨ Ближайшее: завтра у {nm} ({occ.strftime('%d.%m')})"
    else:
        tail = f"\n\n✨ Ближайшее: через {diff} дн. у {nm} ({occ.strftime('%d.%m')})"

    await update.message.reply_text("\n".join(lines) + tail)


def reminder_text(name: str, when: date, days_left: int) -> str:
    if days_left == 0:
        return f"🎉 Сегодня день рождения у *{name}* — {when.strftime('%d.%m')}!"
    if days_left == 1:
        return f"⏰ Завтра день рождения у *{name}* — {when.strftime('%d.%m')}."
    return f"⏰ Через *{days_left}* дн. день рождения у *{name}* — {when.strftime('%d.%m')}."


async def daily_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    for user_id in db.get_all_users():
        for b in db.get_birthdays_for_user(user_id):
            occ = next_occurrence(b["day"], b["month"], today)
            days_left = (occ - today).days

            if not (0 <= days_left <= DAYS_BEFORE):
                continue

            # чтобы не слать повторно каждый день — 1 раз в год на запись
            if b["last_notified_year"] == occ.year:
                continue

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=reminder_text(b["name"], occ, days_left),
                    parse_mode=ParseMode.MARKDOWN,
                )
                db.set_last_notified_year(b["id"], occ.year)
            except Exception as e:
                logger.warning("Cannot send to %s: %s", user_id, e)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Ошибка 😿 Попробуй ещё раз или /help")
    except Exception:
        pass


def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не найден. Проверь .env (BOT_TOKEN=...)")

    db.init_db()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("list", list_cmd))

    app.add_error_handler(error_handler)

    app.job_queue.run_daily(daily_check, time=CHECK_TIME)

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
