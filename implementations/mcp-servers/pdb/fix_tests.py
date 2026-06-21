#!/usr/bin/env python3
"""Update test_suite.py to use dict-style tool calls."""
with open('test_suite.py') as f:
    content = f.read()

replacements = [
    # tool_set
    ("PDB.tool_set('PATIENT', [42, 'name'], 'Juan')", "PDB.tool_set({'ns': 'PATIENT', 'subs': [42, 'name'], 'value': 'Juan'})"),
    ("PDB.tool_set('PATIENT', [42, 'age'], 35)", "PDB.tool_set({'ns': 'PATIENT', 'subs': [42, 'age'], 'value': 35})"),
    ("PDB.tool_set('PATIENT', [42, 'address'], {'city': 'Tarragona', 'zip': 43001})", "PDB.tool_set({'ns': 'PATIENT', 'subs': [42, 'address'], 'value': {'city': 'Tarragona', 'zip': 43001}})"),
    ("PDB.tool_set('PATIENT', [42], None)", "PDB.tool_set({'ns': 'PATIENT', 'subs': [42], 'value': None})"),
    ("PDB.tool_set('PATIENT_I2', subs, pid)", "PDB.tool_set({'ns': 'PATIENT_I2', 'subs': subs, 'value': pid})"),
    ("PDB.tool_set('ORDERS', [1], None)", "PDB.tool_set({'ns': 'ORDERS', 'subs': [1], 'value': None})"),
    ("PDB.tool_set('ORDERS', [1, 'item'], 'widget')", "PDB.tool_set({'ns': 'ORDERS', 'subs': [1, 'item'], 'value': 'widget'})"),
    ("PDB.tool_set('ORDERS', [1, 'item', 'qty'], 5)", "PDB.tool_set({'ns': 'ORDERS', 'subs': [1, 'item', 'qty'], 'value': 5})"),
    ("PDB.tool_set('ORDERS', [2], 'express')", "PDB.tool_set({'ns': 'ORDERS', 'subs': [2], 'value': 'express'})"),
    ("PDB.tool_set('ORDERS', [2, 'note'], 'fragile')", "PDB.tool_set({'ns': 'ORDERS', 'subs': [2, 'note'], 'value': 'fragile'})"),
    ("PDB.tool_set('TMP', [1, 'a'], 'x')", "PDB.tool_set({'ns': 'TMP', 'subs': [1, 'a'], 'value': 'x'})"),
    ("PDB.tool_set('TMP', [1, 'a', 'deep'], 'y')", "PDB.tool_set({'ns': 'TMP', 'subs': [1, 'a', 'deep'], 'value': 'y'})"),
    ("PDB.tool_set('TMP', [1, 'b'], 'z')", "PDB.tool_set({'ns': 'TMP', 'subs': [1, 'b'], 'value': 'z'})"),
    ("PDB.tool_set('SRC', [1, 'name'], 'Juan')", "PDB.tool_set({'ns': 'SRC', 'subs': [1, 'name'], 'value': 'Juan'})"),
    ("PDB.tool_set('SRC', [1, 'age'], 30)", "PDB.tool_set({'ns': 'SRC', 'subs': [1, 'age'], 'value': 30})"),
    ("PDB.tool_set('SRC', [1, 'scores', 'math'], 95)", "PDB.tool_set({'ns': 'SRC', 'subs': [1, 'scores', 'math'], 'value': 95})"),
    ("PDB.tool_set('LOG', ['2024-01-15', '10:00', 'event'], 'login')", "PDB.tool_set({'ns': 'LOG', 'subs': ['2024-01-15', '10:00', 'event'], 'value': 'login'})"),
    ("PDB.tool_set('LOG', ['2024-01-15', '10:05', 'event'], 'search')", "PDB.tool_set({'ns': 'LOG', 'subs': ['2024-01-15', '10:05', 'event'], 'value': 'search'})"),
    ("PDB.tool_set('LOG', ['2024-01-16', '09:00', 'event'], 'logout')", "PDB.tool_set({'ns': 'LOG', 'subs': ['2024-01-16', '09:00', 'event'], 'value': 'logout'})"),
    ("PDB.tool_set('TEST', ['a'], 1)", "PDB.tool_set({'ns': 'TEST', 'subs': ['a'], 'value': 1})"),
    ("PDB.tool_set('TEST', ['b'], 2)", "PDB.tool_set({'ns': 'TEST', 'subs': ['b'], 'value': 2})"),
    ("PDB.tool_set('BK', ['x'], 'data')", "PDB.tool_set({'ns': 'BK', 'subs': ['x'], 'value': 'data'})"),
    ("PDB.tool_set('DEEP', subs, 'bottom')", "PDB.tool_set({'ns': 'DEEP', 'subs': subs, 'value': 'bottom'})"),
    ("PDB.tool_set('UNI', ['\xf1\xf3a', '\u65e5\u672c\u8a9e', '\U0001f600'], 'unicode-test')", "PDB.tool_set({'ns': 'UNI', 'subs': ['\xf1\xf3a', '\u65e5\u672c\u8a9e', '\U0001f600'], 'value': 'unicode-test'})"),
    ("PDB.tool_set('LARGE', ['data'], large)", "PDB.tool_set({'ns': 'LARGE', 'subs': ['data'], 'value': large})"),

    # tool_get
    ("PDB.tool_get('PATIENT', [42, 'name'])", "PDB.tool_get({'ns': 'PATIENT', 'subs': [42, 'name']})"),
    ("PDB.tool_get('PATIENT', [99])", "PDB.tool_get({'ns': 'PATIENT', 'subs': [99]})"),
    ("PDB.tool_get('PATIENT', [99], default='N/A')", "PDB.tool_get({'ns': 'PATIENT', 'subs': [99], 'default': 'N/A'})"),
    ("PDB.tool_get('PATIENT', [42, 'age'])", "PDB.tool_get({'ns': 'PATIENT', 'subs': [42, 'age']})"),
    ("PDB.tool_get('TMP', [1, 'a'])", "PDB.tool_get({'ns': 'TMP', 'subs': [1, 'a']})"),
    ("PDB.tool_get('TMP', [1, 'a', 'deep'])", "PDB.tool_get({'ns': 'TMP', 'subs': [1, 'a', 'deep']})"),
    ("PDB.tool_get('TMP', [1, 'b'])", "PDB.tool_get({'ns': 'TMP', 'subs': [1, 'b']})"),
    ("PDB.tool_get('DST', [100, 'name'])", "PDB.tool_get({'ns': 'DST', 'subs': [100, 'name']})"),
    ("PDB.tool_get('DST', [100, 'age'])", "PDB.tool_get({'ns': 'DST', 'subs': [100, 'age']})"),
    ("PDB.tool_get('DST', [100, 'scores', 'math'])", "PDB.tool_get({'ns': 'DST', 'subs': [100, 'scores', 'math']})"),
    ("PDB.tool_get('EMPTY', ['x'])", "PDB.tool_get({'ns': 'EMPTY', 'subs': ['x']})"),

    # tool_order
    ("PDB.tool_order('PATIENT_I2', [''], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': [''], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Martinez'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Martinez'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', ''], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', ''], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Garcia'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Garcia'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Lopez'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Lopez'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Garcia', ''], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Garcia', ''], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Garcia', 'Juan'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Garcia', 'Juan'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Garcia', 'Maria'], 1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Garcia', 'Maria'], 'direction': 1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', ''], -1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', ''], 'direction': -1})"),
    ("PDB.tool_order('PATIENT_I2', ['Caballero', 'Lopez'], -1)", "PDB.tool_order({'ns': 'PATIENT_I2', 'subs': ['Caballero', 'Lopez'], 'direction': -1})"),
    ("PDB.tool_order('EMPTY', [''], 1)", "PDB.tool_order({'ns': 'EMPTY', 'subs': [''], 'direction': 1})"),

    # tool_data
    ("PDB.tool_data('ORDERS', [999])", "PDB.tool_data({'ns': 'ORDERS', 'subs': [999]})"),
    ("PDB.tool_data('ORDERS', [1, 'item'])", "PDB.tool_data({'ns': 'ORDERS', 'subs': [1, 'item']})"),
    ("PDB.tool_data('ORDERS', [1])", "PDB.tool_data({'ns': 'ORDERS', 'subs': [1]})"),
    ("PDB.tool_data('ORDERS', [2])", "PDB.tool_data({'ns': 'ORDERS', 'subs': [2]})"),

    # tool_kill
    ("PDB.tool_kill('TMP', [1, 'a'])", "PDB.tool_kill({'ns': 'TMP', 'subs': [1, 'a']})"),

    # tool_incr
    ("PDB.tool_incr('COUNTER', ['visits'], 1)", "PDB.tool_incr({'ns': 'COUNTER', 'subs': ['visits'], 'increment': 1})"),
    ("PDB.tool_incr('COUNTER', ['visits'], 5)", "PDB.tool_incr({'ns': 'COUNTER', 'subs': ['visits'], 'increment': 5})"),
    ("PDB.tool_incr('COUNTER', ['visits'], -1)", "PDB.tool_incr({'ns': 'COUNTER', 'subs': ['visits'], 'increment': -1})"),
    ("PDB.tool_incr('COUNTER', ['orders'], 1)", "PDB.tool_incr({'ns': 'COUNTER', 'subs': ['orders'], 'increment': 1})"),

    # tool_merge
    ("PDB.tool_merge('DST', [100], 'SRC', [1])", "PDB.tool_merge({'target_ns': 'DST', 'target_subs': [100], 'source_ns': 'SRC', 'source_subs': [1]})"),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
    else:
        print(f"  NOT FOUND: {old[:60]}")

with open('test_suite.py', 'w') as f:
    f.write(content)
print("Tests updated")
