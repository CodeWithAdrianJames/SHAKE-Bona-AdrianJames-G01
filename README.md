# SHAKE — Structured Handling and Automated Knowledge Extraction

**From Paper to Data:** An offline-first logistics automation web platform designed to convert unstructured ocean freight contract PDFs from shipping carriers (**MSC, CMA CGM, COSCO**, etc.) into structured, machine-readable **Excel, CSV, and JSON** data.

## Student & Course Information

| Field | Details |
|---|---|
| **Student** | Adrian James F. Bona |
| **Course & Section** | CSIT327 (Information Management 2) — Section G1 |
| **Phase** | Phase 1 — Project Setup & Account Feature |
| **Tech Stack** | Full Stack Django (Django Backend + Django Templates + Bootstrap 5 CDN) & PostgreSQL / Supabase |

## Quick Setup

1. **Create and activate a virtual environment**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env` with your PostgreSQL / Supabase connection credentials (`DATABASE_URL` or `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).

4. **Run migrations & start the development server**
   ```powershell
   python manage.py migrate
   python manage.py runserver
   ```
