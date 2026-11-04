from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

DB_PATH = os.getenv("AUTOTEST_DB", "data/autotest.sqlite3")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
          description TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requirements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          req_key TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
          source TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, req_key)
        );
        CREATE TABLE IF NOT EXISTS test_cases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          requirement_id INTEGER REFERENCES requirements(id) ON DELETE SET NULL,
          case_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
          test_type TEXT NOT NULL DEFAULT 'Functional', priority TEXT NOT NULL DEFAULT 'Medium',
          preconditions TEXT DEFAULT '', steps_json TEXT NOT NULL DEFAULT '[]',
          expected_result TEXT DEFAULT '', source_ref TEXT DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS test_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          base_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'RUNNING',
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS test_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
          case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
          status TEXT NOT NULL, message TEXT DEFAULT '', screenshot_path TEXT DEFAULT '',
          duration_seconds REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_req_project ON requirements(project_id);
        CREATE INDEX IF NOT EXISTS idx_case_project ON test_cases(project_id);
        CREATE INDEX IF NOT EXISTS idx_result_run ON test_results(run_id);
        """)
        # Lightweight migration for SQLite databases created by earlier AutoTest versions.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(test_cases)")}
        if "source_ref" not in columns:
            conn.execute("ALTER TABLE test_cases ADD COLUMN source_ref TEXT DEFAULT ''")


def create_project(name: str, description: str = "", db_path: str | None = None) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Project name is required.")
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO projects(name,description) VALUES (?,?)", (name, description.strip()))
        row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        return int(row["id"])


def list_projects(db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        return [dict(x) for x in conn.execute("SELECT * FROM projects ORDER BY name")]


def save_requirements(project_id: int, items: list[dict[str, Any]], db_path: str | None = None) -> int:
    saved = 0
    with connect(db_path) as conn:
        for item in items:
            key, title, desc = (str(item.get(k) or "").strip() for k in ("req_key", "title", "description"))
            if not key or not title or not desc:
                continue
            conn.execute("""INSERT INTO requirements(project_id,req_key,title,description,source)
                VALUES (?,?,?,?,?) ON CONFLICT(project_id,req_key) DO UPDATE SET
                title=excluded.title,description=excluded.description,source=excluded.source""",
                (project_id, key, title, desc, str(item.get("source") or "")))
            saved += 1
    return saved


def list_requirements(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM requirements WHERE project_id=? ORDER BY req_key", (project_id,))]


def add_test_cases(project_id: int, cases: list[dict[str, Any]], db_path: str | None = None) -> int:
    saved = 0
    with connect(db_path) as conn:
        req_ids = {x["req_key"]: x["id"] for x in conn.execute(
            "SELECT id,req_key FROM requirements WHERE project_id=?", (project_id,))}
        for case in cases:
            title = str(case.get("title") or "").strip()
            if not title:
                continue
            key = str(case.get("case_key") or f"TC-{uuid.uuid4().hex[:8].upper()}")
            # Case keys are globally unique in the current SQLite schema. Prefix a
            # built-in suite key when the same catalogue is imported into another project.
            collision = conn.execute("SELECT project_id FROM test_cases WHERE case_key=?", (key,)).fetchone()
            if collision and int(collision["project_id"]) != project_id:
                key = f"P{project_id}-{key}"
            steps = case.get("steps", [])
            steps_json = steps if isinstance(steps, str) else __import__("json").dumps(steps, ensure_ascii=False)
            cur = conn.execute("""INSERT OR IGNORE INTO test_cases
                (project_id,requirement_id,case_key,title,test_type,priority,preconditions,steps_json,expected_result,source_ref)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (project_id, req_ids.get(str(case.get("req_key") or "")), key, title,
                 str(case.get("test_type") or "Functional"), str(case.get("priority") or "Medium"),
                 str(case.get("preconditions") or ""), steps_json, str(case.get("expected_result") or ""), str(case.get("source_ref") or "")))
            saved += int(cur.rowcount > 0)
    return saved


def list_test_cases(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        return [dict(x) for x in conn.execute("""SELECT tc.*,r.req_key FROM test_cases tc
            LEFT JOIN requirements r ON r.id=tc.requirement_id
            WHERE tc.project_id=? ORDER BY tc.created_at DESC,tc.case_key""", (project_id,))]


def update_test_case(case_id: int, fields: dict[str, Any], db_path: str | None = None) -> None:
    allowed = {"title", "test_type", "priority", "preconditions", "steps_json", "expected_result", "source_ref", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = [f"{k}=?" for k in updates]
    vals = list(updates.values())
    cols.append("updated_at=CURRENT_TIMESTAMP")
    with connect(db_path) as conn:
        conn.execute(f"UPDATE test_cases SET {','.join(cols)} WHERE id=?", (*vals, case_id))


def create_run(project_id: int, base_url: str, db_path: str | None = None) -> int:
    with connect(db_path) as conn:
        cur = conn.execute("INSERT INTO test_runs(project_id,base_url) VALUES (?,?)", (project_id, base_url))
        return int(cur.lastrowid)


def save_result(run_id: int, case_id: int, status: str, message: str,
                screenshot_path: str = "", duration_seconds: float = 0, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("""INSERT INTO test_results(run_id,case_id,status,message,screenshot_path,duration_seconds)
            VALUES (?,?,?,?,?,?)""", (run_id, case_id, status, message, screenshot_path, duration_seconds))


def finish_run(run_id: int, status: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE test_runs SET status=?,finished_at=CURRENT_TIMESTAMP WHERE id=?", (status, run_id))


def list_runs(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM test_runs WHERE project_id=? ORDER BY id DESC", (project_id,))]


def list_results(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        return [dict(x) for x in conn.execute("""SELECT tr.*,tc.case_key,tc.title AS case_title,ru.base_url
            FROM test_results tr JOIN test_runs ru ON ru.id=tr.run_id
            JOIN test_cases tc ON tc.id=tr.case_id WHERE ru.project_id=? ORDER BY tr.id DESC""", (project_id,))]
