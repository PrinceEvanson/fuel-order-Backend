# Fuel Order Desk - Backend

The API behind the Fuel Order Automation demo. Clients upload fuel purchase-order PDFs, Claude extracts the order, deterministic checks flag problems, and a human reviewer approves each order before it is posted to Sage Accounting as a sales quote (the stand-in for a pro-forma invoice).

This repository is the FastAPI backend. The React frontend lives in `fuel-order-frontend`.

## What it does

1. A client uploads a PDF. The backend stores it and asks Claude to read it.
2. Claude returns structured data: customer, PO number, date, address, currency, document total and order lines (description, quantity, unit, unit price, line total).
3. Ordinary code then matches the customer and products against Sage, runs the maths and sanity checks, detects duplicates and assigns an AI status: passed or flagged.
4. The client previews the result and either sends it to review, discards it, or asks for a redo with a description of what went wrong. That description is fed back to the AI.
5. A reviewer sees the queue, edits fields, rejects with a required reason, or approves. Approval posts a sales quote to Sage.
6. Every step is written to an audit log.

The AI only reads and fills in a form. It never approves anything. Every Sage write needs a human approval.

## Tech stack

- Python 3.12 and FastAPI, served by Uvicorn
- SQLAlchemy 2 with PostgreSQL (psycopg2). SQLite is the fallback if no database URL is set
- JWT authentication (PyJWT) with two roles, `client` and `reviewer`, and PBKDF2 password hashing
- Anthropic API (`anthropic` SDK) with native PDF input and tool use for structured extraction
- Sage Accounting API v3.1 over OAuth 2.0, called with `httpx`
- Optional mock modes for the AI and for Sage so the whole app can be tested without keys

## Architecture

```
app/
  main.py               FastAPI app, CORS, router registration
  config.py             settings read from .env
  db.py, models.py      database engine and tables
  security.py, deps.py  password hashing, JWT, role guard
  serializers.py        response shapes
  seed.py               creates the two demo accounts
  seed_demo.py          loads demo PDFs into the reviewer queue
  routers/
    auth.py             login, signup, me
    client.py           upload, list, get, redo, submit, discard
    review.py           queue, detail, audit, edit, analyse, rescan, reject, approve
    files.py            authenticated PDF download for the viewer
    sage.py             connection status, connect URL, OAuth callback
  services/
    extractor.py        Claude call (prompt and tool schema live here)
    mock_extractor.py   no-AI placeholder extraction
    pipeline.py         extract, match, check, fingerprint, duplicate flag
    matcher.py          fuzzy matching of customers and products
    checks.py           flags and AI status
    catalog.py          customers and products from Sage (or built-in samples)
    sage_client.py      the only module that talks to Sage
    audit.py            audit log writer
tests/test_logic.py     unit tests for matching, checks and the mock extractor
```

### How the AI knows what to do

`app/services/extractor.py` holds the two things that steer Claude:

- `PROMPT`: plain instructions. Extract the purchase order, copy values exactly as printed, never correct arithmetic or convert units or currencies, use null for anything missing, report the currency as an ISO code, and say the document is not a purchase order when it is not.
- `PO_TOOL`: a JSON schema for the answer. Claude is asked to answer by calling this tool, so the result is structured data and not free text.

The PDF is sent to Claude as a document. When a client asks for a redo, the issues they reported are added to the instruction. Edit `PROMPT` to change what Claude pays attention to.

### Automatic reading

Documents that have not been read by Claude yet (for example, ones loaded while in mock mode) are read when a reviewer opens the queue or a document: `POST /api/review/documents/{id}/analyse`. A document is read once and the result is stored; `rescan` forces a fresh read.

### Checks and flags

Each flag has a severity: error (blocks approval), warn (must be acknowledged) or info.

Examples: not a purchase order, missing PO number, no order lines, unknown customer, low match confidence, ambiguous delivery site, missing price or quantity, unknown product, unit mismatch with Sage, line total or document total not matching quantity times price, AI unsure, duplicate, and a note when the values came from mock mode.

Approval rules: no errors; if there are warnings the reviewer must acknowledge them, and with 5 or more warnings approval is refused until they are fixed or the document is rejected (`MAX_ACK_WARNINGS` in `app/routers/review.py`).

### Duplicate protection

A soft DUPLICATE flag is raised when the same file hash or the same customer and PO number already exists. Hard unique indexes on the posted fingerprint and the posted file hash make a second quote impossible even under a race, and the fingerprint is claimed before the call to Sage.

### Document statuses

`extracted`, `submitted`, `posting`, `posted`, `post_failed`, `rejected`, `discarded`. AI status is `passed`, `flagged` or `failed`.

## Getting started

Requirements: Python 3.12, and either Docker (for PostgreSQL) or nothing at all (SQLite fallback).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Start PostgreSQL (optional, recommended). Port 5433 avoids clashing with a local install:

```bash
docker run -d --name fuel-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=fuel -p 5433:5432 postgres:16
```

Edit `.env` (see the table below), then create the demo accounts and start the server:

```bash
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

The server reads `.env` only when it starts, so restart it after every change. Tables are created automatically on start.

### Environment variables

| Name | Purpose |
| --- | --- |
| `ENV` | `dev` or `production`. Production requires `JWT_SECRET` |
| `JWT_SECRET` | Long random string used to sign tokens |
| `JWT_EXPIRE_MINUTES` | Token lifetime, default 480 |
| `DATABASE_URL` | For example `postgresql://postgres:postgres@localhost:5433/fuel` |
| `ALLOWED_ORIGINS` | Comma separated frontend origins, for example `http://localhost:5174` |
| `FRONTEND_URL` | Where Sage sends the browser back to after connecting |
| `AI_MODE` | `claude` to use Claude, `mock` for placeholders, `auto` to use Claude only if a key exists |
| `ANTHROPIC_API_KEY` | Key from the Claude Console. The API is billed separately from Claude chat plans |
| `ANTHROPIC_MODEL` | Model name, default `claude-sonnet-5-5` |
| `MAX_UPLOAD_MB` | Upload size limit, 4 on Vercel |
| `MOCK_SAGE` | `true` fakes quote creation until Sage is connected |
| `REVIEWER_INVITE_CODE` | Code required to sign up as a reviewer. Leave empty to switch reviewer sign-up off |
| `SAGE_CLIENT_ID`, `SAGE_CLIENT_SECRET` | From your app in the Sage developer portal |
| `SAGE_REDIRECT_URI` | Must equal the callback URL registered in Sage, for example `http://localhost:8000/api/sage/callback` |
| `SAGE_WEB_QUOTE_URL` | Template for the link to a quote, `{id}` is replaced |
| `SAGE_SALES_LEDGER_ACCOUNT_ID`, `SAGE_TAX_RATE_ID` | Optional. If empty the app picks a sales ledger account and a zero-rate tax rate itself |
| `SEED_CLIENT_EMAIL`, `SEED_CLIENT_PASSWORD` | Demo client account created by `python -m app.seed` |
| `SEED_REVIEWER_EMAIL`, `SEED_REVIEWER_PASSWORD` | Demo reviewer account |

There are no default passwords: `python -m app.seed` stops until you set the seed passwords.

Do not put spaces after the `=` signs and never commit `.env`.

## Connecting Sage Accounting

1. Create a Sage Accounting trial business. Sage's developer documentation lists trials for the United Kingdom, Canada and Ireland. Choose a tier that includes quotes, such as Standard or Plus. The South African edition uses a different codebase and is not covered by this integration.
2. In that business create sample data the matcher can use:
   - Customers: set a short code in the Reference field (for example `SDG001`). Use names like "City of San Diego", "Garland Independent School District" and "Mbeya Zonal Referral Hospital".
   - Products: set the Product code to `ULG`, `DSL` or `DSL-D`.
3. Sign up for a Sage developer account at developer.sage.com (GitHub or email) and create an app. Enter a name, an email and the callback URL `http://localhost:8000/api/sage/callback`.
4. Open the app and use Show to reveal the Client ID and Client Secret. Put them in `.env` as `SAGE_CLIENT_ID` and `SAGE_CLIENT_SECRET`. Set `SAGE_REDIRECT_URI` to the same callback URL and `FRONTEND_URL` to the frontend address.
5. Restart the backend. In the app, sign in as a reviewer and click Connect under your name. Sign in to Sage, choose the business and allow access. The notice turns green.
6. Approve a document. A real sales quote is created in the connected business. Quote numbers and links are stored on the document.

How it works: the OAuth refresh token rotates on every use and is stored in the database. All Sage calls go through `app/services/sage_client.py`. Customers are read from contacts and matched by name; products are read from products and matched by description and code. The catalog is cached for 60 seconds.

Limits to know about: quotes are posted in the Sage business's own currency and units. The document's currency is added to the quote notes but amounts are not converted. Quantities are not converted between units; a unit mismatch is flagged instead.

## API overview

All routes need `Authorization: Bearer <token>` except login, signup and the Sage callback.

| Area | Routes |
| --- | --- |
| Auth | `POST /api/auth/login`, `POST /api/auth/signup`, `GET /api/auth/me` |
| Client | `POST /api/client/documents`, `GET /api/client/documents`, `GET /api/client/documents/{id}`, `POST .../redo`, `POST .../submit`, `DELETE .../{id}` |
| Reviewer | `GET /api/review/documents?bucket=`, `GET /api/review/stats`, `GET /api/review/documents/{id}`, `GET .../audit`, `PUT .../fields`, `POST .../analyse`, `POST .../rescan`, `POST .../reject`, `POST .../approve` |
| Files | `GET /api/documents/{id}/file` |
| Sage | `GET /api/sage/status`, `GET /api/sage/connect-url`, `GET /api/sage/callback` |
| Health | `GET /api/health` |

Interactive docs are at `http://localhost:8000/docs` while the server runs.

## How to use it

1. Run the steps in Getting started.
2. Optionally load demo documents into the reviewer queue: save PDFs into `demo_pdfs/` or let the loader download them, then run `python -m app.seed_demo`. It skips files already loaded. Some sites block automatic downloads; save those files by hand with the file names the loader prints.
3. Sign in on the frontend as the demo client, upload a PDF and send it. Sign in as the reviewer, open it, correct anything flagged, and approve or reject.
4. With `AI_MODE=mock` the app returns placeholder values and a banner says so. With `AI_MODE=claude` and a funded key, Claude reads the documents.

## Tests

```bash
pip install pytest
python -m pytest tests
```

## Deployment

A `vercel.json` and `api/index.py` are included for deploying the API as a Vercel serverless function. Vercel limits request bodies to about 4.5 MB, so set `MAX_UPLOAD_MB=4`. Use a hosted PostgreSQL database and set every variable from the table in the project settings. Add the deployed frontend origin to `ALLOWED_ORIGINS`, and the deployed callback URL in both `.env` and the Sage app settings.

## Known limits

- Tables are created with `create_all`; there are no migrations.
- No rate limiting on sign-up.
- Units and currencies are flagged and noted, not converted, in what is posted to Sage.
- Forwarded-email intake and emailed pro-forma invoices are not built.