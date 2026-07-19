#!/usr/bin/env python3
"""إنشاء قاعدة البيانات المحلية (SQLite) وجميع الجداول"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database import DatabaseManager


def main():
    db = DatabaseManager()
    db.create_tables()
    path = db.db_file_path
    if path and path.exists():
        print(f"OK — قاعدة البيانات جاهزة: {path}")
        print(f"     حجم الملف: {path.stat().st_size} bytes")
    else:
        print("OK — تم إنشاء الجداول")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
