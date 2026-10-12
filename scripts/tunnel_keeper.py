#!/usr/bin/env python
"""Держит ssh-туннель для Mini App и обновляет адрес в .env, runtime/webapp_url.txt и в боте.

  python scripts/tunnel_keeper.py [--port 8000]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
URL_FILE = ROOT / "runtime" / "webapp_url.txt"
PROVIDERS = {
    # имя: (аргументы ssh, регулярка для адреса)
    "localhost.run": (["-R", "80:127.0.0.1:{port}", "nokey@localhost.run"], r"https://[a-z0-9]+\.lhr\.life"),
    # serveo без лимита по времени, но один раз показывает страницу Continue to Site
    "serveo": (["-R", "80:127.0.0.1:{port}", "serveo.net"], r"https://[a-z0-9-]+\.serveousercontent\.com"),
}


def read_env(key: str) -> str:
    if not ENV.exists():
        return ""
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return os.environ.get(key, "")


def write_env(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, done = [], False
    for line in lines:
        if line.startswith(key + "="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def set_menu_button(url: str) -> None:
    token = read_env("BOT_TOKEN")
    if not token:
        return
    body = json.dumps({"menu_button": {"type": "web_app", "text": "Приложение", "web_app": {"url": url + "/"}}},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/setChatMenuButton", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        print(f"[keeper] кнопка меню бота -> {url}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[keeper] не удалось обновить кнопку меню: {exc}", flush=True)


def known_chats() -> list[int]:
    """Id пользователей бота из базы бэкенда."""
    db = ROOT / "backend" / "db.sqlite3"
    if not db.exists():
        return []
    import sqlite3

    try:
        rows = sqlite3.connect(db).execute(
            "select distinct telegram_user_id from documents_uploadeddocument where telegram_user_id != ''").fetchall()
        return [int(r[0]) for r in rows if str(r[0]).isdigit() and int(r[0]) > 1000]
    except Exception:  # noqa: BLE001
        return []


def notify_chats(url: str, previous: str) -> None:
    """Шлем новую клавиатуру, в старой кнопка ведет на старый адрес."""
    token = read_env("BOT_TOKEN")
    if not token:
        return
    keyboard = {
        "resize_keyboard": True,
        "keyboard": [
            [{"text": "✅ Проверить комплектность"}, {"text": "🗂 Карточка полей"}],
            [{"text": "🖼 Снимок с разметкой"}, {"text": "📝 Распознанный текст"}],
            [{"text": "📄 Новый документ"}, {"text": "📘 Положение"}],
            [{"text": "🌐 Открыть приложение", "web_app": {"url": url + "/"}}],
        ],
    }
    text = ("🔄 Адрес веб-приложения обновился. Кнопка «🌐 Открыть приложение» и меню «Приложение» уже ведут на новый адрес."
            if previous else "🌐 Веб-приложение доступно: кнопка «Открыть приложение» внизу или меню «Приложение».")
    for chat_id in known_chats():
        body = json.dumps({"chat_id": chat_id, "text": text, "reply_markup": keyboard,
                           "disable_notification": True}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
            print(f"[keeper] клавиатура обновлена в чате {chat_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] чат {chat_id}: {exc}", flush=True)


def publish(url: str, previous: str = "") -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(url, encoding="utf-8")
    write_env("WEBAPP_URL", url)
    print(f"[keeper] Mini App URL: {url}", flush=True)
    set_menu_button(url)
    notify_chats(url, previous)


def run(port: int, provider: str = "localhost.run", name: str = "") -> None:
    args, pattern = PROVIDERS[provider]
    if name and provider == "serveo":
        # постоянное имя, нужен ssh-ключ на console.serveo.net
        args = [a.replace("80:127.0.0.1", f"{name}:80:127.0.0.1") for a in args]
    url_re = re.compile(pattern)
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
           "-o", "ExitOnForwardFailure=yes", *[a.format(port=port) for a in args]]
    current = ""
    while True:
        print("[keeper] запускаю ssh-туннель...", flush=True)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="ignore", bufsize=1)
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                m = url_re.search(line)
                if m and m.group(0) != current:
                    previous, current = current, m.group(0)
                    publish(current, previous or read_env("WEBAPP_URL_PREV"))
        except KeyboardInterrupt:
            proc.terminate()
            return
        code = proc.wait()
        print(f"[keeper] туннель завершился (код {code}), перезапуск через 5 с", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--provider", choices=list(PROVIDERS), default=os.environ.get("TUNNEL_PROVIDER", "localhost.run"))
    p.add_argument("--name", default=os.environ.get("TUNNEL_NAME", ""), help="постоянный поддомен serveo (после регистрации ключа)")
    a = p.parse_args()
    try:
        run(a.port, a.provider, a.name)
    except KeyboardInterrupt:
        sys.exit(0)
