# Backup for the Windows laptop / office PC installation (SQLite development database + uploads).
# Run in PowerShell from the project folder:  powershell -ExecutionPolicy Bypass -File deploy\backup_windows.ps1
# For PostgreSQL on Windows use: pg_dump --format=custom --dbname=$env:DATABASE_URL --file=backup.dump
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $HOME "TechnoflowCRM-backups"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
if (Test-Path "db.sqlite3") {
    # SQLite's own backup command gives a consistent copy even while the CRM is running
    python -c "import sqlite3; s=sqlite3.connect('db.sqlite3'); d=sqlite3.connect(r'$dest\db-$stamp.sqlite3'); s.backup(d); d.close(); s.close()"
    Write-Host "Database -> $dest\db-$stamp.sqlite3"
}
if (Test-Path "media") {
    Compress-Archive -Path "media\*" -DestinationPath "$dest\media-$stamp.zip"
    Write-Host "Documents -> $dest\media-$stamp.zip"
}
Get-ChildItem $dest | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item
Write-Host "Backup finished."
