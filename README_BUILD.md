Build instructions for Windows (PyInstaller)

Prerequisites:
- Python 3.11+ installed (project tested on 3.13)
- Build tools available (pip)

Quick build steps:
1. Create a virtual environment (recommended):
   python -m venv .venv
   .\.venv\Scripts\activate
2. Install runtime and build deps:
   python -m pip install -r requirements.txt
3. Run the build script:
   build.bat

Result:
- Single-file executable: dist\erp_offline.exe
- Use Inno Setup with `installer.iss` to create an installer (adjust paths if needed).
