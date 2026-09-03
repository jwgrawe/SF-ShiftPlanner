#!/usr/bin/env python3
"""Rebuild the demo roster and demo plan (see app/demo.py).

Usage:  python scripts/make_demo_data.py   (after python -m app.importer)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, demo  # noqa: E402


def main() -> None:
    conn = db.get_conn()
    db.init_schema(conn)
    demo.build(conn)
    conn.close()


if __name__ == "__main__":
    main()
