"""Synthetic datasets with ground truth through the Napari dock widget (one-off run, family `synthetic`, host `napari`). Not part of the UI audit: it reuses the audit's
machinery (host window, fill of the form from a case, a real click on Run) to run EVERY case of a generated `cases.json` (tests/oneoff_2026-10/synthetic of the Tools repo) and
writes one report per dataset in the shape `check_ground_truth.py` reads, with `host_observed` (the text of every pixel-size box after the form was filled).

    LC_HOME=<registry> LC_APP=<name> LC_APP_TESTS=<synthetic folder of the app: cases.json, fixtures/, ground_truth.json> LC_EXPECT_NAPARI=listed \
    LC_SHOTS=<scratch for the audit's own matrix> LC_SYN_OUT=<reports folder> [LC_UI_INPUT=file] xvfb-run -a -s "-screen 0 1600x1000x24" python tests/ui_synthetic_napari.py

`LC_UI_INPUT=file` puts every image into the chooser's 'or file' row, so the HOST reads the calibration from the file (what a person who picks a file gets); the default `layer` opens
the fixture as a layer whose scale the audit computes from the TIFF tags. Cases whose values the form cannot hold (a bounded field refuses 1.5) are written to `not_expressible.json`
and are for the CLI/a person. Then: `python check_ground_truth.py ground_truth.json --reports <LC_SYN_OUT> --data <scratch> --with-host`."""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui_audit as ua  # noqa: E402
import ui_audit_core as core  # noqa: E402
import ui_audit_runs as runs  # noqa: E402
from ui_audit_core import AuditConfigError, Recorder, config_from_env, pump  # noqa: E402


def pixel_boxes(ctx: Any, tool: dict[str, Any]) -> dict[str, Any]:
    """What every pixel-size box of the form shows now: a number, or None for an empty box."""
    seen: dict[str, Any] = {}
    for param in tool["inputs"]:
        if param.get("pixel_size_of"):
            text = ctx.host.widget.gui[param["name"]].native.text().strip()
            try:
                seen[param["name"]] = float(text) if text else None
            except ValueError:
                seen[param["name"]] = text
    return seen


def main() -> int:
    try:
        cfg = config_from_env(os.environ)
    except AuditConfigError as error:
        sys.exit("ui_synthetic_napari: %s" % error)
    out = Path(os.environ["LC_SYN_OUT"])
    out.mkdir(parents=True, exist_ok=True)
    app = cfg.apps[0]
    core.HOST_VERSION = core.host_version()
    host = ua.open_host()
    rec = Recorder(app, cfg.shots, [])
    ctx = ua.build_ctx(host, cfg, app, rec)
    truth = json.loads((cfg.tests[app] / "ground_truth.json").read_text(encoding="utf-8"))
    primary = {d["primary_case"]: d["id"] for d in truth["datasets"] if d["primary_case"] is not None}
    w = host.widget
    w._discard_job_dir = lambda: None  # noqa: SLF001 - the result files stay on disk for the checker
    not_expressible: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for number, case in enumerate(ctx.cases):
        tool_id = case["tool"]
        if runs.never_run(tool_id) or "cancel_after_s" in case or case.get("skip"):
            continue
        report: dict[str, Any]
        started = time.time()
        try:
            runs.prepare(ctx, tool_id, case)
            observed = pixel_boxes(ctx, runs.tool_of(ctx, tool_id))
        except ValueError as problem:  # the form refuses the value itself
            not_expressible.append({"case": number, "dataset": primary.get(number), "tool": tool_id, "why": str(problem)[:300]})
            summary.append({"case": number, "dataset": primary.get(number), "tool": tool_id, "status": "NOT_EXPRESSIBLE", "why": str(problem)[:200]})
            print("CASE %03d NOT_EXPRESSIBLE %s %s" % (number, tool_id, str(problem)[:120]), flush=True)
            continue
        except Exception as problem:  # noqa: BLE001 - never stops the run
            report = {"status": "DRIVER_ERROR", "error": "%s: %s | %s" % (type(problem).__name__, problem, traceback.format_exc()[-300:])}
            observed = {}
        else:
            try:
                obs, task = runs.execute(ctx, tool_id, case, started + cfg.timeout)
                report = {
                    "status": task.status,
                    "seconds": round(time.time() - started, 2),
                    "error": task.error,
                    "code": task.code,
                    "status_text": obs.status_text,
                    "run_record": str(w.last_record) if w.last_record else None,
                }
                if task.status == "COMPLETE":
                    report["results"] = list(task.outputs["results"])
            except Exception as problem:  # noqa: BLE001
                report = {"status": "DRIVER_ERROR", "error": "%s: %s | %s" % (type(problem).__name__, problem, traceback.format_exc()[-300:])}
        report["host_observed"] = observed
        text = json.dumps(report, indent=2, default=str)
        (out / ("case_%03d.json" % number)).write_text(text, encoding="utf-8")
        if number in primary:
            (out / (primary[number] + ".json")).write_text(text, encoding="utf-8")
        problems = runs_judge(case, report)
        summary.append({"case": number, "dataset": primary.get(number), "tool": tool_id, "status": report["status"], "code": report.get("code"), "problems": problems})
        print("CASE %03d %-10s %-28s %s" % (number, report["status"], tool_id, "OK" if not problems else "MISMATCH " + "; ".join(problems)[:200]), flush=True)
        pump(0.1)
    # datasets that are judged by what the form shows (no case, `host_checks` only): the file goes into the image's 'or file' row, then the pixel-size boxes are read
    for data in truth["datasets"]:
        if data["primary_case"] is not None or not data.get("host_checks"):
            continue
        if all(str(c.get("param", "")).startswith("blobs_channel_") for c in data["host_checks"]):
            report = channel_blob_counts(ctx, cfg.tests[app], data, started=time.time(), timeout=cfg.timeout)
            (out / (data["id"] + ".json")).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print("HOSTONLY %s %s %s" % (data["id"], report["host_observed"], report.get("error", "")), flush=True)
            continue
        try:
            tool = next(t for t in ctx.schema["tools"] if any(p.get("pixel_size_of") for p in t["inputs"]))
            runs.prepare(ctx, tool["id"], {"inputs": {}})
            image_param = next(p["pixel_size_of"] for p in tool["inputs"] if p["name"] == data["host_checks"][0]["param"])
            w.file_sources[image_param].value = cfg.tests[app] / data["files"][0]
            pump(0.5)
            report = {"status": "HOST_ONLY", "host_observed": pixel_boxes(ctx, tool)}
        except Exception as problem:  # noqa: BLE001
            report = {"status": "DRIVER_ERROR", "error": "%s: %s" % (type(problem).__name__, problem), "host_observed": {}}
        (out / (data["id"] + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("HOSTONLY %s %s" % (data["id"], report["host_observed"]), flush=True)
    (out / "data_dir.txt").write_text(str(getattr(ctx, "scratch", cfg.tests[app])), encoding="utf-8")   # the folder the cases ran in (a copy): files a tool wrote are there, give it to check_ground_truth.py --data
    (out / "cases_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "not_expressible.json").write_text(json.dumps(not_expressible, indent=2), encoding="utf-8")
    print("SUMMARY %d cases, %d differ from their own expectation, %d not expressible in the form" % (len(summary), sum(1 for s in summary if s.get("problems")), len(not_expressible)), flush=True)
    host.viewer.close()
    pump(0.5)
    sys.stdout.flush()
    os._exit(0)


def channel_blob_counts(ctx: Any, tests: Path, data: dict[str, Any], started: float, timeout: float) -> dict[str, Any]:
    """The channel chooser through the real form (alpha.3 driver): the stack/RGB file goes into the image's 'or file' row, each colour/channel k is picked in the Channel chooser
    (its choices are reported), the tool with a PickChannel parameter runs (a real click on Run) and the number of blobs its summary names is `blobs_channel_k`."""
    w = ctx.host.widget
    tool = next((t for t in ctx.schema["tools"] if any(p.get("pick_channel") for p in t["inputs"])), None)
    if tool is None:
        return {"status": "DRIVER_ERROR", "error": "no tool of the app has a PickChannel parameter", "host_observed": {}}
    pname = next(p["name"] for p in tool["inputs"] if p.get("pick_channel"))
    observed: dict[str, Any] = {}
    choices: dict[str, Any] = {}
    errors = []
    source = str(tests / data["files"][0])
    for k in range(len(data["host_checks"])):
        try:
            runs.prepare(ctx, tool["id"], {"inputs": {pname: source}})
            w.file_sources[pname].value = tests / data["files"][0]
            pump(0.6)
            box = w.channel_boxes[pname]
            choices = {"choices": list(box.choices), "visible": box.visible}
            if k >= len(box.choices):
                errors.append("channel %d: the chooser lists only %s" % (k, list(box.choices)))
                continue
            box.value = list(box.choices)[k]
            pump(0.3)
            _obs, task = runs.execute(ctx, tool["id"], {"inputs": {pname: source}, "expect": {}}, started + timeout)
            if task.status != "COMPLETE":
                errors.append("channel %d: run ended %s %s" % (k, task.status, task.code))
                continue
            text = " ".join(str(r.get("text") or r.get("values") or "") for r in task.outputs["results"])
            found = re.search(r"Found \*\*(\d+)\*\* blob", text)
            if found:
                observed["blobs_channel_%d" % k] = int(found.group(1))
            else:
                errors.append("channel %d: no 'Found N blob(s)' in the results: %s" % (k, text[:120]))
        except Exception as problem:  # noqa: BLE001 - one channel failing is a row, not the end
            errors.append("channel %d: %s: %s" % (k, type(problem).__name__, problem))
    return {"status": "HOST_ONLY", "host_observed": observed, "channel_chooser": choices, **({"error": "; ".join(errors)} if errors else {})}


def runs_judge(case: dict[str, Any], report: dict[str, Any]) -> list[str]:
    expect = case.get("expect", {})
    want = expect.get("status", "COMPLETE")
    problems = []
    if report.get("status") != want:
        problems.append("status %s, expected %s: %s" % (report.get("status"), want, re.sub(r"\s+", " ", str(report.get("error") or ""))[:120]))
    elif want == "FAILED":
        if "code" in expect and report.get("code") != expect["code"]:
            problems.append("code %r, expected %r" % (report.get("code"), expect["code"]))
    return problems


if __name__ == "__main__":
    main()
