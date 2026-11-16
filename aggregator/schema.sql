-- Operations Record schema (prototype).
--
-- Written in portable SQL so it can move from SQLite to PostgreSQL:
--   * times are INTEGER seconds since the Unix epoch, UTC
--   * JSON is stored as TEXT (JSONB in PostgreSQL)
--   * "INTEGER PRIMARY KEY" becomes "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
-- Not modelled here: per-subsystem write roles (proposal Sec. 3.2). SQLite has no roles.
--
-- Rows are append-only. A correction is a new entry that names the one it supersedes.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Detector elements. parent_id is the detector-side hierarchy.
CREATE TABLE element (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    kind      TEXT NOT NULL,
    parent_id INTEGER REFERENCES element (id)
);

-- Service-side relations that cut across the hierarchy,
-- e.g. readout box --powered_by--> low-voltage supply.
CREATE TABLE element_relation (
    element_id INTEGER NOT NULL REFERENCES element (id),
    related_id INTEGER NOT NULL REFERENCES element (id),
    relation   TEXT NOT NULL,
    PRIMARY KEY (element_id, related_id, relation)
);

-- The common envelope (see utils/entry.py).
CREATE TABLE entry (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL,
    record_class     TEXT NOT NULL CHECK (record_class IN ('MS', 'QA', 'HI')),
    kind             TEXT NOT NULL CHECK (kind IN ('state', 'point', 'report', 'feature')),
    type             TEXT NOT NULL,
    element_id       INTEGER NOT NULL REFERENCES element (id),
    t_start          INTEGER NOT NULL,
    t_end            INTEGER,
    known_at         INTEGER NOT NULL,
    payload          TEXT NOT NULL,
    raw_ref          TEXT NOT NULL,
    producer         TEXT NOT NULL,
    producer_version TEXT NOT NULL,
    review_status    TEXT NOT NULL,
    supersedes       INTEGER REFERENCES entry (id),
    CHECK (known_at >= t_start)
);
CREATE INDEX entry_element_time ON entry (element_id, t_start);
CREATE INDEX entry_type_time ON entry (type, t_start);
CREATE INDEX entry_known_at ON entry (known_at);
CREATE INDEX entry_supersedes ON entry (supersedes);

-- Links between entries.
--   direct   - same element or interval, built from shared identifiers; context, not cause
--   indirect - expert reasoning: which observation supported which conclusion
CREATE TABLE link (
    id               INTEGER PRIMARY KEY,
    src_entry_id     INTEGER NOT NULL REFERENCES entry (id),
    dst_entry_id     INTEGER NOT NULL REFERENCES entry (id),
    link_type        TEXT NOT NULL CHECK (link_type IN ('direct', 'indirect')),
    relation         TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('proposed', 'confirmed', 'corrected', 'rejected')),
    rationale        TEXT NOT NULL,
    known_at         INTEGER NOT NULL,
    producer         TEXT NOT NULL,
    producer_version TEXT NOT NULL
);
CREATE INDEX link_src ON link (src_entry_id);
CREATE INDEX link_dst ON link (dst_entry_id);

-- Incidents. An open issue is an incident that is not yet closed.
-- The three labels are kept apart and each has its own known-at time:
--   certification   - was the recorded data usable
--   recovery_action - what restored running
--   confirmed_cause - why it happened (may never be known)
CREATE TABLE incident (
    id                     INTEGER PRIMARY KEY,
    title                  TEXT NOT NULL,
    element_id             INTEGER NOT NULL REFERENCES element (id),
    t_start                INTEGER NOT NULL,
    t_end                  INTEGER,
    known_at               INTEGER NOT NULL,
    recovery_action        TEXT,
    recovery_known_at      INTEGER,
    confirmed_cause        TEXT,
    cause_known_at         INTEGER,
    certification          TEXT,
    certification_known_at INTEGER,
    final_status           TEXT CHECK (final_status IN ('closed', 'unresolved')),
    closed_known_at        INTEGER
);
CREATE INDEX incident_element ON incident (element_id);

CREATE TABLE incident_entry (
    incident_id INTEGER NOT NULL REFERENCES incident (id),
    entry_id    INTEGER NOT NULL REFERENCES entry (id),
    role        TEXT NOT NULL,
    known_at    INTEGER NOT NULL,
    PRIMARY KEY (incident_id, entry_id)
);

-- Every read the orchestrator's tools make, so each claim is a re-runnable query.
CREATE TABLE query_log (
    id         INTEGER PRIMARY KEY,
    session    TEXT NOT NULL,
    tool       TEXT NOT NULL,
    args       TEXT NOT NULL,
    as_of      INTEGER NOT NULL,
    result_ids TEXT NOT NULL
);
