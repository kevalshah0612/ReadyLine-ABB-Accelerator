# ReadyLine

ReadyLine helps maintenance teams review equipment readings and plan maintenance work. It checks vibration and temperature trends, looks for comparable equipment, and proposes a procedure and maintenance window based on available parts, staff, and production schedules.

A supervisor approves the proposed work. A technician then completes the procedure checklist and records the findings. Those records are stored in the database and are available during later analyses.

Built for the ABB Accelerator 2026 maintenance challenge.

## What you can do

- Register motors, pumps, fans, and drives with their operating limits.
- Import timestamped equipment readings through the web interface or HTTP API.
- Run five NVIDIA-powered agents to review condition, fleet history, priority, procedures, and scheduling.
- Inspect the tool results and conclusions from each analysis.
- Manage parts inventory, procedure steps, and maintenance windows.
- Approve work, reserve parts, and record completed repairs.
- Review a history of changes and decisions.

## Using the workspace

Use the navigation across the top to open equipment, agent results, work orders, planning, or the activity log.

- Agent results show priority and the review deadline first, followed by bullet-point findings. Expand the supporting details to see the full assessment and limitations.
- Work orders awaiting approval appear before completed or cancelled work. Check the priority, deadline, and maintenance window before approving.
- The red, white, and gray interface is inspired by ABB. ReadyLine is an accelerator project.

## Stack

| Component | Technology |
| --- | --- |
| Web interface | React, TypeScript, Vite |
| API | Python, FastAPI |
| Database | SQLite |
| Model | NVIDIA Nemotron through the NVIDIA API |
| Tests | pytest |

The database is created automatically when the server starts. No separate database installation is needed.

## Requirements

- Python 3.11 or later
- Node.js 22 or later, with npm
- Git
- An NVIDIA API key with access to `nvidia/nemotron-3-ultra-550b-a55b`

## Install and run on Windows

Run these commands in PowerShell.

### 1. Download the project

```powershell
git clone https://github.com/kevalshah0612/ReadyLine-ABB-Accelerator.git
cd ReadyLine-ABB-Accelerator
```

If you already have the project, open a terminal in its root folder and start with step 2.

### 2. Install the dependencies

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
npm.cmd --prefix frontend ci
```

### 3. Add your NVIDIA key

Create `.env` from the example if it does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set the following values and save the file:

```dotenv
NVIDIA_API_KEY=your_nvidia_api_key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_ENABLE_THINKING=false
NVIDIA_MAX_TOKENS=2048
```

Keep the key in `.env`. This file is excluded from Git. The backend reads the key; it is not included in the browser application.

### 4. Build the web interface

```powershell
npm.cmd --prefix frontend run build
```

### 5. Start the server

```powershell
.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** and create your administrator account. There is no default username or password. Keep the terminal running while you use the application; press `Ctrl+C` to stop it.

The database is stored at `data/readyline.sqlite3`. Records remain available after a server restart. Restart the server whenever you change `.env`.

## Install and run on macOS or Linux

```bash
git clone https://github.com/kevalshah0612/ReadyLine-ABB-Accelerator.git
cd ReadyLine-ABB-Accelerator
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm --prefix frontend ci
test -f .env || cp .env.example .env
```

Edit `.env` and add your NVIDIA key, then run:

```bash
npm --prefix frontend run build
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** and create your administrator account.

## Try the sample scenario

The application starts with an empty database. To try the workflow without connecting equipment, run this command from a second terminal in the project root:

```powershell
.venv\Scripts\python -m scripts.seed_demo
```

On macOS or Linux, use `.venv/bin/python` instead.

This adds four sample assets, measurements, parts, inspection procedures, and future maintenance windows. The readings are labeled `synthetic-demo`. Analysis results and work orders are generated when you run an analysis; they are not preloaded.

1. Sign in and open **Fleet intelligence**.
2. Select **MTR-042** and click **Run agent analysis**.
3. Open **Agent runs** to follow the tool calls and review the conclusions. NVIDIA responses can take several minutes.
4. If a proposal is created, open **Work orders** and review the procedure, parts, and window.
5. Click **Approve & reserve**.
6. Complete the checklist and enter the findings, duration, and post-repair vibration.
7. Submit the completed job and refresh the page to check the saved record.

An agent may escalate an analysis when evidence or resources are insufficient. Review its explanation, update the inputs, and try again. Sample procedures are for demonstrating the software; replace them with site-approved procedures before operational use.

Running the sample import again adds fresh readings and future windows. It does not reset your database.

## Use your own equipment data

1. Register an asset in **Fleet intelligence**. Enter its class, rated power, duty cycle, operating limits, and safety and production ratings.
2. Add readings with **Ingest telemetry**. Each CSV line contains `timestamp,vibration,temperature,load`, without a header. Timestamps must include a timezone, such as `2026-09-27T12:00:00Z`.
3. Supply at least three readings across distinct times. The latest reading must be less than 24 hours old.
4. In **Planning & resources**, add the required parts and a procedure for the asset's equipment class. Include its duration, steps, quantities, and approved source reference.
5. Add maintenance windows for the same production area. Enter the available time, staff, permit status, and production utilization.
6. Run an analysis from the asset page.

An external data source can submit readings to `POST /api/assets/{asset_id}/telemetry`. API routes and request schemas are available at **http://127.0.0.1:8000/docs**.

API clients must sign in through `POST /api/auth/login`, retain the session cookie, and send `X-ReadyLine: 1` on write requests. A telemetry request contains a `readings` array and an optional `analyze` flag. Setting `analyze` to `true` requests analysis in the same transaction; if analysis cannot be queued, that transaction is rolled back.

## How analysis works

| Agent | Task |
| --- | --- |
| Health | Reads measurements and calculates trends and threshold comparisons. |
| Fleet | Finds similar equipment and retrieves recorded repair findings. |
| Risk | Calculates priority from equipment condition and configured consequences. |
| Work order | Selects a procedure from the catalog and checks its required parts. |
| Schedule | Checks maintenance windows and compares expected production disruption. |

Each agent calls backend tools through the NVIDIA API. The tools calculate scores and check constraints. The model reviews the returned information and provides a conclusion. Tool results and conclusions are stored with the analysis record.

Approval rechecks the current measurements, procedure, stock, and schedule. It rejects a proposal if these checks fail. Completing an approved job requires every procedure step and saves the technician's findings for later reference.

Asset information, relevant measurements, procedures, schedule information, and retrieved findings are sent to NVIDIA during analysis. Use data you are authorized to share with that service. Provider requests are subject to your account's usage limits and charges.

## User roles

| Role | Access |
| --- | --- |
| Administrator | All actions, including creating users. |
| Supervisor | Manages inputs and procedures, requests analysis, and approves or cancels work. |
| Planner | Manages assets, measurements, inventory, and windows; requests analysis. |
| Technician | Completes approved work and records findings. |

All roles can view the workspace. Administrators can create accounts from **Planning & resources**.

## Development

Run the backend as described above. In another terminal, start the frontend development server:

```powershell
npm.cmd --prefix frontend run dev
```

Open the URL printed by Vite. It forwards `/api` requests to the backend on port 8000.

Run checks from the project root:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check backend scripts tests
npm.cmd --prefix frontend run build
```

The automated tests use temporary databases and test responses for the model calls. They do not use your NVIDIA account. To test the complete agent sequence against NVIDIA, run:

```powershell
.venv\Scripts\python -m scripts.verify_live
```

This makes provider requests and stores its sample inputs and results in a separate `data/validation-*.sqlite3` database.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `NVIDIA_API_KEY` | Empty | Your NVIDIA API key. |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Provider endpoint. |
| `NVIDIA_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b` | Model used by the agents. |
| `NVIDIA_ENABLE_THINKING` | `false` | Enable extended model reasoning when needed. |
| `NVIDIA_MAX_TOKENS` | `2048` | Response token limit per request. |
| `NVIDIA_TIMEOUT_SECONDS` | `180` | Provider request timeout. |
| `READYLINE_DB` | `data/readyline.sqlite3` | Database location. |
| `COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS. |

Run one server worker. The current queue and SQLite database are designed for a single application instance.

### Model choice and response time

The default is Nemotron 3 Ultra 550B with extended thinking disabled. Super is available as an optional faster model. In small local tests on the sample workflow, completed Super runs took about 34-46 seconds. The final 34-second run completed all five stages without rejected tool calls or provider retries. Ultra took 2 minutes 39 seconds with thinking disabled; the earlier Ultra run with thinking enabled took 5 minutes 37 seconds. These were individual hosted-API runs, not controlled throughput or diagnostic-accuracy benchmarks. Service load and retries affect the time.

Some requests needed a correction before their output passed validation. Those rejected calls remain visible in the event log. A temporary stream failure is retried at most twice, after 5 and 15 seconds; partial responses are discarded before any tool is executed. The procedure, inventory, schedule, and human-approval checks remain enforced for every model.

To compare a model without changing your application configuration:

```powershell
.venv\Scripts\python -m scripts.verify_live --model nvidia/nemotron-3-super-120b-a12b --no-thinking --max-tokens 2048
.venv\Scripts\python -m scripts.verify_live --model nvidia/nemotron-3-super-120b-a12b --no-thinking --max-tokens 2048 --scenario stockout
```

The stockout test expects an escalation with no work order. Reports include elapsed time, completed stages, constraint checks, rejected calls, and provider retries. They are saved beside the isolated validation database under `data/`.

The default model is `nvidia/nemotron-3-ultra-550b-a55b` with thinking disabled. For faster runs, you can select `nvidia/nemotron-3-super-120b-a12b` through `.env`. If you enable thinking, raise the response budget (for example, to `16384`) and expect longer runs. Restart the backend after changing these values. NVIDIA documents the models on its [Super](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) and [Ultra](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b) pages.

## Project structure

```text
backend/
  main.py          API routes and maintenance workflow
  agents.py        NVIDIA calls and analysis worker
  domain.py        Measurement, similarity, priority, and scheduling calculations
  db.py            Database schema and transactions
  schemas.py       Request and response validation
  security.py      Passwords, sessions, and role checks
  config.py        Environment settings
frontend/src/      Web interface, forms, and API client
scripts/           Sample data import and NVIDIA verification
tests/             API, workflow, and agent tests
Dockerfile         Container build
.env.example       Configuration template
```

Submission documents are kept separately in the local `refs/` folder and are not included in this repository. Credentials, databases, installed dependencies, caches, and compiled frontend files are also excluded.

## Submission materials

The six submission items are a project summary, working prototype, demo video, source-code link, technical documentation, and an optional presentation deck.

The source-code link is https://github.com/kevalshah0612/ReadyLine-ABB-Accelerator. For a local checkout containing the separate submission materials, open `refs/SUBMISSION_INDEX.md` for the file mapping and remaining actions. Those files are deliberately excluded from this repository. The video still needs recording, and the optional deck currently has an outline only. A localhost URL is not accessible to remote judges.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Server shows a message asking you to build the frontend | Run `npm.cmd --prefix frontend run build`, then restart the backend. |
| Analysis says the NVIDIA key is missing | Set `NVIDIA_API_KEY` in `.env` and restart the backend. |
| A run fails during a temporary NVIDIA outage | On Agent runs, select it and click Retry analysis. This starts a fresh run for the same asset and preserves the old result. |
| NVIDIA returns an authentication or model-access error | Check that the key is valid and the account can use the configured model. |
| No suitable maintenance window | Check job duration, stock, crew availability, permit status, production area, and review deadline. |
| Approval says measurements or procedures changed | Cancel the proposal and run another analysis with the current inputs. |
| Completion is unavailable | Check that the job is approved, your role permits completion, and every checklist step is checked. |
| Port 8000 is already in use | Stop the previous server before starting another instance. |

## Current limits

The condition score uses thresholds and trends; it is not a trained remaining-useful-life model or a calibrated failure probability. Similarity uses equipment class, rated power, and duty cycle. Recorded feedback is retrieved as history rather than used to retrain a model.

Plant data enters through the HTTP API. Direct ABB, OPC UA, CMMS, and MES connections are not included. Production cost estimates use the values entered by the operator and are not measured savings.

For deployment outside your computer, use HTTPS, persistent database storage, and appropriate network access controls. Create the administrator account before exposing the service. The included Dockerfile builds the frontend and backend together; store the database in a mounted `/app/data` volume.
