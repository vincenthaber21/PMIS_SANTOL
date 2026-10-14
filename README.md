# Property Management System (PMS)

**Equipment Management and Data Analytics** — a full-stack Django web application for managing organizational equipment, borrowing workflows, maintenance, and analytics.

## Tech Stack

- **Backend**: Django 5.x (Python 3.11)
- **Database**: SQLite (dev) / PostgreSQL-compatible
- **Frontend**: Django Templates + Bootstrap 5 + Chart.js
- **Auth**: Django built-in with 4 roles (Admin, Property Custodian, Technician, Employee)
- **Exports**: PDF (ReportLab), Excel (openpyxl), CSV

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations
python manage.py migrate

# 3. Seed sample data (40 equipment, 4 users, borrow/maintenance records)
python manage.py seed_data

# 4. Start development server
python manage.py runserver 0.0.0.0:5001
```

## Demo Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin (superuser) | admin | admin123 |
| Property Custodian | custodian1 | pass1234 |
| Technician | tech1 | pass1234 |
| Employee | employee1 | pass1234 |

## Apps

| App | Purpose |
|-----|---------|
| `accounts` | Custom User model, login/logout, profile, user management |
| `equipment` | Inventory, registration, QR codes, depreciation |
| `borrowing` | Borrow requests, approval workflow, overdue tracking |
| `maintenance` | Service requests, technician assignment, cost tracking |
| `analytics` | KPIs, performance metrics, lifecycle prediction |
| `reports` | Generate & export (PDF, Excel, CSV) |
| `core` | Dashboard, audit trail, notifications, global search |

## Features

- Role-based access control (Admin, Property Custodian, Technician, Employee)
- Auto-computed book value (Straight Line & Declining Balance depreciation)
- QR code generation per property number
- Dashboard with 5 Chart.js charts (pie, line, bar, gauge, horizontal bar)
- Analytics: Equipment Performance Index, Inventory Accuracy, Downtime Rate
- Lifecycle prediction with Risk Score and replacement recommendations
- Audit trail on all create/update/archive actions
- Notification system (borrow, maintenance, overdue events)
- PDF / Excel / CSV export with filter support
- Global search across equipment, borrows, and maintenance

## Django Admin

Access at `/admin/` with `admin / admin123`.

## Notes

- All costs displayed in Philippine Peso (₱)
- SQLite database is stored as `db.sqlite3` in the project root
- Media files (QR codes, avatars) stored under `media/`
- To reset and re-seed: delete `db.sqlite3`, re-run `migrate` and `seed_data`
