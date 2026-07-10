-- PDB Edge — Initial schema
-- MUMPS-style ^GLOBAL storage on D1 (SQLite)

CREATE TABLE IF NOT EXISTS pdb_store (
    ns TEXT NOT NULL,
    subkey BLOB NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ns, subkey)
) WITHOUT ROWID;

-- Index for prefix/suffix queries (used by $ORDER and KILL)
CREATE INDEX IF NOT EXISTS idx_pdb_store_ns_subkey
    ON pdb_store (ns, subkey);

-- Index for namespace listing (pdb_ns_order)
CREATE INDEX IF NOT EXISTS idx_pdb_store_ns
    ON pdb_store (ns);
