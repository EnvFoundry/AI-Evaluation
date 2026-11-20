"""A queryable local index of native runs; observations stay at trial resolution."""

from __future__ import annotations

from collections import Counter
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import time

from .analysis import _coverage, _mean, _views
from .contracts import canonical_json, load_run


def _connect(path: str | Path, *, writable: bool = False) -> sqlite3.Connection:
    source = Path(path).resolve()
    new = not source.exists() or source.stat().st_size == 0
    if writable:
        source.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(source, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        if new:
            connection.executescript(files("ai_eval").joinpath("catalog.sql").read_text(encoding="utf-8"))
    else:
        connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)
        connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute("SELECT value FROM catalog_metadata WHERE key='schema_version'").fetchone()
        if version is None or version[0] != "1.0":
            raise ValueError("unsupported evaluation catalog version")
    except sqlite3.Error as exc:
        connection.close()
        raise ValueError("file is not an evaluation catalog") from exc
    except BaseException:
        connection.close()
        raise
    return connection


def _page(offset: int, limit: int) -> None:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit between 1 and 100")


def _insert_run(connection: sqlite3.Connection, path: Path, loaded: dict) -> dict:
    manifest, observations = loaded["manifest"], loaded["results"]
    run_id, benchmark, system = manifest["run_id"], manifest["benchmark"], manifest["system"]
    encoded = canonical_json(manifest)
    existing = connection.execute("SELECT manifest_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if existing is not None and existing[0] != encoded:
        raise ValueError(f"run {run_id} already has a different manifest in this catalog")
    status_counts = dict(Counter(row["status"] for row in observations))
    connection.execute("""INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id) DO UPDATE SET path=excluded.path,
            recorded_trials=excluded.recorded_trials, status_counts_json=excluded.status_counts_json""",
        (run_id, str(path), benchmark["id"], benchmark["name"], benchmark["revision"],
         manifest["system_id"], system["name"], system["revision"], canonical_json(system),
         manifest["planned_trials"], len(observations), manifest.get("created_at"), encoded,
         canonical_json(status_counts)))
    # Refreshing a partial run is transactional, including every derived value.
    for table in ("scores", "sample_metrics", "trials", "samples", "metrics"):
        connection.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
    trials = benchmark["protocol"]["trials"]
    connection.executemany("INSERT INTO samples VALUES (?,?,?,?,?,?)", [
        (run_id, sample["id"], sample.get("group", sample["id"]), float(sample.get("weight", 1)),
         canonical_json(sample.get("slices", {})), trials) for sample in manifest["samples"]])
    for descriptor in benchmark["metrics"]:
        name = descriptor["name"]
        samples, _ = _views(loaded, name)
        connection.execute("INSERT INTO metrics VALUES (?,?,?,?,?,?)", (
            run_id, name, descriptor["direction"], canonical_json(descriptor),
            _mean(samples), canonical_json(_coverage(samples))))
        connection.executemany("INSERT INTO sample_metrics VALUES (?,?,?,?,?,?,?)", [
            (run_id, sample["sample_id"], name, sample["mean"], sample["observed_trials"],
             sample["scored_trials"], int(sample["complete"])) for sample in samples])
    connection.executemany("INSERT INTO trials VALUES (?,?,?,?,?,?,?)", [
        (run_id, row["sample_id"], row["trial"], row["status"], float(row["elapsed_seconds"]) if row.get("elapsed_seconds") is not None else None,
         canonical_json(row.get("usage", {})), canonical_json(row)) for row in observations])
    connection.executemany("INSERT INTO scores VALUES (?,?,?,?,?)", [
        (run_id, row["sample_id"], row["trial"], name, float(value) if value is not None else None)
        for row in observations for name, value in row["scores"].items()])
    return {"run_id": run_id, "path": str(path), "recorded_trials": len(observations),
            "planned_trials": manifest["planned_trials"]}


def add_runs(database: str | Path, run_paths, *, experiment: dict | None = None) -> dict:
    """Insert or refresh native run snapshots, optionally attaching one experiment."""
    paths = [Path(path).resolve() for path in run_paths]
    loaded = [(path, load_run(path)) for path in paths]
    if not loaded and experiment is None:
        raise ValueError("provide at least one run")
    connection = _connect(database, writable=True)
    try:
        with connection:
            added = [_insert_run(connection, path, run) for path, run in loaded]
            if experiment is not None:
                connection.execute("""INSERT INTO experiments VALUES (?,?,?,?,?,?)
                    ON CONFLICT(experiment_id) DO UPDATE SET path=excluded.path,
                        status=excluded.status, manifest_json=excluded.manifest_json""", (
                    experiment["experiment_id"], experiment["name"], experiment.get("question", ""),
                    experiment["path"], experiment["status"], canonical_json(experiment)))
                for condition in experiment.get("conditions", []):
                    if condition.get("run_id") is not None:
                        connection.execute("INSERT OR REPLACE INTO experiment_runs VALUES (?,?,?)", (
                            experiment["experiment_id"], condition["id"], condition["run_id"]))
        return {"catalog_path": str(Path(database).resolve()), "runs": added,
                "experiment_id": experiment.get("experiment_id") if experiment else None}
    finally:
        connection.close()


def list_runs(database: str | Path, *, benchmark: str | None = None, system: str | None = None,
              experiment: str | None = None, metric: str | None = None,
              offset: int = 0, limit: int = 20) -> dict:
    """Find runs by benchmark/system text, experiment ID or exact metric name."""
    _page(offset, limit)
    conditions, parameters = [], []
    for label, value in (("benchmark", benchmark), ("system", system)):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{label} filter must be text")
            conditions.append(f"instr(lower(r.{label}_name),lower(?))>0")
            parameters.append(value)
    if experiment is not None:
        conditions.append("EXISTS (SELECT 1 FROM experiment_runs e WHERE e.run_id=r.run_id AND e.experiment_id=?)")
        parameters.append(experiment)
    if metric is not None:
        conditions.append("EXISTS (SELECT 1 FROM metrics m WHERE m.run_id=r.run_id AND m.name=?)")
        parameters.append(metric)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    connection = _connect(database)
    try:
        total = connection.execute("SELECT count(*) FROM runs r" + where, parameters).fetchone()[0]
        rows = connection.execute("""SELECT r.run_id, r.path, r.benchmark_id, r.benchmark_name,
            r.benchmark_revision, r.system_id, r.system_name, r.system_revision,
            r.planned_trials, r.recorded_trials, r.created_at, r.status_counts_json
            FROM runs r""" + where + " ORDER BY r.created_at,r.run_id LIMIT ? OFFSET ?",
            [*parameters, limit, offset]).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["status_counts"] = json.loads(item.pop("status_counts_json"))
            metric_rows = connection.execute("SELECT name,direction,mean,coverage_json FROM metrics WHERE run_id=? ORDER BY name",
                                             (item["run_id"],)).fetchall()
            item["metrics"] = [dict(name=m["name"], direction=m["direction"], mean=m["mean"],
                                    coverage=json.loads(m["coverage_json"])) for m in metric_rows
                               if metric is None or m["name"] == metric]
            items.append(item)
        return {"total": total, "offset": offset, "limit": limit, "items": items,
                "next_offset": offset + len(items) if offset + len(items) < total else None}
    finally:
        connection.close()


def query(database: str | Path, sql: str, *, params: list | None = None,
          offset: int = 0, limit: int = 20) -> dict:
    """Read a bounded page from a SELECT, including CTEs and native SQLite JSON functions."""
    _page(offset, limit)
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a SELECT query")
    if params is not None and (not isinstance(params, list) or
            any(type(value) not in (str, int, float, bool, type(None)) for value in params)):
        raise ValueError("params must be an array of SQL scalar values")
    canonical_json(params)
    statement = sql.strip().removesuffix(";").rstrip()
    connection = _connect(database)
    deadline = time.monotonic() + 5
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        cursor = connection.execute(f"SELECT * FROM ({statement}) LIMIT ? OFFSET ?", [*(params or []), limit + 1, offset])
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        items = [dict(row) for row in rows[:limit]]
        canonical_json(items)
        truncated = []
        for index, item in enumerate(items):
            for column, value in item.items():
                if isinstance(value, str) and len(value) > 4000:
                    item[column] = value[:4000]
                    truncated.append({"row": index, "column": column, "characters": len(value)})
        return {"columns": columns, "items": items, "offset": offset, "limit": limit,
                "next_offset": offset + limit if len(rows) > limit else None, "truncated_cells": truncated}
    except (sqlite3.Error, OverflowError) as exc:
        raise ValueError(f"catalog query could not run: {exc}") from exc
    finally:
        connection.close()
