"""
Простейший прототип синхронизации Excel <-> SQLite для локального одного пользователя.
Работает так:
- Если нет data.db / data.xlsx — создаёт примерные данные и экспортирует их в data.xlsx
- Слежение за изменениями data.xlsx (watchdog). При сохранении читаются все листы и заменяют таблицы в SQLite (pandas.to_sql with if_exists='replace').
- Делает резервные копии файла excel и базы перед применением.

Это рабочий пример, не продакшн-решение. Для реального использования нужно добавить валидацию, транзакции, контроль ошибок и более тонкую логику слияния.
"""

import os
import time
import shutil
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import pandas as pd
from sqlalchemy import create_engine

BASE_DIR = Path(__file__).parent
EXCEL_FILE = BASE_DIR / 'data.xlsx'
DB_FILE = BASE_DIR / 'data.db'
BACKUP_DIR = BASE_DIR / 'backups'

os.makedirs(BACKUP_DIR, exist_ok=True)


def ensure_sample_data():
    """Если нет файлов — создаёт простую БД и эксель с двумя листами."""
    if not DB_FILE.exists():
        engine = create_engine(f"sqlite:///{DB_FILE}")
        # Примерные таблицы
        df_users = pd.DataFrame({
            'id': [1, 2],
            'name': ['Alice', 'Bob'],
            'email': ['alice@example.com', 'bob@example.com']
        })
        df_products = pd.DataFrame({
            'id': [1, 2],
            'title': ['Widget', 'Gadget'],
            'price': [9.99, 14.5]
        })
        df_users.to_sql('users', engine, index=False, if_exists='replace')
        df_products.to_sql('products', engine, index=False, if_exists='replace')

    if not EXCEL_FILE.exists():
        # Экспорт таблиц из БД в Excel
        engine = create_engine(f"sqlite:///{DB_FILE}")
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as writer:
            for table in ['users', 'products']:
                try:
                    df = pd.read_sql_table(table, engine)
                    df.to_excel(writer, sheet_name=table, index=False)
                except Exception:
                    pass


class ExcelChangeHandler(FileSystemEventHandler):
    def __init__(self, excel_path: Path, db_path: Path):
        super().__init__()
        self.excel_path = excel_path
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{self.db_path}")

    def on_modified(self, event):
        # watchdog иногда посылает несколько событий — фильтруем по файлу
        if Path(event.src_path).resolve() != self.excel_path.resolve():
            return
        print(f"Detected modification of {self.excel_path}. Applying to DB...")
        try:
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            # Резервные копии
            shutil.copy2(self.excel_path, BACKUP_DIR / f"data_{timestamp}.xlsx")
            if self.db_path.exists():
                shutil.copy2(self.db_path, BACKUP_DIR / f"data_{timestamp}.db")

            # Читаем все листы
            xl = pd.ExcelFile(self.excel_path)
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                # В простом прототипе просто заменяем таблицу
                df.to_sql(sheet, self.engine, index=False, if_exists='replace')
                print(f"Applied sheet '{sheet}' -> table '{sheet}' (rows: {len(df)})")

            print("Sync completed.")
        except Exception as e:
            print("Error during sync:", e)


def watch_loop():
    event_handler = ExcelChangeHandler(EXCEL_FILE, DB_FILE)
    observer = Observer()
    observer.schedule(event_handler, str(EXCEL_FILE.parent), recursive=False)
    observer.start()
    print(f"Watching {EXCEL_FILE} for changes. Open it in Excel, edit and save to sync.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == '__main__':
    ensure_sample_data()
    watch_loop()
