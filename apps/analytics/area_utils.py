"""Reporting area labels from address/locality — aligned with map hotspot display."""

import re

_COORD_LABEL_RE = re.compile(
    r'^Location\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)$',
    re.IGNORECASE,
)

_ZONE_LABELS = frozenset({
    'north zone', 'south zone', 'east zone', 'west zone', 'central zone', 'unknown zone',
})

_SKIP_TOKENS = frozenset({
    'pakistan', 'punjab', 'sindh', 'khyber pakhtunkhwa', 'balochistan', 'ict',
    'usa', 'united states', 'ny', 'new york',
})


def dedupe_location_parts(value: str) -> str:
    raw = (value or '').strip()
    if not raw:
        return raw
    parts = [p.strip() for p in re.split(r'[,;]', raw) if p.strip()]
    out: list[str] = []
    last_lower = ''
    for part in parts:
        pl = part.lower()
        if pl == last_lower:
            continue
        out.append(part)
        last_lower = pl
    return ', '.join(out)


def approximate_area_from_coordinates(lat: float, lng: float) -> str:
    if 31.35 <= lat <= 31.75 and 72.95 <= lng <= 74.15:
        if 31.41 <= lat <= 31.43 and 73.08 <= lng <= 73.10:
            return 'D Ground, Civil Lines, Faisalabad'
        if 31.43 <= lat <= 31.47 and 73.05 <= lng <= 73.10:
            return 'Peoples Colony, Faisalabad'
        if 31.45 <= lat <= 31.50 and 73.08 <= lng <= 73.15:
            return 'Madina Town, Faisalabad'
        if lat >= 31.7:
            return 'North Faisalabad, Punjab'
        if lat <= 31.5:
            return 'South Faisalabad, Punjab'
        if lng >= 74.0:
            return 'East Faisalabad, Punjab'
        if lng <= 73.5:
            return 'West Faisalabad, Punjab'
        return 'Faisalabad, Punjab'
    if 33.60 <= lat <= 33.80 and 72.80 <= lng <= 73.20:
        return 'Islamabad, ICT'
    if 31.40 <= lat <= 31.65 and 74.20 <= lng <= 74.50:
        if 31.510 <= lat <= 31.530 and 74.330 <= lng <= 74.360:
            return 'Gulberg III, Lahore'
        return 'Lahore, Punjab'
    if 24.80 <= lat <= 25.00 and 66.90 <= lng <= 67.20:
        return 'Karachi, Sindh'
    if 40.5 <= lat <= 41.0 and -74.5 <= lng <= -73.5:
        return 'New York City, USA'
    return 'Unknown Area'


def reporting_area_label(location_text: str | None) -> str:
    """Same granularity as map hotspots (up to 4 address parts, not 2)."""
    if not location_text or not str(location_text).strip():
        return 'Unknown Area'

    text = str(location_text).strip()
    if text.lower() in _ZONE_LABELS:
        return 'Unknown Area'

    coord_match = _COORD_LABEL_RE.match(text)
    if coord_match:
        lat = float(coord_match.group(1))
        lng = float(coord_match.group(2))
        return reporting_area_label(approximate_area_from_coordinates(lat, lng))

    parts = [
        p.strip()
        for p in dedupe_location_parts(text).split(',')
        if p.strip()
    ]
    filtered: list[str] = []
    for part in parts:
        low = part.lower()
        if low in _SKIP_TOKENS:
            continue
        if re.fullmatch(r'\d{4,6}', part):
            continue
        if low.startswith('location ('):
            continue
        if low in _ZONE_LABELS:
            continue
        filtered.append(part)

    if not filtered:
        return 'Unknown Area'
    return ', '.join(filtered[:4])


def _resolve_display_location(*, location_address=None, latitude=None, longitude=None) -> str:
    """Full readable address for chart/map (no truncation)."""
    from apps.reports.serializers import get_local_fallback, resolve_report_location_display_list

    class _ReportStub:
        pass

    stub = _ReportStub()
    stub.location_address = location_address
    stub.latitude = latitude
    stub.longitude = longitude

    label = (resolve_report_location_display_list(stub) or '').strip()
    if _COORD_LABEL_RE.match(label):
        try:
            lat = float(latitude)
            lng = float(longitude)
            label = get_local_fallback(lat, lng)
        except (TypeError, ValueError):
            pass
    if _COORD_LABEL_RE.match((label or '').strip()):
        try:
            lat = float(latitude)
            lng = float(longitude)
            label = approximate_area_from_coordinates(lat, lng)
        except (TypeError, ValueError):
            label = 'Unknown Area'

    deduped = dedupe_location_parts(label)
    return deduped or 'Unknown Area'


def reporting_area_for_report(*, location_address=None, latitude=None, longitude=None) -> str:
    """One chart/map row per distinct full address."""
    return _resolve_display_location(
        location_address=location_address,
        latitude=latitude,
        longitude=longitude,
    )


def severity_for_count(count: int, max_count: int) -> str:
    if count <= 0 or max_count <= 0:
        return 'low'
    ratio = count / max_count
    if ratio >= 0.67:
        return 'high'
    if ratio >= 0.34:
        return 'medium'
    return 'low'
