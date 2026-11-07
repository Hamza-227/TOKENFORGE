@echo off
REM TOKENFORGE one-click launcher (Windows)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating virtual environment...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
where tesseract >nul 2>nul || echo Note: Tesseract OCR not found ^(only needed for scanned PDFs/images^). See README.
.venv\Scripts\python.exe server.py
pause
