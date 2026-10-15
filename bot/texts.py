"""Тексты сообщений бота и их форматирование (HTML)."""
from __future__ import annotations

from html import escape

WELCOME = (
    "👋 <b>Онлайн-деканат</b> — цифровой секретарь.\n\n"
    "Пришлите <b>фото или файл</b> справки об обучении, заявления на академический отпуск или справки о практике "
    "(JPG, PNG, одностраничный PDF). Подпись к фото — ваш вопрос.\n\n"
    "Я распознаю текст, заполню карточку полей, проверю комплектность по Положению и отвечу со ссылками на "
    "поля документа и пункты Положения.\n\n"
    "⚖️ Окончательное решение о принятии документа принимает сотрудник деканата (п. 1.3)."
)

HELP = (
    "<b>Команды</b>\n"
    "/new — загрузить новый документ\n"
    "/check — проверить комплектность текущего документа\n"
    "/fields — карточка полей\n"
    "/text — распознанный текст\n"
    "/photo — снимок с разметкой найденных полей\n"
    "/type — сменить тип документа\n"
    "/rules — Положение\n"
    "/types — поддерживаемые типы документов\n"
    "/submit — отправить текущий документ в деканат (решение придёт сюда сообщением)\n"
    "/history — мои документы и решения деканата\n"
    "/site — ссылка на сайт (кабинет студента и деканата), то же — кнопка «🌐 Открыть приложение»\n\n"
    "После загрузки документа просто напишите вопрос, например: «Какова дата выдачи?», "
    "«Хватит ли справки для перевода?», «Есть ли печать?»."
)

NO_DOC = "Сначала пришлите документ (фото или файл). /help — подсказка."


LOW_CONF = 0.75

# почему поле не найдено (missing_reason из ядра)
MISSING_REASON = {
    "label_not_found": "метка не распознана на снимке",
    "empty_value": "в документе не заполнено",
    "anchor_not_found": "надпись для отметки не найдена",
    "mark_not_detected": "рядом с надписью нет отметки",
}

REVIEW_STATUS = {
    "pending": "⏳ на рассмотрении",
    "accepted": "✅ принято",
    "rejected": "❌ отклонено",
    "needs_fix": "✏️ нужно исправить",
}


def field_line(f: dict) -> str:
    reason = MISSING_REASON.get(f.get("missing_reason") or "", "")
    why = f" <i>({reason})</i>" if reason else ""
    if f["kind"] == "mark":
        return f"{'✅' if f['found'] else '❌'} {escape(f['label'])}: {'есть' if f['found'] else 'отсутствует' + why}"
    if not f["found"]:
        return f"⚠️ {escape(f['label'])}: <i>не найдено</i>{why}"
    val = escape(str(f["value"]))
    if f.get("source") == "manual":
        ocr = escape(str(f.get("ocr_value") or "не найдено"))
        return f"✏️ {escape(f['label'])}: <code>{val}</code> <i>(исправлено вручную, OCR: {ocr})</i>"
    if (f.get("confidence") or 0) < LOW_CONF:
        return f"❓ {escape(f['label'])}: <code>{val}</code> <i>(низкая уверенность OCR)</i>"
    return f"✅ {escape(f['label'])}: <code>{val}</code>"


def review_line(review: dict | None) -> str:
    if not review:
        return "📨 В деканат не отправлен"
    s = REVIEW_STATUS.get(review.get("status"), review.get("status", ""))
    line = f"📨 Деканат: {s}"
    if review.get("comment"):
        line += f"\n💬 {escape(review['comment'])}"
    return line


def format_history(rows: list[dict]) -> str:
    """Список документов студента для /history."""
    if not rows:
        return "Документов пока нет. Пришлите фото или файл, чтобы начать."
    lines = ["<b>Мои документы</b> (последние сначала)", ""]
    for i, d in enumerate(rows, 1):
        date = (d.get("created_at") or "")[:16].replace("T", " ")
        v = d.get("validation_status")
        check = "✅ в порядке" if v == "document_ok" else (f"⚠️ не хватает полей: {d.get('missing_count', 0)}" if v else "⏳ обрабатывается")
        rev = " · исправленная версия" if d.get("parent") else ""
        lines.append(f"<b>{i}. {escape(d.get('doc_type_title') or d.get('doc_type') or 'Документ')}</b> · {date}{rev}")
        lines.append(f"   {check}")
        r = d.get("review")
        if r:
            s = REVIEW_STATUS.get(r.get("status"), r.get("status", ""))
            lines.append(f"   📨 {s}" + (f": {escape(r['comment'])}" if r.get("comment") else ""))
        lines.append("")
    lines.append("Нажмите на номер документа, чтобы открыть его и задать вопросы.")
    return "\n".join(lines)


def format_document(doc: dict) -> str:
    r = doc["result"]
    conf = f" (уверенность {r['type_confidence'] * 100:.0f}%)" if r.get("type_auto") else ""
    lines = [f"📄 <b>{escape(r['doc_type_title'])}</b>{conf}", ""]
    if (r.get("quality") or {}).get("readability", {}).get("low_quality"):
        lines += ["🚫 <b>Снимок низкого качества</b> — текст мелкий или нечёткий, результат ненадёжен. "
                  "Переснимите документ ближе, ровно и при хорошем освещении (или пришлите скан/PDF).", ""]
    lines += [field_line(f) for f in r["fields"].values()]
    v = r["validation"]
    lines += ["", ("✅ " if v["status"] == "document_ok" else "⚠️ ") + "<b>Предварительная проверка</b>", escape(v["message"])]
    if doc.get("review"):
        lines += ["", review_line(doc["review"])]
    extra = [w for w in (r.get("warnings") or []) if not w.startswith(("Снимок низкого качества", "Похоже, выбран"))]
    if extra:
        lines += ["", *("ℹ️ " + escape(w) for w in extra)]
    return "\n".join(lines)


def format_sources(sources: list[str], fields: dict) -> str:
    out = []
    for s in sources:
        if s.startswith("field:"):
            key = s[6:]
            out.append(f"поле «{escape(fields.get(key, {}).get('label', key))}»")
        else:
            out.append(f"п. {s.replace('rule:', '')} Положения")
    return "; ".join(out) if out else "нет (ответа нет в документе и Положении)"


def format_answer(qa: dict, fields: dict) -> str:
    if not qa["answerable"]:
        head = "ℹ️ <b>Нет информации</b>"
    elif qa["value"] == "document_ok":
        head = "✅ <b>Документ содержит обязательные сведения</b>"
    elif qa["value"] == "missing_fields":
        head = "⚠️ <b>Не хватает обязательных сведений</b>"
    else:
        head = "💬 <b>Ответ</b>"
    return f"{head}\n{escape(qa['answer'])}\n\n<i>Источники: {format_sources(qa['sources'], fields)}</i>"


def format_rules(rules: dict, section: str | None = None) -> list[str]:
    chunks = []
    for s in rules["sections"]:
        if section and s["id"] != section:
            continue
        text = f"<b>{s['id']}. {escape(s['title'])}</b>\n" + "\n".join(f"<b>{r['id']}.</b> {escape(r['text'])}" for r in s["rules"])
        chunks.append(text)
    return chunks


def split_message(text: str, limit: int = 4000) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts or [text[:limit]]
