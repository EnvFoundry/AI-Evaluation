PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS catalog_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO catalog_metadata VALUES ('schema_version', '1.0');

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    question TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    benchmark_id TEXT NOT NULL,
    benchmark_name TEXT NOT NULL,
    benchmark_revision TEXT NOT NULL,
    system_id TEXT NOT NULL,
    system_name TEXT NOT NULL,
    system_revision TEXT NOT NULL,
    system_json TEXT NOT NULL,
    planned_trials INTEGER NOT NULL,
    recorded_trials INTEGER NOT NULL,
    created_at TEXT,
    manifest_json TEXT NOT NULL,
    status_counts_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_benchmark ON runs(benchmark_id);
CREATE INDEX IF NOT EXISTS runs_system ON runs(system_id);

CREATE TABLE IF NOT EXISTS experiment_runs (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    condition_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    PRIMARY KEY (experiment_id, condition_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    name TEXT NOT NULL,
    direction TEXT NOT NULL,
    descriptor_json TEXT NOT NULL,
    mean REAL,
    coverage_json TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS samples (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sample_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    weight REAL NOT NULL,
    slices_json TEXT NOT NULL,
    planned_trials INTEGER NOT NULL,
    PRIMARY KEY (run_id, sample_id)
);
CREATE INDEX IF NOT EXISTS samples_group ON samples(run_id, group_id);

CREATE TABLE IF NOT EXISTS trials (
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    trial INTEGER NOT NULL,
    status TEXT NOT NULL,
    elapsed_seconds REAL,
    usage_json TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sample_id, trial),
    FOREIGN KEY (run_id, sample_id) REFERENCES samples(run_id, sample_id)
);

CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    trial INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (run_id, sample_id, trial, metric),
    FOREIGN KEY (run_id, sample_id, trial) REFERENCES trials(run_id, sample_id, trial),
    FOREIGN KEY (run_id, metric) REFERENCES metrics(run_id, name)
);

-- These values use the same sample-mean implementation as native analysis.
-- A repeated attempt does not create a new independent sample.
CREATE TABLE IF NOT EXISTS sample_metrics (
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    mean REAL,
    observed_trials INTEGER NOT NULL,
    scored_trials INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    PRIMARY KEY (run_id, sample_id, metric),
    FOREIGN KEY (run_id, sample_id) REFERENCES samples(run_id, sample_id),
    FOREIGN KEY (run_id, metric) REFERENCES metrics(run_id, name)
);

CREATE VIEW IF NOT EXISTS run_metrics AS
SELECT r.run_id, r.path, r.benchmark_id, r.benchmark_name,
       r.benchmark_revision, r.system_id, r.system_name, r.system_revision,
       r.planned_trials, r.recorded_trials, m.name AS metric,
       m.direction, m.mean, m.coverage_json
FROM runs AS r JOIN metrics AS m ON r.run_id = m.run_id;
