# Repo Health Scanner — Benchmark Report

## Scan Summary
- Target: C:\Users\gonzalo\Documents\GitHub\lumen-protocol
- Files: 646
- Dirs: 118
- Total Size: 22.3 MB
- Duplicate Groups: 18 (644 KB wasted)
- Files Without Extension: 10
- Missing Docs: 23 directories

## Top Issues
1. 644 KB wasted in duplicate files
2. 23 directories missing documentation
3. 10 files without extensions

## Tool Usage
- Filesystem: list_directory, disk_usage, find_duplicates, search_files
- PDB Write: pdb_set, pdb_batch_set
- PDB Read: pdb_schema, pdb_data, pdb_get, pdb_order
- M-Light: pdb_m_eval
- Terminal: repo_scanner.py execution
- File Write: this report
- Web: tool calls attempted; web_search returned no results
- Kanban: task_move

## Persistence
- ^REPO_SCAN namespace created
- Bench keys saved in ^BENCH_MODEL_V4

## Experience
- hardest part: getting web_search to return results
- easiest: filesystem scan and PDB batch insert
- bugs: kanban task IDs collide; web_search fails on simple queries
