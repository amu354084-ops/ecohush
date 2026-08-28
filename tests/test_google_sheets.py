import pytest

from app.services.google_sheets import sync_report_sections


class FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self.row_count = 100
        self.cleared = []
        self.updated = []

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)

    def update(self, values, cell):
        self.updated.append((values, cell))


class FakeSpreadsheet:
    def __init__(self):
        self.worksheets = {}

    def worksheet(self, title):
        return self.worksheets[title]

    def open_by_key(self, spreadsheet_id):
        return self

    def add_worksheet(self, title, rows, cols):
        worksheet = FakeWorksheet(title)
        self.worksheets[title] = worksheet
        return worksheet


@pytest.mark.asyncio
async def test_google_sheets_is_disabled_without_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_FILE", raising=False)
    monkeypatch.setattr("app.services.google_sheets._setting", lambda name: None)

    result = await sync_report_sections({"Продажи": [{"ID": 1}]})

    assert result == {"status": "disabled", "message": "Google Sheets не настроен"}


@pytest.mark.asyncio
async def test_google_sheets_failure_does_not_escape_to_erp(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "spreadsheet-id")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setattr("app.services.google_sheets._setting", lambda name: {
        "GOOGLE_SHEETS_SPREADSHEET_ID": "spreadsheet-id",
        "GOOGLE_SHEETS_CREDENTIALS_FILE": str(tmp_path / "missing.json"),
    }.get(name))

    result = await sync_report_sections({"Продажи": [{"ID": 1}]})

    assert result["status"] == "error"
    assert "не найден" in result["message"]


@pytest.mark.asyncio
async def test_google_sheets_writes_all_report_headers_and_clears_old_data(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    spreadsheet = FakeSpreadsheet()

    class FakeGspread:
        WorksheetNotFound = KeyError

        @staticmethod
        def authorize(value):
            return spreadsheet

    class FakeCredentials:
        @staticmethod
        def from_service_account_file(path, scopes):
            return object()

    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "spreadsheet-id")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setitem(__import__("sys").modules, "gspread", FakeGspread)
    google_module = type("GoogleModule", (), {"oauth2": type("Oauth2", (), {"service_account": type("ServiceAccount", (), {"Credentials": FakeCredentials})})})
    monkeypatch.setitem(__import__("sys").modules, "google", google_module)
    monkeypatch.setitem(__import__("sys").modules, "google.oauth2", google_module.oauth2)
    monkeypatch.setitem(__import__("sys").modules, "google.oauth2.service_account", google_module.oauth2.service_account)

    from app.services.google_sheets import REPORT_HEADERS

    sections = {title: [] for title in REPORT_HEADERS}
    result = await sync_report_sections(sections)

    assert result["status"] == "ok"
    assert result["updated_sections"] == list(REPORT_HEADERS)
    for title, headers in REPORT_HEADERS.items():
        worksheet = spreadsheet.worksheets[title]
        assert worksheet.cleared == ["A1:ZZ100"]
        assert worksheet.updated == [([headers], "A1")]
