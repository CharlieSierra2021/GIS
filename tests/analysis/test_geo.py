import math

from shapely.geometry import Point

from analysis.geo import buffer_m, distance_m

# DeLand city hall ~ (29.0283, -81.3031); Daytona Beach pier ~ (29.2286, -81.0054)
DELAND = Point(-81.3031, 29.0283)
PIER = Point(-81.0054, 29.2286)


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def test_known_distance_matches_haversine() -> None:
    expected = _haversine_m(*DELAND.coords[0], *PIER.coords[0])
    actual = distance_m(DELAND, PIER)
    assert abs(actual - expected) / expected < 0.02


def test_buffer_area_approx_circle() -> None:
    buffered = buffer_m(Point(-81.3, 29.0), 100)
    # Re-measure in EPSG:3087 via distance: buffer area ≈ π r² within 1%.
    from analysis.geo import to_measure

    area = to_measure(buffered).area
    assert abs(area - math.pi * 100**2) / (math.pi * 100**2) < 0.01
