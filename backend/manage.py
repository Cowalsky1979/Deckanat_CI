#!/usr/bin/env python
"""manage.py для проекта Онлайн-деканат."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dekanat.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
