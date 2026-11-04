# AutoTest — SRS-driven Web QA Platform

AutoTest converts SRS documents into traceable requirements and editable test cases, then executes browser steps with Playwright.

## MVP

- Parse PDF, DOCX, XLSX, CSV, Markdown, TXT, YAML and JSON.
- Extract candidate requirements and retain source-file traceability.
- Generate positive, negative, boundary and authorization test drafts.
- Optional AI-assisted test-case generation.
- Edit test steps as JSON and execute in Chromium.
- Capture failure screenshots and execution logs.
- Store projects, requirements, cases and runs in SQLite.
- Export test cases and results to CSV/JSON.

> Generated cases are drafts. SRS alone cannot reveal real DOM selectors or test data. Review each requirement and case, replace every \`manual\` step with verified browser actions, and run only against systems you are authorized to test.

## Quick start

Python 3.10+:

\`\`\`bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
\`\`\`

## Tests

\`\`\`bash
pytest -q
\`\`\`

## Docker

\`\`\`bash
docker build -t autotest .
docker run --rm -p 8501:8501 -v autotest-data:/app/data autotest
\`\`\`

Set \`AUTOTEST_DB\` to change the SQLite path. Set \`OPENAI_API_KEY\` in your secret manager or enter it for one generation request. Keys and browser credentials are not stored in SQLite.

## Browser step format

Steps are a JSON array. Supported actions:

- \`{"action":"goto","url":"${BASE_URL}/login"}\`
- \`{"action":"fill","selector":"input[name='email']","value":"${USERNAME}"}\`
- \`{"action":"fill","selector":"input[name='password']","value":"${PASSWORD}"}\`
- \`{"action":"click","selector":"button[type='submit']"}\`
- \`{"action":"select_option","selector":"select[name='role']","value":"admin"}\`
- \`check\`, \`uncheck\`, \`expect_visible\`, \`expect_hidden\`
- \`{"action":"expect_text","text":"Welcome"}\`
- \`{"action":"expect_url","contains":"/dashboard"}\`
- \`{"action":"assert_title","contains":"Portal"}\`
- \`press\`, \`screenshot\`, \`wait_for_timeout\`
- \`manual\`: placeholder that marks the case BLOCKED until replaced.

Placeholders: \`${BASE_URL}\`, \`${USERNAME}\`, \`${PASSWORD}\`. Explicit navigation is restricted to the configured base host. Credentials are held in Streamlit session memory only.

## Limitations and operational notes

- Requirement extraction is heuristic; review imported requirements.
- AI output may be wrong and must be reviewed.
- Selectors must be verified against the target DOM.
- Execution is synchronous in the Streamlit process. Use an isolated worker and a production database before team-scale concurrent use.
- Do not run destructive cases or production-data tests without an approved plan and backups.
