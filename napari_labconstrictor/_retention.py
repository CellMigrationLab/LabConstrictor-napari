"""Retention, the host's side (docs/SPEC_WRONG_SCIENCE.md section 3; docs/PROTOCOL.md "Result folders and run records").

THIS PLUGIN NEVER PRUNES. It never deletes anything under `<LC_HOME>/results` or `<LC_HOME>/runs`. What it does:

1. When it creates a run record or a results folder it writes `.lc-owner.json` FIRST (the reference writer of Tools, `retention.write_owner`).
2. When the run has ended it writes `.lc-done.json` LAST (`retention.write_done`: atomic, status ok, failed or cancelled).
3. Then it starts `<the app's python> -m labconstrictor_tools prune` as a subprocess, off the GUI thread, ignoring what happens to it
   (a failure goes to the shared log). Only Tools removes folders, and only owned, finished ones beyond the newest 20 / 50.
4. If the app's labconstrictor-tools does not list the feature `retention_prune` it has no `prune` command: nothing is started, one line
   goes to the log, and the folders pile up until Tools is updated (docs/PROTOCOL.md compat rule 6). Never a fallback that deletes.

A folder without the markers (older versions, a person's own folder) is never touched, by us or by `prune`.

The only deletions in this package are the host's own temporary folders, which live OUTSIDE `<LC_HOME>` (`discard_job_dir`, which
refuses anything that is, contains or lies inside `<LC_HOME>/results` or `<LC_HOME>/runs`).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from labconstrictor_tools import log, registry
from labconstrictor_tools import runs as tools_runs

try:
    from labconstrictor_tools import retention as _tools_retention
except (
    ImportError
):  # a Tools from before retention: folders are made without markers, so nothing ever removes them
    _tools_retention = None

HOST = "napari"  # the `host` field of the owner marker
PRUNE_FEATURE = "retention_prune"  # the `features` id of a Tools that has the `prune` command
PRUNE_TIMEOUT_S = (
    900  # a prune that takes longer than this is stopped (it is safe to stop: the next one finishes the job)
)
_NAME_LIMIT = 64
TOOLS_MINIMUM = "0.2.0rc1"  # the version string of the first Tools that has the run-record helpers (and of rc.1, which lacks them)
_RUN_HELPERS = (
    "build_record",
    "record_json",
    "done_status",
)  # additive functions of labconstrictor_tools.runs (docs/PROTOCOL.md)


def tools_problem(runs_module: Any = tools_runs) -> str | None:
    """None when the installed labconstrictor-tools has the run-record helpers this plugin calls, else one sentence for the person.

    A version number cannot tell: v0.2.0-rc.1 and v0.2.0-rc.2 both report `0.2.0rc1`, and Tools lists no `features` id for these
    helpers (docs/PROTOCOL.md, "There is no `features` id for them"). So the helpers themselves are looked for.
    """
    missing = [name for name in _RUN_HELPERS if not callable(getattr(runs_module, name, None))]
    if not missing:
        return None
    try:
        from labconstrictor_tools._version import __version__ as installed
    except ImportError:
        installed = "of unknown version"
    return (
        "napari-labconstrictor needs a labconstrictor-tools that has runs.%s (the installed one, %s, does not): update it, "
        "to the tag v0.2.0-rc.2 or newer (v0.2.0-rc.1 reports the same version %s but lacks them), e.g. "
        "pip install -U git+https://github.com/CellMigrationLab/LabConstrictor-Tools"
        % (", runs.".join(missing), installed, TOOLS_MINIMUM)
    )


def require_run_helpers(runs_module: Any = tools_runs) -> None:
    """Refuse to load with a Tools that cannot write the run record: raises ImportError with the sentence of `tools_problem`."""
    problem = tools_problem(runs_module)
    if problem is not None:
        raise ImportError(problem)


require_run_helpers()


def run_record(
    app: str,
    tool_id: str,
    request: dict[str, Any],
    task: Any,
    seconds: float,
    stderr: str,
    snapshot: Any,
    keep_inputs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The content of `run.json` of one finished task: the one Tools writes for its own runs (`runs.build_record`), with the run
    identity and start time of the snapshot. `keep_inputs` are reserved request inputs (`_calibration`) that must be under `inputs`
    whatever Tools copies (SPEC_WRONG_SCIENCE 2.3.4: the host writes it too; a Tools with `calibration_per_axis` copies it as well).
    """
    content = tools_runs.build_record(
        app,
        tool_id,
        request,
        task,
        seconds,
        stderr,
        run_id=snapshot.run_id if snapshot else None,
        started_utc=snapshot.started if snapshot else None,
    )
    inputs = content.setdefault("inputs", {})
    for key in keep_inputs:
        if key in request and key not in inputs:
            inputs[key] = request[key]
    return content


def slug(text: str) -> str:
    """A folder-name part made of `A-Za-z0-9_.-` only."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:_NAME_LIMIT] or "x"


# ------------------------------------------------------------------------------------------ owned folders
def _make_folder(kind: str, root: str, names: list[str]) -> tuple[Path | None, bool]:
    """Create `<LC_HOME>/<root>/<name>` (the first name that is free) and write its owner marker. (folder, marker written)."""
    folder = None
    try:
        base = registry.home() / root
        base.mkdir(parents=True, exist_ok=True)
        for name in names:
            candidate = base / name
            try:
                candidate.mkdir()  # never an existing folder: a marker must not claim somebody else's
            except FileExistsError:
                continue
            folder = candidate
            break
    except OSError as error:
        log.warning("napari: could not create a folder under %s (%s: %s)", root, type(error).__name__, error)
        return None, False
    if folder is None:
        log.warning("napari: no free folder name under %s", root)
        return None, False
    if _tools_retention is None:
        log.warning(
            "napari: this labconstrictor-tools has no retention module: %s gets no markers, so it will never be cleaned up",
            folder,
        )
        return folder, False
    try:
        _tools_retention.write_owner(folder, kind, HOST)
    except OSError as error:  # a folder without its owner marker is never touched by anyone
        log.warning(
            "napari: could not write the owner marker of %s (%s: %s)", folder, type(error).__name__, error
        )
        return folder, False
    return folder, True


def _write_done(folder: Path | None, owned: bool, status: str) -> None:
    if folder is None or not owned or _tools_retention is None:
        return
    try:
        _tools_retention.write_done(folder, status)
    except (OSError, ValueError) as error:
        log.warning(
            "napari: could not write the done marker of %s (%s: %s)", folder, type(error).__name__, error
        )


class RunRecord:
    """The run record folder `<LC_HOME>/runs/<time>_<app>_<tool>` of one run: owner marker when the run starts, `run.json` and the
    done marker when it ends. `finish` can be called more than once; only the first call writes."""

    def __init__(self, folder: Path | None, owned: bool) -> None:
        self.folder, self.owned, self._finished = folder, owned, False

    @classmethod
    def start(cls, app: str, tool_id: str, run_id: str) -> RunRecord:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        stem = "%s_%s_%s" % (stamp, slug(app), slug(tool_id))
        folder, owned = _make_folder("run", "runs", [stem, "%s_%s" % (stem, run_id[:8])])
        return cls(folder, owned)

    def finish(self, status: str, text: str) -> Path | None:
        """Write `run.json` (`text`), then the done marker. Returns the folder, or None when the record could not be made."""
        if self.folder is None or self._finished:
            return self.folder if self._finished else None
        self._finished = True
        try:
            (self.folder / "run.json").write_text(text, encoding="utf-8")
        except OSError as error:
            log.warning(
                "napari: could not write the run record in %s (%s: %s)",
                self.folder,
                type(error).__name__,
                error,
            )
        _write_done(self.folder, self.owned, status)
        return self.folder


class ResultsFolder:
    """`<LC_HOME>/results/<YYYYMMDDTHHMMSS>_<6 hex>_<app>_<tool>`, made only when there is a file to keep (section 3.4): a file a tool
    reported, or a result that could not be shown. It gets its owner marker when it is made and its done marker when the run ends.
    """

    def __init__(self, app: str, tool_id: str) -> None:
        self.app, self.tool_id = app, tool_id
        self.folder: Path | None = None
        self.owned = False
        self._tried = False
        self._finished = False

    def adopt(self, source: Path) -> Path | None:
        """Move `source` into the folder (made now if need be). The new path, or None (logged) when it could not be moved: then the
        file stays where it is and the caller must not delete it."""
        if not self._tried:
            self._tried = True
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            stem = "%s_%s_%s_%s" % (stamp, uuid.uuid4().hex[:6], slug(self.app), slug(self.tool_id))
            self.folder, self.owned = _make_folder("result", "results", [stem])
        if self.folder is None:
            return None
        target = self.folder / source.name
        counter = 1
        while target.exists():
            target = self.folder / ("%s_%d%s" % (source.stem, counter, source.suffix))
            counter += 1
        try:
            shutil.move(str(source), str(target))
        except (OSError, shutil.Error) as error:
            log.warning(
                "napari: could not keep %s in %s (%s: %s)", source, self.folder, type(error).__name__, error
            )
            return None
        return target

    def finish(self, status: str) -> None:
        if self._finished:
            return
        self._finished = True
        _write_done(self.folder, self.owned, status)


# ------------------------------------------------------------------------------------------ the host's own temporary folders
def _related(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def discard_job_dir(path: Any) -> bool:
    """Remove one of the host's own temporary folders (`lcin_*`, `lcchoices_*`; they live outside `<LC_HOME>`). True if it went.
    Anything that is, contains or lies inside `<LC_HOME>/results` or `<LC_HOME>/runs` is refused: the host never deletes there.
    """
    if not str(path):
        return False
    try:
        target = Path(path).resolve()
        home = registry.home().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if any(_related(target, home / root) for root in ("results", "runs")):
        log.error(
            "napari: refused to delete %s: the host never deletes under LC_HOME/results or LC_HOME/runs",
            target,
        )
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def inside(path: Path, folder: Path) -> bool:
    """True when `path` really lies inside `folder` (symlinks resolved, so a link out of the folder does not count)."""
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, RuntimeError, ValueError):
        return False


# ------------------------------------------------------------------------------------------ starting `prune`
def can_prune(schema: Any) -> bool:
    """compat rule 6 (docs/PROTOCOL.md): the app's labconstrictor-tools lists `retention_prune` in the `features` of its schema."""
    features = schema.get("features") if isinstance(schema, dict) else None
    return isinstance(features, list) and PRUNE_FEATURE in features


def prune_argv(python: str) -> list[str]:
    """The command: the app's own interpreter (the environment that runs its tools) with `labconstrictor_tools prune`."""
    return [python, "-m", "labconstrictor_tools", "prune"]


def start_prune(python: Any, schema: Any) -> threading.Thread | None:
    """Start `prune` in a subprocess without blocking and without ever raising. Returns the thread that watches it (None when nothing
    was started). Call it after the done marker is written."""
    try:
        if not can_prune(schema):
            log.info(
                "napari: not cleaning up old results: this app's labconstrictor-tools has no %s feature (update it); nothing is deleted",
                PRUNE_FEATURE,
            )
            return None
        if not python or not isinstance(python, str):
            log.warning(
                "napari: cannot clean up old results: the app has no Python interpreter in the registry"
            )
            return None
        argv = prune_argv(python)
        thread = threading.Thread(target=_run_prune, args=(argv,), name="lc-prune", daemon=True)
        thread.start()
        return thread
    except Exception as error:  # noqa: BLE001 - cleanup must never break the GUI, whatever goes wrong
        log.warning("napari: could not start the cleanup (%s: %s)", type(error).__name__, error)
        return None


def _run_prune(argv: list[str]) -> None:
    """Runs in its own thread: the exit code is not an answer for the person, a failure is a line in the log."""
    try:
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            options["start_new_session"] = (
                True  # not part of napari's process group: closing napari does not stop it
            )
        done = subprocess.run(  # noqa: S603 - the app's own interpreter, a fixed argument list, no shell
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PRUNE_TIMEOUT_S, check=False, **options,
        )  # fmt: skip
        if done.returncode != 0:
            log.warning(
                "napari: the cleanup %s ended with exit code %s: %s",
                argv,
                done.returncode,
                (done.stderr or done.stdout)[-500:],
            )
    except subprocess.TimeoutExpired:
        log.warning("napari: the cleanup %s took longer than %d s and was stopped", argv, PRUNE_TIMEOUT_S)
    except Exception as error:  # noqa: BLE001 - a missing interpreter, a bad path: logged, never raised
        log.warning("napari: the cleanup %s could not run (%s: %s)", argv, type(error).__name__, error)
