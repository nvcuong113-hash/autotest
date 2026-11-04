# AutoTest — SRS-driven Web QA Platform

AutoTest converts SRS documents into traceable requirements and editable test cases, then executes browser steps with Playwright.

## MVP features

- Parse PDF, DOCX, XLSX, CSV, Markdown, TXT, YAML and JSON.
- Extract candidate requirements and retain source-file traceability.
- Generate positive, negative, boundary and authorization test drafts.
- Optional AI-assisted test-case generation.
- Edit browser steps as JSON and execute with Playwright Chromium.
- Capture failure screenshots and execution logs.
- Store projects, requirements, cases and runs in SQLite.
- Export test cases and execution results to CSV/JSON.

Generated cases are drafts. SRS alone cannot reveal actual DOM selectors or test data. Review requirements and cases, replace every manual placeholder with verified browser actions, and run only against systems you are authorized to test.

## Quick start

Python 3.10+ is recommended.

    python -m venv .venv
    # Windows: .venv\Scripts\activate
    # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium
    streamlit run app.py

Open the local URL printed by Streamlit (usually http://localhost:8501).

## Run tests

    pytest -q

## Docker

    docker build -t autotest .
    docker run --rm -p 8501:8501 -v autotest-data:/app/data autotest

Set AUTOTEST_DB to change the SQLite path. Set OPENAI_API_KEY in a secret manager or enter it for one generation request. API keys and browser credentials are not stored in SQLite.

## Browser step format

Each test case stores a JSON array of browser actions. Supported actions:

- goto: open a path on the configured Base URL.
- fill: fill an input using a verified CSS selector.
- click: click an element using a verified selector.
- select_option, check, uncheck.
- expect_visible, expect_hidden, expect_text, expect_url, assert_title.
- press, screenshot, wait_for_timeout.
- manual: placeholder that marks a case BLOCKED until replaced.

Placeholders: BASE_URL, USERNAME and PASSWORD. Explicit navigation is restricted to the configured base host. Credentials are held in Streamlit session memory only.

## Limitations

- Requirement extraction is heuristic and must be reviewed.
- AI output may be inaccurate; review before execution.
- Selectors must be verified against the target DOM.
- MVP execution is synchronous in the Streamlit process. Use an isolated worker and a production database for concurrent team-scale usage.
- Avoid destructive cases and production data without an approved plan and backups.
