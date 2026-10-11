import pytest

from resolution.intake import normalize_address


@pytest.mark.parametrize(
    ("raw", "street", "unit"),
    [
        ("123 Main Street", "123 MAIN ST", None),
        ("123 main st", "123 MAIN ST", None),
        ("456 Oak Avenue", "456 OAK AVE", None),
        ("7 River Road", "7 RIVER RD", None),
        ("9 Palm Drive", "9 PALM DR", None),
        ("11 Ocean Boulevard", "11 OCEAN BLVD", None),
        ("13 Magnolia Lane", "13 MAGNOLIA LN", None),
        ("15 Orange Court", "15 ORANGE CT", None),
        ("17 Park Circle", "17 PARK CIR", None),
        ("  123   Main   St. ", "123 MAIN ST", None),
        ("123 Main St, Apt 4B", "123 MAIN ST", "4B"),
        ("500 Ocean Blvd #101", "500 OCEAN BLVD", "101"),
        ("500 Ocean Blvd Unit 102", "500 OCEAN BLVD", "102"),
        ("500 Ocean Blvd STE 7", "500 OCEAN BLVD", "7"),
        ("22-B Elm Street", "22-B ELM ST", None),
    ],
)
def test_normalize_address(raw: str, street: str, unit: str | None) -> None:
    result = normalize_address(raw)
    assert result.street == street
    assert result.unit == unit
