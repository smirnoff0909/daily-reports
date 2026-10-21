# Запуск dev-версии. Stable живёт в C:\daily-reports на порту 8000.
$env:DATABASE_URL = "sqlite+pysqlite:///./dev.db"
$env:SECRET_KEY   = "dev-local"
$env:COOKIE_SECURE = "false"
$env:APP_NAME     = "Отчёты · dev"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
