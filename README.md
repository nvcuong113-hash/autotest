# AutoTest — SRS-driven Web QA Platform

AutoTest converts SRS documents into traceable requirements and editable test cases, then executes browser steps with Playwright.


## Architecture: SRS-driven reusable test engine

AutoTest separates business test design from application-specific browser locators.

1. **SRS Intelligence** – parses PDF, DOCX, XLSX, CSV, Markdown and text; Gemini can extract explicit requirements, actors, preconditions, business rules, acceptance criteria and source references. Local parsing remains available without an AI key.
2. **Test Design** – generates requirement-linked scenarios and semantic test steps. AI output is a draft and must be reviewed.
3. **Application Profile** – JSON profile per application, containing base URL, authentication strategy, session probe, page routes, shared components and verified semantic targets.
4. **Action Registry / Execution Engine** – resolves business targets such as `guarantee.create_button` through the selected profile. The Test Case itself does not contain CSS/XPath selectors.
5. **Evidence & Reporting** – stores test runs, result statuses, source references and automation level.

### Add another application

Create a JSON file under `application_profiles/<profile-id>.json` following `application_profiles/oap-meta.json`.

- Define the application's authentication strategy and session probe.
- Define internal page IDs and routes.
- Add shared/page targets only after they are verified from the application.
- Mark a target `"verified": true` only when the locator has been checked against the target environment.
- Do not copy OAP Meta selectors into another application profile.

The same SRS parser, semantic test model, action registry, execution engine and reporting functions are reused by every profile.

### Mapping Coverage and Automation Assessment

The UI provides a project-level **Mapping & Coverage** workspace.

- It assesses every Test Case against the selected Application Profile and shows READY/BLOCKED, recommended automation level, missing page/target mappings, manual placeholders and missing assertions.
- Project mappings are persisted in the database (SQLite locally, Neon PostgreSQL when configured) and scoped by project + Application Profile + page + semantic target.
- A page-specific mapping can be reused by every Test Case that references the same semantic target. A Shared mapping can be reused across pages for common headers, search boxes, navigation and other reviewed components.
- Inspector input/button suggestions can prefill a locator. A human must explicitly confirm that the locator has been checked on the correct staging screen before it is marked verified.
- Re-assessment updates automation levels in bulk. Only READY cases with a real assertion become `automatable`; partial/unmapped cases remain blocked from execution.
- Mapping a selector does not rewrite a manual placeholder into a business workflow. Manual Test Cases still need explicit semantic steps and assertions before they can be unlocked.
- The execution screen offers only assessed, enabled and automatable cases. Previously BLOCKED cases can be selected again after mapping and re-assessment.

### Test Case automation levels

- `automatable`: all required steps and assertions are available through verified mappings.
- `partially_automatable`: some steps can run but at least one action/target needs review.
- `manual`: the case is not executed by Playwright.
- A case without an assertion is blocked from execution; navigation or data entry alone must never produce a false PASS.

### Gemini AI provider

The default AI provider is Google Gemini, configured with `AI_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.5-flash-lite`, and `GEMINI_API_KEY` on the UI service. No OpenAI key or OpenAI SDK is required. The free tier has quotas and rate limits; quota errors are shown instead of silently switching providers or fabricating results.


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
