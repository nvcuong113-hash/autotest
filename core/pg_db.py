from __future__ import annotations

import json
import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL chưa được cấu hình.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)


def init_db(db_path: str | None = None) -> None:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    statements = [
        """
        CREATE TABLE IF NOT EXISTS projects (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          description TEXT DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS requirements (
          id BIGSERIAL PRIMARY KEY,
          project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          req_key TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT NOT NULL,
          source TEXT DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, req_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS test_cases (
          id BIGSERIAL PRIMARY KEY,
          project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          requirement_id BIGINT REFERENCES requirements(id) ON DELETE SET NULL,
          case_key TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          test_type TEXT NOT NULL DEFAULT 'Functional',
          priority TEXT NOT NULL DEFAULT 'Medium',
          preconditions TEXT DEFAULT '',
          steps_json TEXT NOT NULL DEFAULT '[]',
          expected_result TEXT DEFAULT '',
          source_ref TEXT DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS test_runs (
          id BIGSERIAL PRIMARY KEY,
          project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          base_url TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'RUNNING',
          started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          finished_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS test_results (
          id BIGSERIAL PRIMARY KEY,
          run_id BIGINT NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
          case_id BIGINT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
          status TEXT NOT NULL,
          message TEXT DEFAULT '',
          screenshot_path TEXT DEFAULT '',
          duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_req_project ON requirements(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_case_project ON test_cases(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_result_run ON test_results(run_id)",
        "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS source_ref TEXT DEFAULT ''",
    ]
    with connect() as conn:
        for statement in statements:
            conn.execute(statement)


def create_project(name: str, description: str = "", db_path: str | None = None) -> int:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    name = name.strip()
    if not name:
        raise ValueError("Tên dự án không được để trống.")
    with connect() as conn:
        conn.execute(
            "INSERT INTO projects(name,description) VALUES (%s,%s) ON CONFLICT(name) DO NOTHING",
            (name, description.strip()),
        )
        row = conn.execute("SELECT id FROM projects WHERE name=%s", (name,)).fetchone()
        if not row:
            raise RuntimeError("Không thể tạo hoặc đọc lại dự án.")
        return int(row["id"])


def list_projects(db_path: str | None = None) -> list[dict[str, Any]]:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        return list(conn.execute("SELECT * FROM projects ORDER BY name").fetchall())


def save_requirements(project_id: int, items: list[dict[str, Any]], db_path: str | None = None) -> int:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    saved = 0
    with connect() as conn:
        for item in items:
            key, title, desc = (
                str(item.get(k) or "").strip()
                for k in ("req_key", "title", "description")
            )
            if not key or not title or not desc:
                continue
            conn.execute(
                """
                INSERT INTO requirements(project_id,req_key,title,description,source)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(project_id,req_key) DO UPDATE SET
                  title=EXCLUDED.title,
                  description=EXCLUDED.description,
                  source=EXCLUDED.source
                """,
                (project_id, key, title, desc, str(item.get("source") or "")),
            )
            saved += 1
    return saved


def list_requirements(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        return list(conn.execute(
            "SELECT * FROM requirements WHERE project_id=%s ORDER BY req_key",
            (project_id,),
        ).fetchall())


def add_test_cases(project_id: int, cases: list[dict[str, Any]], db_path: str | None = None) -> int:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    saved = 0
    with connect() as conn:
        req_ids = {
            row["req_key"]: row["id"]
            for row in conn.execute(
                "SELECT id,req_key FROM requirements WHERE project_id=%s",
                (project_id,),
            ).fetchall()
        }
        for case in cases:
            title = str(case.get("title") or "").strip()
            if not title:
                continue
            key = str(case.get("case_key") or f"TC-{uuid.uuid4().hex[:8].upper()}")
            collision = conn.execute(
                "SELECT project_id FROM test_cases WHERE case_key=%s",
                (key,),
            ).fetchone()
            if collision and int(collision["project_id"]) != project_id:
                key = f"P{project_id}-{key}"
            steps = case.get("steps", [])
            steps_json = steps if isinstance(steps, str) else json.dumps(steps, ensure_ascii=False)
            cur = conn.execute(
                """
                INSERT INTO test_cases
                  (project_id,requirement_id,case_key,title,test_type,priority,
                   preconditions,steps_json,expected_result,source_ref)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(case_key) DO NOTHING
                """,
                (
                    project_id,
                    req_ids.get(str(case.get("req_key") or "")),
                    key,
                    title,
                    str(case.get("test_type") or "Functional"),
                    str(case.get("priority") or "Medium"),
                    str(case.get("preconditions") or ""),
                    steps_json,
                    str(case.get("expected_result") or ""),
                    str(case.get("source_ref") or ""),
                ),
            )
            saved += int(cur.rowcount > 0)
    return saved


def list_test_cases(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        return list(conn.execute(
            """
            SELECT tc.*,r.req_key FROM test_cases tc
            LEFT JOIN requirements r ON r.id=tc.requirement_id
            WHERE tc.project_id=%s
            ORDER BY tc.created_at DESC,tc.case_key
            """,
            (project_id,),
        ).fetchall())


def update_test_case(case_id: int, fields: dict[str, Any], db_path: str | None = None) -> None:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    allowed = {
        "title", "test_type", "priority", "preconditions", "steps_json",
        "expected_result", "source_ref", "enabled",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    columns = [f"{key}=%s" for key in updates]
    values = list(updates.values())
    columns.append("updated_at=CURRENT_TIMESTAMP")
    with connect() as conn:
        conn.execute(
            f"UPDATE test_cases SET {','.join(columns)} WHERE id=%s",
            (*values, case_id),
        )


def create_run(project_id: int, base_url: str, db_path: str | None = None) -> int:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO test_runs(project_id,base_url) VALUES (%s,%s) RETURNING id",
            (project_id, base_url),
        ).fetchone()
        return int(row["id"])


def save_result(
    run_id: int,
    case_id: int,
    status: str,
    message: str,
    screenshot_path: str = "",
    duration_seconds: float = 0,
    db_path: str | None = None,
) -> None:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO test_results
              (run_id,case_id,status,message,screenshot_path,duration_seconds)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (run_id, case_id, status, message, screenshot_path, duration_seconds),
        )


def finish_run(run_id: int, status: str, db_path: str | None = None) -> None:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        conn.execute(
            "UPDATE test_runs SET status=%s,finished_at=CURRENT_TIMESTAMP WHERE id=%s",
            (status, run_id),
        )


def list_runs(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        return list(conn.execute(
            "SELECT * FROM test_runs WHERE project_id=%s ORDER BY id DESC",
            (project_id,),
        ).fetchall())


def list_results(project_id: int, db_path: str | None = None) -> list[dict[str, Any]]:
    if db_path:
        raise ValueError("Không dùng db_path khi cấu hình PostgreSQL.")
    with connect() as conn:
        return list(conn.execute(
            """
            SELECT tr.*,tc.case_key,tc.title AS case_title,ru.base_url
            FROM test_results tr
            JOIN test_runs ru ON ru.id=tr.run_id
            JOIN test_cases tc ON tc.id=tr.case_id
            WHERE ru.project_id=%s ORDER BY tr.id DESC
            """,
            (project_id,),
        ).fetchall())
