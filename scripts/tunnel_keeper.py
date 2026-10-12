#!/usr/bin/env python
"""Держит туннель к сайту и записывает публичный адрес в .env (SITE_URL) и runtime/site_url.txt.
Бот читает файл при каждом нажатии кнопки «Сайт», поэтому перезапускать его при смене адреса не нужно.

  python scripts/tunnel_keeper.py [--port 8000] [--provider serveo|cloudflared|localhost.run] [--name dekanat-ci]

Провайдер и имя берутся из .env (TUNNEL_PROVIDER, TUNNEL_NAME). serveo с зарегистрированным именем даёт
постоянный адрес; localhost.run показывал «no tunnel»; cloudflared требует, чтобы сам ПК выходил через VPN
(без него не резолвится argotunnel.com). Пользователи открывают сайт через VPN - с телефона и с ПК.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
URL_FILE = ROOT / "runtime" / "site_url.txt"
PROVIDERS = {
    # имя: (аргументы ssh, регулярка для адреса)
    "localhost.run": (["-R", "80:127.0.0.1:{port}", "nokey@localhost.run"], r"https://[a-z0-9]+\.lhr\.life"),
    # serveo без лимита по времени, но один раз показывает страницу Continue to Site
    "serveo": (["-R", "80:127.0.0.1:{port}", "serveo.net"], r"https://[a-z0-9-]+\.serveousercontent\.com"),
    # cloudflared - не ssh, отдельная ветка в run()
    "cloudflared": ([], r"https://[a-z0-9-]+\.trycloudflare\.com"),
}
CLOUDFLARED = (os.environ.get("CLOUDFLARED") or shutil.which("cloudflared")
               or r"C:\Program Files (x86)\cloudflared\cloudflared.exe")


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


def publish(url: str) -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(url, encoding="utf-8")
    write_env("SITE_URL", url)
    print(f"[keeper] адрес сайта: {url}", flush=True)


def run(port: int, provider: str = "serveo", name: str = "") -> None:
    args, pattern = PROVIDERS[provider]
    if name and provider == "serveo":
        # постоянное имя, нужен ssh-ключ на console.serveo.net
        args = [a.replace("80:127.0.0.1", f"{name}:80:127.0.0.1") for a in args]
    url_re = re.compile(pattern)
    if provider == "cloudflared":
        if not Path(CLOUDFLARED).exists() and not shutil.which(CLOUDFLARED):
            sys.exit(f"[keeper] cloudflared не найден: {CLOUDFLARED} (укажите путь в переменной CLOUDFLARED)")
        cmd = [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"]
    else:
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
               "-o", "ExitOnForwardFailure=yes", *[a.format(port=port) for a in args]]
    current = ""
    while True:
        print(f"[keeper] запускаю туннель ({provider})...", flush=True)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="ignore", bufsize=1)
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                m = url_re.search(line)
                if m and m.group(0) != current:
                    current = m.group(0)
                    publish(current)
        except KeyboardInterrupt:
            proc.terminate()
            return
        code = proc.wait()
        print(f"[keeper] туннель завершился (код {code}), перезапуск через 5 с", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--provider", choices=list(PROVIDERS),
                   default=os.environ.get("TUNNEL_PROVIDER") or read_env("TUNNEL_PROVIDER") or "serveo")
    p.add_argument("--name", default=os.environ.get("TUNNEL_NAME") or read_env("TUNNEL_NAME"),
                   help="постоянный поддомен serveo (после регистрации ключа)")
    a = p.parse_args()
    try:
        run(a.port, a.provider, a.name)
    except KeyboardInterrupt:
        sys.exit(0)
