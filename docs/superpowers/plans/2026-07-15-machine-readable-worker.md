# Machine-Readable Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JSON Lines event protocol and a thin, cancellable-by-parent Worker entry point that a future PySide6 desktop application can run without parsing human terminal text.

**Architecture:** `ear_param.events` owns event schema validation, durable JSONL writing, and optional stdout mirroring. The existing `scripts/run_full_pipeline.py` remains the only formal W2-to-W3 orchestrator; it receives optional event arguments and emits lifecycle events around its existing pipeline. `scripts/ear_analysis_worker.py` changes working directory to a selected project root, forces an isolated output root, enables durable events plus stdout mirroring, and delegates to that same orchestrator.

**Tech Stack:** Existing Python 3.14, standard-library JSON/pathlib/argparse, pandas-based current pipeline, pytest. No PySide6, VTK, geometry algorithm, data, or config change in this milestone.

## Global Constraints

- Existing commands that omit all new event/worker options retain their current parameters, default output locations, terminal summary, numerical behavior, and failure behavior.
- The Worker and future GUI must use `--output-root`; original `data/` and `config/` files remain read-only.
- Event JSON is UTF-8 JSONL, append-only, one object per line, and must not accept non-finite floats.
- Event status is progress information only; final PASS/WARNING/FAIL decisions remain sourced from existing formal CSV/JSON outputs.
- Do not stage, commit, switch branches, clean the worktree, or alter user landmark files.

---

### Task 1: Event Protocol Module

**Files:**
- Create: `ear_param/events.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Produces `EVENT_PREFIX = "@@EAR_EVENT@@"`.
- Produces `JsonlEventWriter(path: Path, *, mirror_stdout: bool = False)` with `emit(event: str, **fields: object) -> dict[str, object]`.
- Event payloads contain `event`, UTC `timestamp`, and only strict JSON-safe values.

- [ ] **Step 1: Write failing tests**

```python
def test_writer_appends_one_json_object_per_line(tmp_path: Path):
    from ear_param.events import JsonlEventWriter

    path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path)
    payload = writer.emit("stage_started", stage="REMESH", sample_tag="T076_L")

    assert payload["event"] == "stage_started"
    assert json.loads(path.read_text(encoding="utf-8"))["sample_tag"] == "T076_L"


def test_writer_rejects_nonfinite_payload(tmp_path: Path):
    from ear_param.events import JsonlEventWriter

    with pytest.raises(ValueError):
        JsonlEventWriter(tmp_path / "events.jsonl").emit("progress", value=float("nan"))
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/test_events.py -v --basetemp output/.pytest_events_red
```

Expected: import failure because `ear_param.events` does not exist.

- [ ] **Step 3: Implement the strict JSONL writer**

```python
EVENT_PREFIX = "@@EAR_EVENT@@"


class JsonlEventWriter:
    def __init__(self, path: Path, *, mirror_stdout: bool = False) -> None:
        self.path = Path(path)
        self.mirror_stdout = mirror_stdout

    def emit(self, event: str, **fields: object) -> dict[str, object]:
        payload = {"event": event, "timestamp": utc_timestamp(), **fields}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded + "\n")
            stream.flush()
        if self.mirror_stdout:
            print(f"{EVENT_PREFIX}{encoded}", flush=True)
        return payload
```

Use a private UTC timestamp helper and raise `ValueError` from strict JSON encoding.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest tests/test_events.py -v --basetemp output/.pytest_events_green
```

Expected: all tests PASS.

### Task 2: Pipeline Lifecycle Events

**Files:**
- Modify: `ear_param/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- `PipelineConfig` gains an additive final field `event_reporter: Callable[[str, dict[str, object]], None] | None = None`.
- The existing pipeline emits `sample_started`, `sample_finished`, `stage_started`, `stage_finished`, and `stage_error` without changing its reporter text or status logic.

- [ ] **Step 1: Write failing event-order tests**

```python
def test_pipeline_emits_sample_and_batch_events(tmp_path: Path):
    events: list[tuple[str, dict[str, object]]] = []
    config = PipelineConfig(..., event_reporter=lambda event, fields: events.append((event, fields)))

    result = run_pipeline(config, stage_functions=successful_stages())

    assert ("sample_started", {"sample_tag": "T076_L", "stage": "REMESH"}) in events
    assert any(event == "stage_finished" and fields["stage"] == "WELD" for event, fields in events)
    assert result.records.loc[0, "salvage"] == "PASS"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k emits -v --basetemp output/.pytest_pipeline_events_red
```

Expected: failure because `PipelineConfig` has no `event_reporter` or no events are emitted.

- [ ] **Step 3: Implement event helper and minimal call sites**

```python
def _emit(config: PipelineConfig, event: str, **fields: object) -> None:
    if config.event_reporter is not None:
        config.event_reporter(event, fields)
```

Emit before and after each existing remesh/QC/Weld/Alignment/GPA/fixed-reference stage. On existing exception paths emit `stage_error` with stage, sample tag when known, and `str(error)`. Do not derive new PASS/WARNING/FAIL values.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k emits -v --basetemp output/.pytest_pipeline_events_green
```

Expected: all selected tests PASS; existing pipeline tests remain unchanged.

### Task 3: Formal CLI Event Options

**Files:**
- Modify: `scripts/run_full_pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- New additive parser options: `--events-file PATH` and `--event-stdout`.
- `execute(args)` emits `run_started`, exactly one terminal `run_finished` with `COMPLETED` or `ERROR`, and preserves manifest lifecycle plus final text summary.

- [ ] **Step 1: Write failing execution tests**

```python
def test_execute_writes_durable_lifecycle_events(tmp_path: Path, monkeypatch):
    args = build_parser().parse_args(["--output-root", str(tmp_path / "run"),
                                      "--events-file", str(tmp_path / "run" / "events.jsonl")])
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: successful_result())

    cli.execute(args)

    events = [json.loads(line) for line in (tmp_path / "run" / "events.jsonl").read_text().splitlines()]
    assert events[0]["event"] == "run_started"
    assert events[-1] == {**events[-1], "event": "run_finished", "status": "COMPLETED"}
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k lifecycle_events -v --basetemp output/.pytest_cli_events_red
```

Expected: parser rejects the new options.

- [ ] **Step 3: Add optional writer wiring**

Construct `JsonlEventWriter` only when `args.events_file` is set. Pass a small adapter into `PipelineConfig.event_reporter`. Emit `run_started` after the isolated root is reserved and before `run_pipeline`; emit `run_finished` on both completion and error. When options are absent, do not create files or modify terminal output.

- [ ] **Step 4: Run GREEN and CLI help smoke test**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k lifecycle_events -v --basetemp output/.pytest_cli_events_green
python scripts/run_full_pipeline.py --help
```

Expected: lifecycle tests PASS; help includes both new options and all existing options.

### Task 4: Worker Entry Point

**Files:**
- Create: `scripts/ear_analysis_worker.py`
- Create: `tests/test_worker.py`

**Interfaces:**
- Worker command: `python scripts/ear_analysis_worker.py --project-root <root> --output-root <new-empty-root> [full-pipeline options]`.
- Worker changes into `project_root`, creates `<output-root>/events.jsonl`, enables stdout event mirroring, and delegates to `scripts.run_full_pipeline.execute`.
- It rejects missing `--output-root` and never writes `data/` or `config/`.

- [ ] **Step 1: Write failing worker argument tests**

```python
def test_worker_forces_scoped_event_file(tmp_path: Path, monkeypatch):
    import scripts.ear_analysis_worker as worker
    captured = {}
    monkeypatch.setattr(worker.pipeline_cli, "execute", lambda args: captured.update(vars(args)))

    assert worker.main(["--project-root", str(tmp_path), "--output-root", "output/pipeline_runs/demo"]) == 0
    assert captured["events_file"].endswith("output/pipeline_runs/demo/events.jsonl")
    assert captured["event_stdout"] is True
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/test_worker.py -v --basetemp output/.pytest_worker_red
```

Expected: import failure because worker does not exist.

- [ ] **Step 3: Implement thin delegation only**

Use `argparse` for `--project-root`, parse the remaining options with `pipeline_cli.build_parser()`, require `output_root`, set `events_file = output_root / "events.jsonl"`, set `event_stdout = True`, call `pipeline_cli.execute(args)`, return `0` on success and re-raise errors for the calling process.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest tests/test_worker.py -v --basetemp output/.pytest_worker_green
```

Expected: worker tests PASS.

### Task 5: Documentation and Regression Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-15-ear-analysis-desktop-design.md`
- Modify: `docs/superpowers/plans/2026-07-15-ear-analysis-desktop-roadmap.md`
- Create: `docs/桌面软件开发与运行说明.md`

- [ ] **Step 1: Update the current milestone state**

Mark run isolation/manifest as completed, document `events.jsonl` and the worker command, and state that the Worker does not replace direct CLI usage.

- [ ] **Step 2: Document the event contract**

Document the event prefix, required keys, event names, output location, and the rule that GUI final status comes from formal result files rather than progress events.

- [ ] **Step 3: Run documentation checks**

Run:

```powershell
rg -n "events.jsonl|ear_analysis_worker|output-root|EVENT" README.md docs
git diff --check
```

Expected: new worker/event documentation is discoverable and there are no whitespace errors.

- [ ] **Step 4: Run full regression suite**

Run:

```powershell
python -m pytest -q --basetemp output/.pytest_desktop_worker_full
```

Expected: all tests PASS; no existing command-line test regresses.

## Self-Review

- Every event is produced by the existing orchestration layer; no GUI code or duplicated QC logic is introduced.
- The Worker only delegates to `run_full_pipeline.execute` and requires isolated output.
- Options absent means no event file and no changed legacy output location.
- New `PipelineConfig` fields are appended after the existing positional contract.
- Worker, events, and docs are sufficient for the following PySide6 project/batch UI milestone but do not claim that a GUI exists yet.
