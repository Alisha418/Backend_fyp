"""Derive reporting area (zone) from report coordinates — matches admin panel logic."""


def zone_from_coordinates(lat, lng):
    if lat is None or lng is None:
        return 'Unknown Zone'
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return 'Unknown Zone'

    # Pakistan
    if 31.0 <= lat <= 35.0 and 70.0 <= lng <= 75.0:
        if lat > 33.5:
            return 'North Zone'
        if lat < 31.5:
            return 'South Zone'
        if lng > 74.0:
            return 'East Zone'
        if lng < 73.0:
            return 'West Zone'
        return 'Central Zone'

    # Default (NYC-style)
    if lat > 40.78:
        return 'North Zone'
    if lat < 40.72:
        return 'South Zone'
    if lng > -73.98:
        return 'East Zone'
    if lng < -74.02:
        return 'West Zone'
    return 'Central Zone'
