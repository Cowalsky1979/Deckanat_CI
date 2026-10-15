"""Telegram-бот Онлайн-деканат (aiogram 3).

Запуск: BOT_TOKEN=... API_BASE_URL=http://localhost:8000 python -m bot
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           MenuButtonDefault, Message, ReplyKeyboardMarkup)
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from bot import api_client as api  # noqa: E402
from bot import texts  # noqa: E402

log = logging.getLogger("bot")
router = Router()

MAX_TG_FILE = 20 * 1024 * 1024
# публичный адрес сайта меняется при переподключении туннеля, поэтому читаем его при каждом нажатии:
# сначала из файла от tunnel_keeper.py, потом из SITE_URL (WEBAPP_URL - старое имя переменной)
_URL_FILE = Path(os.environ.get("SITE_URL_FILE", Path(__file__).resolve().parents[1] / "runtime" / "site_url.txt"))
SITE_BTN = "🌐 Открыть приложение"   # кнопка клавиатуры: присылает ссылку на сайт


def site_url() -> str:
    try:
        if _URL_FILE.exists():
            u = _URL_FILE.read_text(encoding="utf-8").strip()
            if u.startswith("https://"):
                return u.rstrip("/")
    except OSError:
        pass
    return (os.environ.get("SITE_URL") or os.environ.get("WEBAPP_URL", "")).rstrip("/")


def site_button(text: str, path: str = "/") -> InlineKeyboardButton | None:
    """Обычная ссылка на сайт, открывается в браузере."""
    url = site_url()
    if not url:
        return None
    return InlineKeyboardButton(text=text, url=f"{url}{path}")


COMPLETENESS_Q = "Содержит ли документ все обязательные сведения по Положению?"


class Flow(StatesGroup):
    waiting_type = State()
    ready = State()


HISTORY_BTN = "📂 Мои документы"
SUBMIT_BTN = "📨 Отправить в деканат"

# профили кабинета по Telegram id (создаются на бэкенде один раз, здесь только кэш)
_profiles: dict[str, str] = {}


async def profile_id(user, *, refresh: bool = False) -> str | None:
    """Профиль студента, привязанный к Telegram-аккаунту: загрузки попадают в кабинет, решения приходят в чат.
    refresh=True пересоздаёт профиль (например, базу очистили, и закэшированный id больше не существует)."""
    uid = str(user.id)
    if refresh:
        _profiles.pop(uid, None)
    if uid in _profiles:
        return _profiles[uid]
    try:
        p = await api.ensure_profile(user.full_name or user.username or "", uid)
    except (api.ApiError, httpx.HTTPError) as exc:
        log.warning("Не удалось создать профиль для %s: %s", uid, exc)
        return None
    _profiles[uid] = p["id"]
    return p["id"]


def main_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="✅ Проверить комплектность"), KeyboardButton(text="🗂 Карточка полей")],
        [KeyboardButton(text="🖼 Снимок с разметкой"), KeyboardButton(text="📝 Распознанный текст")],
        [KeyboardButton(text=SUBMIT_BTN), KeyboardButton(text=HISTORY_BTN)],
        [KeyboardButton(text="📄 Новый документ"), KeyboardButton(text="📘 Положение")],
    ]
    if site_url():
        rows.append([KeyboardButton(text=SITE_BTN)])
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=rows)


async def types_kb(prefix: str) -> InlineKeyboardMarkup:
    types = await api.doc_types()
    rows = [[InlineKeyboardButton(text="🔎 Определить автоматически", callback_data=f"{prefix}:auto")]] if prefix == "type" else []
    rows += [[InlineKeyboardButton(text=t["title"], callback_data=f"{prefix}:{t['key']}")] for t in types]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fields_kb(doc: dict) -> InlineKeyboardMarkup:
    rows, row = [], []
    for f in doc["result"]["fields"].values():
        if not f.get("bbox"):
            continue
        row.append(InlineKeyboardButton(text=f["label"][:30], callback_data=f"crop:{f['key']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def quick_kb(doc_id: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ Проверить комплектность", callback_data="q:check")],
        [InlineKeyboardButton(text="⚖️ Кто принимает решение?", callback_data="q:decision")],
        [InlineKeyboardButton(text="📍 Показать поле на снимке", callback_data="q:fields")],
        [InlineKeyboardButton(text="📨 Отправить в деканат", callback_data="q:submit")],
    ]
    sb = site_button("🌐 Открыть документ на сайте", f"/d/{doc_id}" if doc_id else "/")
    if sb:
        rows.append([sb])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ошибки
@router.errors()
async def on_error(event, state: FSMContext | None = None, **kwargs):
    """При любой ошибке пишем пользователю, чтобы бот не молчал."""
    exc = event.exception
    log.exception("Ошибка обработчика: %s", exc)
    msg = None
    upd = event.update
    if upd.message:
        msg = upd.message
    elif upd.callback_query and upd.callback_query.message:
        msg = upd.callback_query.message
    if msg is None:
        return True
    if isinstance(exc, api.ApiError) and exc.status == 404:
        # текущий документ удалили на сервере (например, очистили базу): сбрасываем состояние
        if state is not None:
            try:
                await state.clear()
            except Exception:  # pragma: no cover
                pass
        text = "ℹ️ Этот документ больше недоступен на сервере. Пришлите документ заново (/new)."
    elif isinstance(exc, api.ApiError):
        text = f"❌ {exc}"
    elif isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        text = "❌ Сервис распознавания сейчас недоступен (бэкенд не отвечает). Попробуйте через минуту."
    else:
        text = "❌ Не удалось обработать запрос. Попробуйте ещё раз или пришлите документ заново (/new)."
    try:
        await msg.answer(text)
    except Exception:  # pragma: no cover
        pass
    return True


# команды
def site_kb(doc_id: str | None = None) -> InlineKeyboardMarkup | None:
    """Ссылки на сайт: главная, текущий документ, кабинет."""
    if not site_url():
        return None
    rows = [[site_button("🌐 Открыть сайт", "/")]]
    if doc_id:
        rows.append([site_button("📄 Текущий документ на сайте", f"/d/{doc_id}")])
    rows.append([site_button("👤 Кабинет студента / деканата", "/cabinet")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    # у старых чатов могла остаться кнопка меню «Приложение» (Mini App) - убираем её для этого чата
    try:
        await bot.set_chat_menu_button(chat_id=m.chat.id, menu_button=MenuButtonDefault())
    except Exception:  # pragma: no cover
        pass
    await m.answer(texts.WELCOME, reply_markup=main_kb())
    kb = site_kb()
    if kb:
        await m.answer("Сайт с личным кабинетом (открывать через VPN):", reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(texts.HELP)


@router.message(Command("new"))
@router.message(F.text == "📄 Новый документ")
async def cmd_new(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Пришлите фото или файл документа (JPG, PNG, PDF). Для лучшего качества отправляйте как файл.",
                   reply_markup=main_kb())


@router.message(Command("types"))
async def cmd_types(m: Message):
    types = await api.doc_types()
    await m.answer("<b>Поддерживаемые типы</b>\n" + "\n".join(
        f"• {t['title']} — раздел {t['rules_section']} Положения, {len(t['fields'])} полей" for t in types))


@router.message(Command("site"))
@router.message(F.text == SITE_BTN)
async def cmd_site(m: Message, state: FSMContext):
    data = await state.get_data()
    kb = site_kb(data.get("doc_id"))
    if not kb:
        await m.answer("Адрес сайта не настроен: запустите scripts/tunnel_keeper.py или задайте SITE_URL в .env.")
        return
    await m.answer("Сайт «Онлайн-деканат» (открывать через VPN):", reply_markup=kb)


@router.message(Command("rules"))
@router.message(F.text == "📘 Положение")
async def cmd_rules(m: Message):
    rules = await api.rules()
    for chunk in texts.format_rules(rules):
        for part in texts.split_message(chunk):
            await m.answer(part)


async def _current(m: Message, state: FSMContext) -> dict | None:
    data = await state.get_data()
    if not data.get("doc_id"):
        await m.answer(texts.NO_DOC)
        return None
    return data


@router.message(Command("check"))
@router.message(F.text == "✅ Проверить комплектность")
async def cmd_check(m: Message, state: FSMContext):
    data = await _current(m, state)
    if not data:
        return
    qa = await api.check(data["doc_id"])
    await m.answer(texts.format_answer(qa, data["fields"]))


@router.message(Command("fields"))
@router.message(F.text == "🗂 Карточка полей")
async def cmd_fields(m: Message, state: FSMContext):
    data = await _current(m, state)
    if not data:
        return
    doc = await api.get(data["doc_id"])
    await m.answer(texts.format_document(doc), reply_markup=fields_kb(doc))


@router.message(Command("text"))
@router.message(F.text == "📝 Распознанный текст")
async def cmd_text(m: Message, state: FSMContext):
    data = await _current(m, state)
    if not data:
        return
    o = await api.ocr(data["doc_id"])
    from html import escape

    for part in texts.split_message("<b>Распознанный текст</b>\n<code>" + escape(o["ocr_text"]) + "</code>"):
        await m.answer(part)


@router.message(Command("photo"))
@router.message(F.text == "🖼 Снимок с разметкой")
async def cmd_photo(m: Message, state: FSMContext):
    data = await _current(m, state)
    if not data:
        return
    png = await api.image(data["doc_id"], "annotated")
    if png:
        await m.answer_photo(BufferedInputFile(png, "annotated.png"),
                             caption="Зелёный — поле найдено, красный — не найдено, синий — подпись/печать")
    else:
        await m.answer("Снимок недоступен.")


@router.message(Command("type"))
async def cmd_type(m: Message, state: FSMContext):
    data = await _current(m, state)
    if not data:
        return
    await m.answer("Выберите тип документа:", reply_markup=await types_kb("retype"))


# ---------- кабинет: отправка в деканат и история ----------

async def with_profile(user, call):
    """Вызывает call(profile_id); если бэкенд не узнал профиль (403), пересоздаёт его и повторяет один раз."""
    pid = await profile_id(user)
    if not pid:
        raise api.ApiError("Кабинет недоступен: бэкенд не отвечает. Попробуйте позже.")
    try:
        return await call(pid)
    except api.ApiError as exc:
        if exc.status != 403:
            raise
        pid = await profile_id(user, refresh=True)
        if not pid:
            raise
        return await call(pid)


async def _submit_current(m: Message, state: FSMContext, user) -> None:
    data = await _current(m, state)
    if not data:
        return
    doc_id = data["doc_id"]
    doc = await api.get(doc_id)
    v = (doc.get("result") or {}).get("validation") or {}
    try:
        await with_profile(user, lambda pid: api.submit(doc_id, pid))
    except api.ApiError as exc:
        await m.answer(f"ℹ️ {exc}")
        return
    warn = ""
    if v.get("status") == "missing_fields":
        labels = [f["label"] for k, f in (doc["result"]["fields"] or {}).items() if k in (v.get("missing_fields") or [])]
        warn = ("\n\n⚠️ По предварительной проверке не хватает: " + ", ".join(labels) +
                ". Деканат может вернуть документ на доработку.")
    kb = site_kb(doc_id)
    await m.answer("📨 <b>Документ отправлен в деканат.</b>\nРешение (принято, отклонено или нужно исправить) придёт "
                   "сюда сообщением; его же видно в кабинете на сайте." + warn, reply_markup=kb)


@router.message(Command("submit"))
@router.message(F.text == SUBMIT_BTN)
async def cmd_submit(m: Message, state: FSMContext):
    await _submit_current(m, state, m.from_user)


def history_kb(rows: list[dict]) -> InlineKeyboardMarkup | None:
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"hist:{d['id']}") for i, d in enumerate(rows, 1)]
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 5] for i in range(0, len(buttons), 5)])


@router.message(Command("history"))
@router.message(F.text == HISTORY_BTN)
async def cmd_history(m: Message):
    rows = await with_profile(m.from_user, lambda pid: api.list_documents(pid, limit=10))
    for part in texts.split_message(texts.format_history(rows)):
        await m.answer(part)
    kb = history_kb(rows)
    if kb:
        await m.answer("Открыть документ:", reply_markup=kb)


@router.callback_query(F.data.startswith("hist:"))
async def on_history_open(cq: CallbackQuery, state: FSMContext):
    doc_id = cq.data.split(":", 1)[1]
    await cq.answer()
    try:
        doc = await api.get(doc_id)
    except api.ApiError as exc:
        await cq.message.answer(f"❌ {exc}")
        return
    if doc.get("status") != "done" or not doc.get("result"):
        await cq.message.answer("Документ ещё обрабатывается или не был распознан.")
        return
    await state.set_state(Flow.ready)
    await state.update_data(doc_id=doc["id"], fields=doc["result"]["fields"], pending_file=None)
    await cq.message.answer(texts.format_document(doc), reply_markup=main_kb())
    await cq.message.answer("Задайте вопрос о документе или выберите действие:", reply_markup=await quick_kb(doc["id"]))


# загрузка файла
@router.message(F.photo | F.document)
async def on_file(m: Message, state: FSMContext, bot: Bot):
    if m.document:
        size = m.document.file_size or 0
        name = m.document.file_name or "document"
        mime = m.document.mime_type or ""
        if mime and not (mime.startswith("image/") or mime == "application/pdf"):
            await m.answer("Поддерживаются JPG, PNG и одностраничный PDF.")
            return
        file_id = m.document.file_id
    else:
        best = m.photo[-1]
        size, name, file_id = best.file_size or 0, "photo.jpg", best.file_id
    if size > MAX_TG_FILE:
        await m.answer("Файл больше 20 МБ — Telegram не позволяет его скачать. Сожмите или пришлите фото.")
        return
    await bot.send_chat_action(m.chat.id, ChatAction.UPLOAD_DOCUMENT)
    f = await bot.get_file(file_id)
    buf = await bot.download_file(f.file_path)
    data = buf.read()
    await state.update_data(pending_file=data, pending_name=name, pending_question=(m.caption or "").strip())
    await state.set_state(Flow.waiting_type)
    try:
        kb = await types_kb("type")
    except (api.ApiError, httpx.HTTPError) as exc:
        log.warning("doc-types недоступны: %s", exc)
        await m.answer("❌ Сервис распознавания недоступен, не могу получить список типов. Попробуйте через минуту "
                       "и отправьте документ заново.")
        await state.clear()
        return
    await m.answer("Какой это документ?", reply_markup=kb)


@router.callback_query(F.data.startswith("type:"))
async def on_type_chosen(cq: CallbackQuery, state: FSMContext, bot: Bot):
    doc_type = cq.data.split(":", 1)[1]
    data = await state.get_data()
    if not data.get("pending_file"):
        await cq.answer("Сначала пришлите файл")
        return
    await cq.answer()
    await cq.message.edit_reply_markup(reply_markup=None)
    status = await cq.message.answer("⏳ Распознаю документ…")
    await bot.send_chat_action(cq.message.chat.id, ChatAction.TYPING)
    question = data.get("pending_question", "")
    pid = await profile_id(cq.from_user)
    try:
        # грузим с async и опрашиваем статус, туннель рвет долгие запросы
        doc = await api.upload(data["pending_file"], data["pending_name"], doc_type, question,
                               user_id=str(cq.from_user.id), wait=False, profile_id=pid)
        for i in range(90):
            if doc.get("status") != "processing":
                break
            await asyncio.sleep(1.0)
            if i in (6, 15, 30):
                await status.edit_text("⏳ Распознаю документ… " + "•" * (i // 6))
            doc = await api.get(doc["id"])
    except api.ApiError as exc:
        await status.edit_text(f"❌ {exc}")
        await state.clear()
        return
    except Exception as exc:  # pragma: no cover
        log.exception("upload failed")
        await status.edit_text(f"❌ Сервис недоступен: {exc}")
        await state.clear()
        return
    if doc.get("status") == "error":
        await status.edit_text(f"❌ {doc.get('error') or 'Не удалось обработать документ'}")
        await state.clear()
        return
    if doc.get("status") != "done" or not doc.get("result"):
        await status.edit_text("❌ Обработка занимает слишком много времени. Попробуйте ещё раз позже.")
        await state.clear()
        return
    await status.delete()
    await state.set_state(Flow.ready)
    await state.update_data(doc_id=doc["id"], fields=doc["result"]["fields"], pending_file=None)
    await cq.message.answer(texts.format_document(doc), reply_markup=main_kb())
    await _warn_type_mismatch(cq.message, doc)
    if question and doc.get("questions"):
        await _send_answer(cq.message, doc["questions"][-1], doc["result"]["fields"], doc["id"])
    await cq.message.answer("Задайте вопрос о документе или выберите действие:", reply_markup=await quick_kb(doc["id"]))


async def _warn_type_mismatch(m: Message, doc: dict):
    """Если тип выбран не тот, предлагаем его сменить."""
    mm = (doc.get("result") or {}).get("type_mismatch")
    if not mm:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"🔁 Сменить тип на «{mm['detected_title']}»", callback_data=f"retype:{mm['detected']}")]])
    await m.answer("⚠️ <b>Похоже, выбран неправильный тип документа.</b>\n"
                   f"Загруженный документ больше похож на «{mm['detected_title']}», поэтому большинство полей "
                   "не найдено. Сменить тип?", reply_markup=kb)


@router.callback_query(F.data.startswith("retype:"))
async def on_retype(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("doc_id"):
        await cq.answer("Нет текущего документа")
        return
    await cq.answer()
    try:
        doc = await api.change_type(data["doc_id"], cq.data.split(":", 1)[1])
    except api.ApiError as exc:
        await cq.message.answer(f"❌ {exc}")
        return
    await state.update_data(fields=doc["result"]["fields"])
    await cq.message.answer(texts.format_document(doc), reply_markup=main_kb())


async def _send_answer(m: Message, qa: dict, fields: dict, doc_id: str):
    await m.answer(texts.format_answer(qa, fields))
    key = qa.get("field_key")
    if key and fields.get(key, {}).get("bbox"):
        png = await api.image(doc_id, "crop", key)
        if png:
            await m.answer_photo(BufferedInputFile(png, f"{key}.png"), caption=f"Поле «{fields[key]['label']}» на снимке")


@router.callback_query(F.data.startswith("q:"))
async def on_quick(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("doc_id"):
        await cq.answer("Сначала пришлите документ")
        return
    await cq.answer()
    action = cq.data.split(":", 1)[1]
    if action == "fields":
        doc = await api.get(data["doc_id"])
        await cq.message.answer("Какое поле показать?", reply_markup=fields_kb(doc))
        return
    if action == "submit":
        await _submit_current(cq.message, state, cq.from_user)
        return
    q = COMPLETENESS_Q if action == "check" else "Кто принимает окончательное решение о принятии документа?"
    qa = await api.ask(data["doc_id"], q)
    await _send_answer(cq.message, qa, data["fields"], data["doc_id"])


@router.callback_query(F.data.startswith("crop:"))
async def on_crop(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("doc_id"):
        await cq.answer("Нет документа")
        return
    key = cq.data.split(":", 1)[1]
    await cq.answer()
    png = await api.image(data["doc_id"], "crop", key)
    f = data["fields"].get(key, {})
    if png:
        val = "есть" if f.get("kind") == "mark" and f.get("found") else ("отсутствует" if f.get("kind") == "mark" else str(f.get("value")))
        await cq.message.answer_photo(BufferedInputFile(png, f"{key}.png"), caption=f"{f.get('label', key)}: {val}")
    else:
        await cq.message.answer("Для этого поля нет координат на снимке.")


# вопрос текстом
@router.message(F.text)
async def on_question(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not data.get("doc_id"):
        await m.answer(texts.NO_DOC)
        return
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        qa = await api.ask(data["doc_id"], m.text.strip())
    except api.ApiError as exc:
        await m.answer(f"❌ {exc}")
        return
    await _send_answer(m, qa, data["fields"], data["doc_id"])


# ---------- уведомления о решениях деканата ----------

NOTIFY_INTERVAL = float(os.environ.get("NOTIFY_INTERVAL", "4"))


async def notify_loop(bot: Bot):
    """Забирает из бэкенда очередь уведомлений и шлёт их студентам в Telegram."""
    api_down = False
    while True:
        try:
            items = await api.pending_notifications()
            if api_down:
                log.info("Очередь уведомлений снова доступна")
                api_down = False
        except (api.ApiError, httpx.HTTPError) as exc:
            if not api_down:
                log.warning("Очередь уведомлений недоступна: %s", exc)
                api_down = True
            items = []
        for n in items:
            doc_id = n.get("document_id")
            kb = site_kb(str(doc_id)) if doc_id else None
            error = ""
            try:
                await bot.send_message(int(n["telegram_user_id"]), n["text"], reply_markup=kb)
            except Exception as exc:  # чат заблокировал бота, неверный id и т. п.: помечаем, чтобы не слать вечно
                error = str(exc)
                log.warning("Не удалось отправить уведомление %s пользователю %s: %s", n["id"], n["telegram_user_id"], exc)
            try:
                await api.notification_sent(n["id"], error)
            except (api.ApiError, httpx.HTTPError) as exc:
                log.warning("Не удалось отметить уведомление %s: %s", n["id"], exc)
        await asyncio.sleep(NOTIFY_INTERVAL)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # иначе опрос очереди уведомлений пишет строку каждые 4 с
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Укажите BOT_TOKEN в окружении или .env")
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    # без кнопки меню: ссылку на сайт даёт кнопка «🌐 Открыть приложение» на клавиатуре и /site
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    log.info("Сайт: %s", site_url() or "не настроен")
    log.info("Бот запущен; API: %s", api.API_BASE)
    notifier = asyncio.create_task(notify_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        notifier.cancel()


if __name__ == "__main__":
    asyncio.run(main())
