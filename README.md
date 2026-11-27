# TableCraft

TableCraft is a Django restaurant operations app that connects staff onboarding,
table QR codes, the customer menu, and the station dashboard. This repository
contains the Project Development 2 (PD2) vertical slice and the Project
Development 3 (PD3) hardening pass. PD3 adds no new customer-facing feature; it
makes the delivered features safe, validated, and testable.

## Increment summary

### Project Development 1 — standard features

The PD1 features remain the foundation of the app:

- Staff sign-in, sign-out, and role-based access.
- Owner-only staff onboarding and staff editing through **Add staff member**.
- Profile editing, including an optional profile photo.
- Password change flow.
- Operations dashboard with an active staffing summary.

Roles are `CASHIER`, `KITCHEN`, and `MANAGER`. A Django superuser is the **Owner**
and has the full staff-management superset.

### Project Development 2 — core feature description

The PD2 core feature is **Owner Table and QR Code Management**.

The Owner can:

- Register a dining table or booth with a short, human-readable label.
- Get a unique QR code for that table.
- Open the public table menu from the table list.
- Rotate a QR token when a printed code is lost or exposed. The old link stops
  working immediately.
- Deactivate or reactivate a table. A deactivated table's QR menu returns a
  branded `404`, so removed tables cannot be used by customers.

Table labels are normalized to uppercase, limited to 10 characters, restricted
to letters, numbers, spaces, hyphens, and underscores, and checked for
case-insensitive duplicates. QR tokens are generated with Django's
`secrets.token_urlsafe`, so they are not based on the table's primary key.

### Project Development 3 — hardening

PD3 hardens the PD2 core feature and the PD1 standard features:

- Server-side validation and bounded form values.
- Database-level `CHECK` and uniqueness constraints for orders and menu data.
- Atomic order saving and fail-closed ordering while the lifecycle is incomplete.
- Branded `403`, `404`, and `500` pages.
- Confirmation prompts for deactivation, QR rotation, and archive actions.
- An automated regression suite that runs on in-memory SQLite, never on the
  live Supabase database.
- The PD3 report PDF in `docs/TableCraft-Bungabong-Justine-G2-PD3.pdf`.

Customer ordering is intentionally switched off in this build
(`ORDERING_ENABLED=False`). The menu is browsable, but submitting an order
returns `503` until the payment/kitchen/status lifecycle is implemented in PD4.

## Setup steps

### 1. Prerequisites

- Python 3.12+ (Python 3.13 was used during development).
- PostgreSQL/Supabase connection string.
- Git.

### 2. Clone and create a virtual environment

Windows (PowerShell):

```powershell
git clone https://github.com/justinebungabong/TableCraft-Bungabong-Justine-G2.git
cd TableCraft-Bungabong-Justine-G2
py -3 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

macOS/Linux:

```bash
git clone https://github.com/justinebungabong/TableCraft-Bungabong-Justine-G2.git
cd TableCraft-Bungabong-Justine-G2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the environment

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

or:

```bash
cp .env.example .env
```

Then fill in real values. Do not commit `.env`.

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DEBUG=False
ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=postgres://user:password@host:5432/tablecraft
DB_CONN_MAX_AGE=0
ORDERING_ENABLED=False
```

Notes:

- `DATABASE_URL` must point to the Supabase PostgreSQL connection string.
- `DB_CONN_MAX_AGE=0` avoids pinning sessions on Supabase's limited session
  pooler. Raise it only if your pooler has a higher connection cap.
- `DEBUG=False` is the production-like setting. Add your deployed hostname to
  `ALLOWED_HOSTS`.
- `ORDERING_ENABLED` must stay `False` until the PD4 order lifecycle exists.
- Rotate the database password if it was ever shared outside the team.

### 4. Apply migrations

```powershell
python manage.py migrate
```

This also applies `pos/0002_order_constraints.py`, which adds the PD3 database
constraints.

### 5. Create the Owner account

```powershell
python manage.py createsuperuser
```

A superuser is displayed as **Owner** and can manage staff, tables/QR codes, and
the menu. Additional staff can be created from **Add staff member** after
signing in.

### 6. Prepare static files

For local development with `DEBUG=False`, Django can serve static files with
`--insecure` if needed:

```powershell
python manage.py collectstatic
python manage.py runserver 127.0.0.1:8000 --insecure
```

In deployment, run `collectstatic` during build and serve `staticfiles/` through
the host or CDN instead of relying on `--insecure`.

Open <http://127.0.0.1:8000/accounts/login/> and sign in. The main pages after
login are:

- `/dashboard/` — operations and staff summary.
- `/pos/tables/` — Owner table registry and QR codes.
- `/pos/menu/` — Owner/Manager category and item maintenance.
- `/accounts/profile/` — staff profile and photo.
- `/accounts/password-change/` — password change.

Uploaded media is served by Django only when `DEBUG=True`. In production, serve
`MEDIA_URL` from object storage or the web server.

## Running the tests

Run the full suite from the project root with the virtual environment active:

```powershell
python manage.py test
```

If the virtual environment is not activated:

```powershell
.\venv\Scripts\python.exe manage.py test
```

macOS/Linux:

```bash
python3 manage.py test
```

The tests are safe to run against a development machine because
`tablecraft/settings.py` replaces `DATABASES["default"]` with in-memory SQLite
when the `test` command is used. The suite does **not** read or write the live
Supabase database.

Useful variants:

```powershell
python manage.py test pos
python manage.py test accounts
python manage.py test tablecraft
python manage.py test pos.tests.TablesTests
python manage.py test --verbosity 2
```

A healthy run ends with `OK`, for example:

```text
Ran 239 tests in 99s

OK
```

Before merging or deploying, also run:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
```

Both should report no issues and no missing migrations.

## Reports

- `docs/TableCraft-Bungabong-Justine-G2-PD2.pdf` — PD2 core feature report.
- `docs/TableCraft-Bungabong-Justine-G2-PD3.pdf` — PD3 hardening report.
