# SheetWise — File Comparison & Validation Platform

A portfolio-ready starter that compares two Excel/CSV files, identifies discrepancies, and exports detailed reports.

## Stack
- FastAPI + Pandas + SQLite
- React + Vite
- Report exports: XLSX, PDF, DOCX
- Email/password authentication; Google OAuth is a configuration step, not active until credentials/callback are added.

## Run on Windows
Backend terminal:
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```
Frontend terminal:
```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```
Open http://localhost:5173. API docs: http://127.0.0.1:8000/docs

## Current MVP behavior
- Register, sign in, sign out, profile name editing, protected API routes
- Upload XLSX/XLS/CSV files, choose a matching key, compare records and values
- Detect missing/extra rows, missing/extra columns, mismatches, duplicate keys, blank cells
- Save comparison history in SQLite
- Export findings to Excel, PDF, and Word
- PDF/Word are report outputs only in this MVP; input parsing is currently Excel/CSV.
- Google sign-in button is a setup placeholder. Configure a Google OAuth client and implement the OAuth callback before claiming Gmail sign-in works.

## Before public deployment
Change JWT_SECRET, use secure HttpOnly cookies, add email verification/password reset, rate limiting, file malware scanning, storage limits, retention controls, HTTPS, and a security review. Results should be reviewed by a human; differences do not automatically mean the comparison file is wrong.

## GitHub
```powershell
git init
git add .
git commit -m "Build SheetWise file comparison platform"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/SheetWise.git
git push -u origin main
```
