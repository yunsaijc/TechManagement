#!/usr/bin/env python3
"""Prepare Project.year_norm and related indexes for faster year-window queries.

Usage:
  .venv/bin/python scripts/prepare_project_year_norm.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

URI = os.getenv("NEO4J_URI", "neo4j://192.168.0.198:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}


def run_query(session, query: str) -> None:
    session.run(query).consume()


def main() -> int:
    if not PASSWORD:
        print("[ERROR] Missing NEO4J_PASSWORD")
        return 2

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        with driver.session(database=DATABASE, **SESSION_KWARGS) as session:
            print("[STEP] Backfilling Project.year_norm in batches...")
            run_query(
                session,
                """
                CALL {
                  MATCH (p:Project)
                  WITH p,
                       coalesce(
                         toInteger(p.year_norm),
                         toInteger(p.year),
                         toInteger(p.startYear),
                         toInteger(substring(toString(p.period), 0, 4))
                       ) AS y
                  WHERE y IS NOT NULL AND (p.year_norm IS NULL OR p.year_norm <> y)
                  SET p.year_norm = y
                } IN TRANSACTIONS OF 50000 ROWS
                """,
            )

            print("[STEP] Creating indexes (if not exists)...")
            run_query(
                session,
                "CREATE RANGE INDEX project_year_norm_idx IF NOT EXISTS FOR (p:Project) ON (p.year_norm)",
            )
            run_query(
                session,
                "CREATE RANGE INDEX project_guide_year_norm_idx IF NOT EXISTS FOR (p:Project) ON (p.guideName, p.year_norm)",
            )
            run_query(
                session,
                "CREATE RANGE INDEX project_department_year_norm_idx IF NOT EXISTS FOR (p:Project) ON (p.department, p.year_norm)",
            )
            run_query(
                session,
                "CREATE RANGE INDEX project_office_year_norm_idx IF NOT EXISTS FOR (p:Project) ON (p.office, p.year_norm)",
            )

            counts = session.run(
                """
                MATCH (p:Project)
                RETURN
                  count(p) AS total,
                  sum(CASE WHEN p.year_norm IS NOT NULL THEN 1 ELSE 0 END) AS yearNormFilled
                """
            ).single()

            print("[OK] year_norm preparation finished")
            print(f"[INFO] Project total: {int(counts['total'])}")
            print(f"[INFO] Project year_norm filled: {int(counts['yearNormFilled'])}")

        return 0
    except Exception as exc:
        print(f"[ERROR] Failed: {exc}")
        return 1
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
