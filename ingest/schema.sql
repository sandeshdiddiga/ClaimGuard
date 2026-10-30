-- Reference data (read-only at runtime). Cases, lines, findings and calls live in data/state.db.
-- Built by `python -m ingest` from three CMS public-use files. Level II codes only: every code starts with
-- a letter, and the schema refuses anything else. Committed to the repo (no AMA content).

CREATE TABLE hcpcs (
    code              TEXT PRIMARY KEY CHECK (code GLOB '[A-Z]*'),
    short_description TEXT NOT NULL,
    long_description  TEXT NOT NULL,
    added_date        TEXT,           -- YYYYMMDD
    effective_date    TEXT,           -- YYYYMMDD
    termination_date  TEXT            -- YYYYMMDD; NULL while the code is live
) WITHOUT ROWID;

-- Part B drugs: Medicare payment limit per billing unit. Exact decimal strings, never floats.
CREATE TABLE drug_limits (
    code              TEXT PRIMARY KEY CHECK (code GLOB '[A-Z]*'),
    short_description TEXT NOT NULL,
    dosage            TEXT NOT NULL,  -- the billing-unit dose exactly as CMS wrote it, e.g. '1 MG'
    dose_value        TEXT,           -- parsed number ('1', '0.1'); NULL when dosage is not one amount + one unit
    dose_unit         TEXT,           -- parsed unit, upper case ('MG'); NULL together with dose_value
    payment_limit     TEXT,           -- dollars per billing unit ('0.167'); NULL when CMS lists none
    CHECK ((dose_value IS NULL) = (dose_unit IS NULL))
) WITHOUT ROWID;

-- Medically Unlikely Edits, facility outpatient hospital: the most units CMS expects per code per day.
CREATE TABLE mue (
    code      TEXT PRIMARY KEY CHECK (code GLOB '[A-Z]*'),
    mue_value INTEGER NOT NULL CHECK (mue_value >= 0),
    mai       INTEGER NOT NULL CHECK (mai IN (1, 2, 3)),  -- 1 line edit, 2 absolute DOS, 3 clinical DOS
    rationale TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
