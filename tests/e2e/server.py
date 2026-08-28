import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Добавим текущую директорию в путь для импорта app
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

os.environ["USE_SQLITE"] = "1"
database_path = Path(tempfile.gettempdir()) / "erp_e2e.sqlite"
database_path.unlink(missing_ok=True)
os.environ["SQLITE_DB_PATH"] = str(database_path)
os.environ["ERP_AUTH_SECRET"] = "e2e-only-secret"
os.environ["ERP_INITIAL_ADMIN_PASSWORD"] = "admin"
os.environ["ERP_SERVER_PORT"] = "1834"
os.environ["ERP_DISABLE_INITIAL_PASSWORD_CHANGE"] = "1"

from app.main import main


if __name__ == "__main__":
    asyncio.run(main())
