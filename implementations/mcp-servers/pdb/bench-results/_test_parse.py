"""Quick test of SQL parsing"""
import re

line = "INSERT OR IGNORE INTO petmap_places (id, name, slug, type, address, municipality, municipality_slug, province, province_slug, community, community_slug, postal_code, latitude, longitude, geohash, phone, email, website, emergency_24h, species, is_enclosed, data_source, data_quality) VALUES ('osm-n178820970', 'Los Austrias', 'los-austrias-madrid', 'veterinary', '', 'Madrid', 'madrid', 'Madrid', 'madrid', 'Comunidad de Madrid', 'comunidad-de-madrid', NULL, 40.4152466, -3.7094269, 'ezjmgt6', NULL, NULL, NULL, 0, '[\"perros\",\"gatos\"]', 0, 'osm', 0.5);"

# Find VALUES — the values are between VALUES ( and );
idx = line.find("VALUES (")
if idx >= 0:
    raw = line[idx + 8:]  # skip "VALUES ("
    # Find matching closing paren
    depth = 0
    end = 0
    for i, ch in enumerate(raw):
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                end = i
                break
            depth -= 1
    vals_str = raw[:end]
    # Parse single-quoted strings
    vals = re.findall(r"'((?:[^']|'')*)'", vals_str)
    print(f"Fields: {len(vals)}")
    for i, v in enumerate(vals[:5]):
        print(f"  [{i}] {v}")
else:
    print("No VALUES found")
