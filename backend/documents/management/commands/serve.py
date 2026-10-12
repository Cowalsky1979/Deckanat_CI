"""Запуск сайта и API одной командой:  python manage.py serve [--port 8000] [--threads 4]

Внутри тот же waitress, что и в Docker, но в консоли печатаются адреса, которые можно открыть.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Запустить сайт и API (waitress)"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 - доступ и с других устройств в сети")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--threads", type=int, default=4)

    def handle(self, *args, **opts):
        from waitress import serve

        from dekanat.wsgi import application

        host, port = opts["host"], opts["port"]
        base = f"http://localhost:{port}"
        self.stdout.write(self.style.SUCCESS("Онлайн-деканат запущен"))
        self.stdout.write(f"  Сайт:            {base}")
        self.stdout.write(f"  Кабинет:         {base}/cabinet")
        self.stdout.write(f"  Документация API: {base}/api/docs/")
        if host == "0.0.0.0":
            self.stdout.write("  Доступ с других устройств в сети: по IP этого компьютера на том же порту")
        self.stdout.write("Первые секунды прогревается OCR. Остановить: Ctrl+C")
        self.stdout.flush()  # чтобы адреса были видны сразу и при выводе в файл/другой процесс
        try:
            serve(application, host=host, port=port, threads=opts["threads"], _quiet=True)
        except KeyboardInterrupt:
            self.stdout.write("Остановлено")
