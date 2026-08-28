import pytest

from app.services.localization import display_label


@pytest.mark.parametrize(
    ("internal_value", "expected"),
    [
        ("CASH", "Наличные"),
        ("BANK", "Наличные"),
        ("BANK_TRANSFER", "Наличные"),
        ("Sale payment", "Оплата продажи"),
        ("IN_TRANSIT", "В пути"),
        ("PRODUCTION_OUTPUT", "Выпуск продукции"),
        ("RAW", "Сырьё"),
    ],
)
def test_display_label_translates_internal_values(internal_value, expected):
    assert display_label(internal_value) == expected


def test_display_label_keeps_unknown_values_readable():
    assert display_label("custom value") == "custom value"
