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
                           MenuButtonWebApp, Message, ReplyKeyboardMarkup, WebAppInfo)
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from bot import api_client as api  # noqa: E402
from bot import texts  # noqa: E402

log = logging.getLogger("bot")
router = Router()

MAX_TG_FILE = 20 * 1024 * 1024
# адрес Mini App меняется при переподключении туннеля, поэтому читаем его каждый раз:
# сначала из файла от tunnel_keeper.py, потом из WEBAPP_URL
_URL_FILE = Path(os.environ.get("WEBAPP_URL_FILE", Path(__file__).resolve().parents[1] / "runtime" / "webapp_url.txt"))


def webapp_url() -> str:
    try:
        if _URL_FILE.exists():
            u = _URL_FILE.read_text(encoding="utf-8").strip()
            if u.startswith("https://"):
                return u.rstrip("/")
    except OSError:
        pass
    return os.environ.get("WEBAPP_URL", "").rstrip("/")


WEBAPP_URL = webapp_url()  # для лога при старте


def webapp_button(text: str = "🌐 Открыть приложение", path: str = "/") -> InlineKeyboardButton | None:
    url = webapp_url()
    if not url:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{url}{path}"))
COMPLETENESS_Q = "Содержит ли документ все обязательные сведения по Положению?"


class Flow(StatesGroup):
    waiting_type = State()
    ready = State()


def main_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="✅ Проверить комплектность"), KeyboardButton(text="🗂 Карточка полей")],
        [KeyboardButton(text="🖼 Снимок с разметкой"), KeyboardButton(text="📝 Распознанный текст")],
        [KeyboardButton(text="📄 Новый документ"), KeyboardButton(text="📘 Положение")],
    ]
    url = webapp_url()
    if url:
        rows.append([KeyboardButton(text="🌐 Открыть приложение", web_app=WebAppInfo(url=f"{url}/"))])
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
    ]
    wb = webapp_button("🌐 Открыть документ в приложении", f"/d/{doc_id}" if doc_id else "/")
    if wb:
        rows.append([wb])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ошибки
@router.errors()
async def on_error(event, *args, **kwargs):
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
    if isinstance(exc, api.ApiError):
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
@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(texts.WELCOME, reply_markup=main_kb())


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


@router.message(Command("app"))
async def cmd_app(m: Message, state: FSMContext):
    if not webapp_url():
        await m.answer("Веб-приложение не настроено: запустите scripts/tunnel_keeper.py или задайте WEBAPP_URL в .env.")
        return
    data = await state.get_data()
    path = f"/d/{data['doc_id']}" if data.get("doc_id") else "/"
    text = "Открыть текущий документ в приложении:" if data.get("doc_id") else "Открыть веб-приложение «Онлайн-деканат»:"
    await m.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[webapp_button("🌐 Открыть приложение", path)]]))


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
    try:
        # грузим с async и опрашиваем статус, туннель рвет долгие запросы
        doc = await api.upload(data["pending_file"], data["pending_name"], doc_type, question,
                               user_id=str(cq.from_user.id), wait=False)
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


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Укажите BOT_TOKEN в окружении или .env")
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    url = webapp_url()
    if url:
        # кнопка меню для Mini App, tunnel_keeper обновляет её при смене адреса
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Приложение", web_app=WebAppInfo(url=f"{url}/")))
        log.info("Mini App: %s", url)
    else:
        from aiogram.types import MenuButtonDefault

        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    log.info("Бот запущен; API: %s", api.API_BASE)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
