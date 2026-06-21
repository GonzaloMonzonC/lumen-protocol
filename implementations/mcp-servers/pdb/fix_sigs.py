#!/usr/bin/env python3
"""Batch update tool function signatures in pdb_tools.py"""
import re

with open('pdb_tools.py', 'r') as f:
    content = f.read()

# Map old signatures → new signatures + extraction line
replacements = [
    # tool_order
    ('def tool_order(ns: str, subs: list, direction: int = 1) -> dict:\n    """$ORDER',
     'def tool_order(args: dict) -> dict:\n    ns = args["ns"]; subs = args["subs"]; direction = args.get("direction", 1)\n    """$ORDER'),
    # tool_data
    ('def tool_data(ns: str, subs: list) -> dict:\n    r"""$DATA',
     'def tool_data(args: dict) -> dict:\n    ns = args["ns"]; subs = args["subs"]\n    r"""$DATA'),
    # tool_kill
    ('def tool_kill(ns: str, subs: list) -> dict:\n    """KILL',
     'def tool_kill(args: dict) -> dict:\n    ns = args["ns"]; subs = args["subs"]\n    """KILL'),
    # tool_incr
    ('def tool_incr(ns: str, subs: list, increment: float = 1.0) -> dict:\n    """$INCREMENT',
     'def tool_incr(args: dict) -> dict:\n    ns = args["ns"]; subs = args["subs"]; increment = args.get("increment", 1.0)\n    """$INCREMENT'),
    # tool_merge
    ('def tool_merge(target_ns: str, target_subs: list,\n               source_ns: str, source_subs: list) -> dict:\n    """MERGE',
     'def tool_merge(args: dict) -> dict:\n    target_ns = args["target_ns"]; target_subs = args["target_subs"]; source_ns = args["source_ns"]; source_subs = args["source_subs"]\n    """MERGE'),
    # tool_query
    ('def tool_query(sql: str, params: list = None, limit: int = 100) -> dict:\n    """Execute',
     'def tool_query(args: dict) -> dict:\n    sql = args["sql"]; params = args.get("params"); limit = args.get("limit", 100)\n    """Execute'),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f'  Replaced: {old.split("(")[0]}')
    else:
        print(f'  NOT FOUND: {old.split("(")[0]}')

with open('pdb_tools.py', 'w') as f:
    f.write(content)
print('Done')
