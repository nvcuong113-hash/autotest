# AutoTest – Render deployment (split UI / Browser Runner)

## Why the deployment is split

The Render Free UI instance has 512 MB RAM. Running Streamlit and Chromium in the same container caused confirmed OOM restarts. The UI service therefore no longer installs or launches Playwright. Chromium runs in a separate, single-request Browser Runner service.

The SQLite fallback remains for local development only. On Render, configure PostgreSQL before creating test projects. Render Free filesystems are ephemeral.

## 1. Create a Neon PostgreSQL database

1. Create a Neon project in the Singapore region (or the closest available region).
2. Copy the PostgreSQL connection string. Keep it private.
3. Use the connection string as the `DATABASE_URL` environment variable in both Render services.
4. Do not commit the connection string to GitHub or paste it into chat.

The app initializes its schema automatically. If the new database has no projects, the UI service seeds the default project **OAP Meta - CCM Bank Guarantee** and imports the built-in CCM Guarantee catalogue (10 requirement groups and 75 test cases). Existing projects are not overwritten.

## 2. Generate a private Runner token

Generate a random token locally, for example:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = [Convert]::ToBase64String($bytes)
$token
```

Use the same token in both services. Do not put it in source code or share it in a screenshot.

## 3. Keep the existing UI service

Service: `oap-autotest-ccm`

Runtime remains Docker. Keep the current branch:

`feat/srs-autotest-mvp`

Set these Environment Variables:

- `DATABASE_URL` = Neon PostgreSQL connection string
- `RUNNER_URL` = public HTTPS URL of the Browser Runner service, e.g. `https://oap-autotest-runner.onrender.com`
- `RUNNER_API_TOKEN` = the private token generated above

The UI Dockerfile is `./Dockerfile`. It no longer installs Chromium or Playwright. The Runner Dockerfile is `./Dockerfile.runner` and installs only Playwright's Chromium headless shell (`playwright install chromium --only-shell`) to reduce the browser footprint on the 512 MB Free instance. It also bounds V8 heap, diagnostic buffers, DOM/frame collection and uses an 800x600 viewport.

## 4. Create a separate Browser Runner Web Service

Create another Render **Web Service** from the same GitHub repository.

- Name: `oap-autotest-runner`
- Branch: `feat/srs-autotest-mvp`
- Runtime: Docker
- Dockerfile Path: `./Dockerfile.runner`
- Docker Context: `.`
- Region: Singapore
- Instance: Free (512 MB RAM)
- Health Check Path: `/health`

Set these Environment Variables:

- `DATABASE_URL` = the same Neon PostgreSQL connection string
- `RUNNER_API_TOKEN` = the same private token as the UI service

The runner processes one browser job at a time and rejects batches larger than five test cases. Requests other than `/health` require the private token.

## 5. Verify

1. Open `https://<runner-host>.onrender.com/health`. It should return JSON with `ok: true`, `database_configured: true`, and `token_configured: true`. The endpoint also reports `peak_process_rss_mb` and `browser_job_active` for runtime memory diagnostics.
2. Confirm the UI service Environment Variables are saved and redeploy both services.
3. Open the UI. The sidebar should show PostgreSQL and Browser Runner as configured.
4. Confirm the project and 75 test cases have been seeded.
5. Run Browser Inspector before running any Test Cases.

## Free-tier notes

- Render Free services spin down after 15 minutes idle. The first request to the Browser Runner can take around a minute to wake up.
- Render's 750 Free instance hours are shared by services in the workspace. Two Free services running simultaneously consume hours twice as fast.
- Neon Free includes 1 GB per project and 100 compute-hours per project per month; the database can scale to zero after inactivity.
- This is a test/staging setup, not a production-grade availability guarantee.

## Security notes

- Never commit `DATABASE_URL` or `RUNNER_API_TOKEN`.
- Use a dedicated, least-privilege staging account for OAP Meta.
- Credentials are sent from the UI service to the Browser Runner over HTTPS and are not intentionally printed or stored by the Runner API.
- The Browser Runner is not a public anonymous execution API: the `X-Runner-Token` header is required for `/inspect` and `/run`.
