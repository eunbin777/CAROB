"""Evaluation harness.

A single orchestration layer that runs the matrix

    (task, dataset, model, baseline, instance) → prediction → metric

with three engineering invariants:

  - **Resumable**: per-instance results are appended to JSONL on disk; a
    re-run skips instances whose ``(task, dataset, model, baseline,
    instance_id)`` already has a record.
  - **Parallel**: independent instances run concurrently in a thread pool;
    cache writes are serialised so JSONL stays append-safe.
  - **Reproducible**: every record carries the model id, baseline name,
    prediction, score and timestamp, so result tables are regenerable from
    the stored predictions alone.

The harness owns nothing task-specific. Each baseline is a small object
implementing the :class:`Baseline` protocol; the harness only knows how to
load instances, call ``baseline.predict``, score with ``task.metric``, and
write the record. New tasks or baselines plug in by implementing the
protocol — no harness change required.

Aggregation (mean + bootstrap 95% CI) and table rendering live in
``eval/aggregate.py``; this file is the runner.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable, Protocol

logger = logging.getLogger(__name__)

try:
    from tqdm import tqdm                                          # noqa: I001
except ImportError:                                                # pragma: no cover
    class tqdm:                                                    # type: ignore[no-redef]
        """No-op progress bar used when tqdm is not installed."""

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def update(self, n=1):
            pass

        def set_postfix(self, **kwargs):
            pass

__all__ = [
    "Baseline", "Task", "RunRecord", "Harness", "gold_view",
]


# ---------------------------------------------------------------------------
# protocols / records
# ---------------------------------------------------------------------------

class Baseline(Protocol):
    """A baseline knows how to map one task instance to a prediction.

    Attributes
    ----------
    name : str
        Stable identifier used in cache filenames and result tables.
    task : str
        One of ``"t1"``, ``"t2"``, ``"t3"`` — the task this baseline targets.
    requires_llm : bool
        Whether the baseline needs an ``llm_client`` at ``predict`` time.
        The harness uses this to skip LLM-cost work when no client is
        configured (or to plan parallelism around model rate limits).
    """
    name: str
    task: str
    requires_llm: bool

    def setup(self, dataset_state: dict) -> None:
        """Called once per ``(task, dataset)`` before any ``predict``.

        ``dataset_state`` carries shared objects (e.g. an org roster, a
        pre-built retrieval index) so a baseline can stash references
        without rebuilding them per instance. The baseline must not
        mutate ``dataset_state``; treat it as read-only context.
        """
        ...

    def predict(
        self, instance: dict, gold: dict, *,
        llm_client: Callable | None = None,
    ) -> dict:
        """Produce a prediction for one instance.

        ``instance`` is the JSONL record the model would see (the released
        instance files carry model-visible fields only). ``gold`` is the
        instance's gold record (see :func:`gold_view`), passed in so oracle
        baselines have access; non-oracle baselines must ignore it.

        Return shape is task-specific — the harness hands it off verbatim
        to ``task.metric``.
        """
        ...


@dataclass
class Task:
    """A scoring task — instances, gold, and the metric that scores both.

    ``metric(prediction, gold)`` receives the baseline's prediction and the
    instance's :func:`gold_view`, and returns a flat score dict.
    """
    name: str                          # "t1" | "t2" | "t3"
    instances_path: Path
    gold_path: Path
    metric: Callable[[dict, dict], dict[str, float]]


@dataclass
class RunRecord:
    """One ``(task, dataset, model, baseline, instance)`` result.

    Stored append-only as JSONL. ``error`` is set when the baseline raised;
    in that case ``prediction`` and ``score`` are empty.
    """
    task: str
    dataset: str
    model: str
    baseline: str
    instance_id: str
    prediction: dict = field(default_factory=dict)
    score: dict[str, float] = field(default_factory=dict)
    elapsed_ms: int = 0
    timestamp: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _index_by(records: Iterable[dict], key: str) -> dict[str, dict]:
    return {r[key]: r for r in records if key in r}


def gold_view(record: dict) -> dict:
    """The gold handed to ``baseline.predict`` and ``task.metric``.

    T1 / T2 gold records nest their labels under ``"gold"`` next to
    record-level fields (``queried_event_id``, ``stress_conditions``, ...);
    the nested block is merged into the top level so both are available
    (e.g. ``gold["authorized"]`` and ``gold["queried_event_id"]`` for T2).
    Flat records (T3) are returned as a copy.
    """
    labels = record.get("gold")
    if isinstance(labels, dict):
        return {**{k: v for k, v in record.items() if k != "gold"}, **labels}
    return dict(record)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class Harness:
    """Per-instance runner with disk-backed cache.

    Layout: ``results_dir/{task}__{dataset}__{model}__{baseline}.jsonl`` —
    one file per ``(task, dataset, model, baseline)`` cell, each line a
    :class:`RunRecord`. New runs append; existing instance_ids are skipped
    when ``resume=True``.
    """

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._write_locks: dict[Path, Lock] = {}

    def _cache_path(
        self, task: str, dataset: str, model: str, baseline: str,
    ) -> Path:
        # Sanitise / for compound model ids like "anthropic/claude-sonnet-4.6"
        safe_model = model.replace("/", "_")
        return self.results_dir / (
            f"{task}__{dataset}__{safe_model}__{baseline}.jsonl")

    def _lock_for(self, path: Path) -> Lock:
        if path not in self._write_locks:
            self._write_locks[path] = Lock()
        return self._write_locks[path]

    def _existing_ids(self, cache_path: Path) -> set[str]:
        """Instance ids with a *successful* record (``error`` is null).
        Errored records do not count as done, so a resumed run retries them."""
        if not cache_path.exists():
            return set()
        ids: set[str] = set()
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if not rec.get("error"):
                    ids.add(rec["instance_id"])
            except (json.JSONDecodeError, KeyError):
                continue
        return ids

    def _done_ids(self, cache_path: Path, *, resume: bool,
                  retry_errors: bool) -> set[str]:
        """Ids to skip for this cell.

        - ``resume=False``: nothing is skipped.
        - ``retry_errors=True`` (default): errored records are dropped from
          the cache file (rewritten in place) and their instances re-run,
          so the file never holds an error *and* a success for one id.
        - ``retry_errors=False``: any record, errored or not, marks the
          instance done.
        """
        if not resume:
            return set()
        if not retry_errors:
            return self._all_ids(cache_path)
        self._drop_errored(cache_path)
        return self._existing_ids(cache_path)

    def _all_ids(self, cache_path: Path) -> set[str]:
        if not cache_path.exists():
            return set()
        ids: set[str] = set()
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            try:
                ids.add(json.loads(line)["instance_id"])
            except (json.JSONDecodeError, KeyError):
                continue
        return ids

    def _drop_errored(self, cache_path: Path) -> int:
        """Remove errored records from ``cache_path``; returns how many."""
        if not cache_path.exists():
            return 0
        with self._lock_for(cache_path):
            kept: list[str] = []
            dropped = 0
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("error"):
                        dropped += 1
                        continue
                except json.JSONDecodeError:
                    pass                    # keep unparsable lines untouched
                kept.append(line)
            if dropped:
                tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
                tmp.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
                tmp.replace(cache_path)
        return dropped

    def _append(self, cache_path: Path, record: RunRecord) -> None:
        with self._lock_for(cache_path):
            with cache_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    # -----------------------------------------------------------------
    # main entry point
    # -----------------------------------------------------------------

    def run(
        self, task: Task, dataset: str, model: str, baseline: Baseline,
        *,
        instances: list[dict] | None = None,
        golds: list[dict] | None = None,
        dataset_state: dict | None = None,
        llm_client: Callable | None = None,
        max_workers: int = 1,
        resume: bool = True,
        limit: int | None = None,
        retry_errors: bool = True,
    ) -> list[RunRecord]:
        """Run one ``(task, dataset, model, baseline)`` cell.

        Parameters
        ----------
        task : Task
            Carries instances path, gold path, and metric.
        dataset : str
            Cell label recorded with each result, e.g. ``"orgbench"``.
        model : str
            Model identifier (recorded with each result). May be ``"none"``
            for deterministic baselines.
        baseline : Baseline
            The strategy to evaluate.
        instances, golds : optional
            Pre-loaded lists. If ``None``, loads from ``task.instances_path``
            and ``task.gold_path``.
        dataset_state : optional dict
            Shared context passed to ``baseline.setup`` (org roster, retriever
            indexes, etc.). Built once before per-instance dispatch.
        llm_client : optional callable
            Required when ``baseline.requires_llm`` is True. Signature is
            convention; baselines decide how to call it.
        max_workers : int
            Thread pool size. 1 for deterministic baselines; higher for
            LLM-bound work that benefits from concurrency.
        resume : bool
            If True (default), skip instances already in the cache file.
        limit : int, optional
            Process at most this many *new* instances; useful for quick checks.
        retry_errors : bool
            If True (default), errored records do not count as cached: they
            are removed from the cache file and their instances re-run.

        Returns
        -------
        list[RunRecord]
            Only the *newly produced* records this call appended. Older
            cached records remain on disk untouched.
        """
        if baseline.requires_llm and llm_client is None:
            raise ValueError(
                f"baseline {baseline.name} requires an LLM client but none "
                "was passed; pass llm_client=... or pick a non-LLM baseline")

        if instances is None:
            instances = _load_jsonl(task.instances_path)
        if golds is None:
            golds = _load_jsonl(task.gold_path)
        gold_index = _index_by(golds, "instance_id")

        cache_path = self._cache_path(task.name, dataset, model, baseline.name)
        done = self._done_ids(cache_path, resume=resume,
                              retry_errors=retry_errors)

        baseline.setup(dataset_state or {})

        # which instances need work
        pending = [inst for inst in instances if inst["instance_id"] not in done]
        if limit is not None:
            pending = pending[:limit]
        if not pending:
            return []

        new_records: list[RunRecord] = []
        new_records_lock = Lock()

        def _one(inst: dict) -> RunRecord:
            iid = inst["instance_id"]
            gold = gold_view(gold_index.get(iid, {}))
            t0 = time.time()
            try:
                pred = baseline.predict(inst, gold, llm_client=llm_client)
                score = task.metric(pred, gold)
                rec = RunRecord(
                    task=task.name, dataset=dataset, model=model,
                    baseline=baseline.name, instance_id=iid,
                    prediction=pred, score=score,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:                           # noqa: BLE001
                rec = RunRecord(
                    task=task.name, dataset=dataset, model=model,
                    baseline=baseline.name, instance_id=iid,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                    error=f"{type(exc).__name__}: {exc}",
                )
                traceback.print_exc()
            self._append(cache_path, rec)
            with new_records_lock:
                new_records.append(rec)
            return rec

        desc = f"{baseline.name} × {model}"
        bar_fmt = ("{l_bar}{bar}| {n_fmt}/{total_fmt} "
                   "[{elapsed}<{remaining}, {rate_fmt}{postfix}]")
        n_err = 0
        if max_workers <= 1:
            with tqdm(total=len(pending), desc=desc, unit="inst",
                      bar_format=bar_fmt) as pbar:
                for inst in pending:
                    rec = _one(inst)
                    if rec.error:
                        n_err += 1
                        pbar.set_postfix(errs=n_err)
                    pbar.update(1)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_one, inst) for inst in pending]
                with tqdm(total=len(futures), desc=desc, unit="inst",
                          bar_format=bar_fmt) as pbar:
                    for fut in as_completed(futures):
                        rec = fut.result()
                        if rec.error:
                            n_err += 1
                            pbar.set_postfix(errs=n_err)
                        pbar.update(1)

        return new_records

    # -----------------------------------------------------------------
    # flat-pool runner: all (baseline, model, instance) tasks share one pool
    # -----------------------------------------------------------------

    def run_flat(
        self, task: Task, dataset: str,
        cells: list[tuple[str, Baseline, Callable | None]],
        *,
        instances: list[dict] | None = None,
        golds: list[dict] | None = None,
        dataset_state: dict | None = None,
        max_workers: int = 64,
        resume: bool = True,
        limit: int | None = None,
        retry_errors: bool = True,
    ) -> dict[tuple[str, str], list[RunRecord]]:
        """Dispatch every (baseline, model, instance) task through one shared
        thread pool, so a slow cell (e.g. a reasoning model whose calls take
        tens of seconds) does not block faster cells from making progress.

        ``cells`` is a list of ``(model, baseline, llm_client_or_None)``.
        Per-file appends are already thread-safe via :meth:`_append`'s lock,
        and instances already on disk are skipped, so this composes with
        earlier partial runs.
        """
        if instances is None:
            instances = _load_jsonl(task.instances_path)
        if golds is None:
            golds = _load_jsonl(task.gold_path)
        gold_index = _index_by(golds, "instance_id")

        # setup each unique baseline once (idempotent; stateless predict())
        seen_setup: set[str] = set()
        for _, baseline, _ in cells:
            if baseline.name not in seen_setup:
                baseline.setup(dataset_state or {})
                seen_setup.add(baseline.name)

        # build flat work queue across cells
        work: list[tuple[str, Baseline, Callable | None, dict, Path]] = []
        new_records: dict[tuple[str, str], list[RunRecord]] = {}
        for model, baseline, llm in cells:
            key = (baseline.name, model)
            new_records[key] = []
            if baseline.requires_llm and llm is None:
                continue
            cache_path = self._cache_path(
                task.name, dataset, model, baseline.name)
            done = self._done_ids(cache_path, resume=resume,
                                  retry_errors=retry_errors)
            pending = [i for i in instances if i["instance_id"] not in done]
            if limit is not None:
                pending = pending[:limit]
            for inst in pending:
                work.append((model, baseline, llm, inst, cache_path))

        nr_lock = Lock()

        def _one(item) -> RunRecord:
            model, baseline, llm, inst, cache_path = item
            iid = inst["instance_id"]
            gold = gold_view(gold_index.get(iid, {}))
            t0 = time.time()
            try:
                pred = baseline.predict(inst, gold, llm_client=llm)
                score = task.metric(pred, gold)
                rec = RunRecord(
                    task=task.name, dataset=dataset, model=model,
                    baseline=baseline.name, instance_id=iid,
                    prediction=pred, score=score,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:                           # noqa: BLE001
                rec = RunRecord(
                    task=task.name, dataset=dataset, model=model,
                    baseline=baseline.name, instance_id=iid,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                    error=f"{type(exc).__name__}: {exc}",
                )
                traceback.print_exc()
            self._append(cache_path, rec)
            with nr_lock:
                new_records[(baseline.name, model)].append(rec)
            return rec

        if not work:
            logger.info("flat pool: nothing to do (all cells fully cached)")
            return new_records

        bar_fmt = ("{l_bar}{bar}| {n_fmt}/{total_fmt} "
                   "[{elapsed}<{remaining}, {rate_fmt}{postfix}]")
        n_err = 0
        n_cells = sum(1 for k, v in new_records.items())
        logger.info("flat pool: %d instances across %d cells, %d workers",
                    len(work), n_cells, max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_one, w) for w in work]
            with tqdm(total=len(futures), desc="flat",
                      unit="inst", bar_format=bar_fmt) as pbar:
                for fut in as_completed(futures):
                    rec = fut.result()
                    if rec.error:
                        n_err += 1
                        pbar.set_postfix(errs=n_err)
                    pbar.update(1)

        return new_records

    # -----------------------------------------------------------------
    # convenience: matrix runner
    # -----------------------------------------------------------------

    def run_matrix(
        self,
        task: Task, dataset: str,
        *,
        models: list[str],
        baselines: list[Baseline],
        dataset_state: dict | None = None,
        llm_factory: Callable[[str], Callable] | None = None,
        max_workers: int = 4,
        resume: bool = True,
        limit: int | None = None,
        retry_errors: bool = True,
    ) -> dict[tuple[str, str], int]:
        """Run a full ``models × baselines`` matrix for one ``(task, dataset)``.

        ``llm_factory`` is a callable taking a model id and returning that
        model's chat function (so per-model API keys / endpoints stay local
        to the factory). It is invoked once per (model, baseline) cell, and
        only when ``baseline.requires_llm`` is True.

        Returns ``{(model, baseline_name): n_new_records}``.
        """
        # share loaded instances/gold across cells for speed
        instances = _load_jsonl(task.instances_path)
        golds = _load_jsonl(task.gold_path)
        counts: dict[tuple[str, str], int] = {}
        for baseline in baselines:
            if baseline.task != task.name:
                continue
            for model in models:
                if baseline.requires_llm and llm_factory is None:
                    raise ValueError(
                        f"baseline {baseline.name} requires an LLM but no "
                        "llm_factory was provided")
                llm = llm_factory(model) if (llm_factory and baseline.requires_llm) else None
                new = self.run(
                    task, dataset, model, baseline,
                    instances=instances, golds=golds,
                    dataset_state=dataset_state, llm_client=llm,
                    max_workers=max_workers, resume=resume, limit=limit,
                    retry_errors=retry_errors,
                )
                counts[(model, baseline.name)] = len(new)
        return counts

    # -----------------------------------------------------------------
    # results readback
    # -----------------------------------------------------------------

    def load_records(
        self, task: str, dataset: str,
        model: str | None = None, baseline: str | None = None,
    ) -> list[RunRecord]:
        """Read RunRecords back from cache for analysis.

        Pass ``model=None`` / ``baseline=None`` to fetch every matching cell.
        """
        out: list[RunRecord] = []
        for p in self.results_dir.glob(f"{task}__{dataset}__*__*.jsonl"):
            parts = p.stem.split("__")
            if len(parts) != 4:
                continue
            _, _, file_model, file_baseline = parts
            file_model = file_model.replace("_", "/", 1) if "_" in file_model else file_model
            if model is not None and file_model != model.replace("/", "_"):
                if file_model.replace("/", "_") != model.replace("/", "_"):
                    continue
            if baseline is not None and file_baseline != baseline:
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    out.append(RunRecord(**d))
                except (json.JSONDecodeError, TypeError):
                    continue
        return out
