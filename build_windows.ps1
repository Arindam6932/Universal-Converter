$ErrorActionPreference = "Stop"
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --onedir --name UniversalFileConverter --add-data "app;app" main.py
Write-Host "Build complete: dist\UniversalFileConverter\UniversalFileConverter.exe"
