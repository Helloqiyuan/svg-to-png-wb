#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for scripts/svg2png.py.

These cover the silent-failure bugs that were fixed in v1.0.1. Every case here
failed, or would have gone unnoticed, before that release:

  * a missing input file killed the whole batch with a traceback
  * --recursive flattened subdirectories, so a/icon.svg and b/icon.svg
    silently overwrote each other
  * --scale 0 / negative reached the browser as --force-device-scale-factor=0
  * blank detection sampled a 64x64 grid and missed small elements
  * batch mode printed nothing until it was done

Only the standard library is used. Renders are skipped (not failed) when no
Chromium-family browser is installed, so this is safe to run anywhere.

Run:  python test/regression.py
Exit: 0 all passed (or skipped), 1 something failed
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PKG_ROOT / "scripts" / "svg2png.py"

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    line = "%s %s" % (mark, name)
    if not condition and detail:
        line += "\n     " + str(detail).strip().replace("\n", "\n     ")
    print(line)


def load_module():
    spec = importlib.util.spec_from_file_location("svg2png_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, errors="replace", cwd=cwd,
    )


def run_json(args, cwd=None):
    proc = run(args + ["--json"], cwd=cwd)
    try:
        return proc, json.loads(proc.stdout)
    except Exception:
        return proc, None


def first_result(data):
    results = (data or {}).get("results") or [{}]
    return results[0]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SVG = '<svg xmlns="http://www.w3.org/2000/svg" %s>%s</svg>'


def main():
    module = load_module()
    browsers = module.find_browsers()
    if not browsers:
        print("SKIP no Chromium-family browser found - render tests not run")
        print("\n0/0 passed (skipped)")
        return 0

    root = Path(tempfile.mkdtemp(prefix="svg2png-regression-"))
    print("workdir: %s\n" % root)

    try:
        # ---------------------------------------------------------- fixtures
        simple = root / "simple.svg"
        write(simple, SVG % ('width="120" height="80"',
                             '<rect width="120" height="80" fill="#3366cc"/>'))

        viewbox = root / "viewbox.svg"
        write(viewbox, SVG % ('viewBox="0 0 100 60"',
                              '<circle cx="50" cy="30" r="25" fill="#cc3333"/>'))

        # A tiny element in a big canvas: the old 64x64 sampling grid could step
        # straight over it and report a perfectly good render as blank.
        tiny = root / "tiny-in-big.svg"
        write(tiny, SVG % ('width="1200" height="1200"',
                           '<rect x="1100" y="1100" width="8" height="8" fill="#ff00ff"/>'))

        blank = root / "blank.svg"
        write(blank, SVG % ('width="200" height="150"', ''))

        nested = root / "nested"
        write(nested / "a" / "icon.svg",
              SVG % ('width="64" height="64"', '<rect width="64" height="64" fill="#ff0000"/>'))
        write(nested / "b" / "icon.svg",
              SVG % ('width="64" height="64"', '<rect width="64" height="64" fill="#00ff00"/>'))

        # ---------------------------------------------------------- 1. happy path
        _, data = run_json([str(simple)])
        res = first_result(data)
        check("simple.svg renders", res.get("ok") is True, res.get("error", ""))
        check("simple.svg is 120x80", res.get("pixels") == [120, 80], res.get("pixels"))
        check("simple.svg is not flagged blank", "warning" not in res, res.get("warning"))

        _, data = run_json([str(viewbox)])
        res = first_result(data)
        check("viewBox-only svg renders", res.get("ok") is True, res.get("error", ""))
        check("viewBox-only svg is 100x60", res.get("pixels") == [100, 60], res.get("pixels"))
        check("viewBox-only svg is not blank", "warning" not in res, res.get("warning"))

        # ---------------------------------------------------------- 2. blank verdict
        _, data = run_json([str(blank), "-b", "transparent"])
        res = first_result(data)
        check("a genuinely blank svg IS flagged", res.get("warning") is not None,
              "blank detection stopped working")

        _, data = run_json([str(tiny)])
        res = first_result(data)
        check("tiny element in a big canvas is NOT flagged blank", "warning" not in res,
              "sampling missed the 8x8 element: %s" % res.get("warning"))

        # ---------------------------------------------------------- 3. missing input
        proc, data = run_json([str(simple), str(root / "does-not-exist.svg")])
        res = (data or {}).get("results") or []
        check("missing file gives exit code 1", proc.returncode == 1, "rc=%s" % proc.returncode)
        check("missing file is a per-file failure, not a crash",
              len(res) == 2 and res[0].get("ok") and not res[1].get("ok"),
              json.dumps(res)[:200])
        check("missing file produces no traceback", "Traceback" not in proc.stderr,
              proc.stderr[-200:])
        check("the good file in the same batch still rendered",
              (root / "simple.png").is_file() and "simple.png" in proc.stdout)

        # ---------------------------------------------------------- 4. recursive layout
        mirror = root / "out-mirror"
        proc, data = run_json(["--input-dir", str(nested), "--outdir", str(mirror), "--recursive"])
        produced = sorted(str(p.relative_to(mirror)) for p in mirror.rglob("*.png")) if mirror.is_dir() else []
        check("recursive batch exits 0", proc.returncode == 0, proc.stderr[-200:])
        check("subdirectory structure is preserved",
              (mirror / "a" / "icon.png").is_file() and (mirror / "b" / "icon.png").is_file(),
              produced)
        check("both same-named files got their own PNG", len(produced) == 2, produced)

        flat = root / "out-flat"
        proc, data = run_json(["--input-dir", str(nested), "--outdir", str(flat),
                               "--recursive", "--flat"])
        res = (data or {}).get("results") or []
        check("--flat reports the collision instead of overwriting",
              proc.returncode == 1 and any("collision" in (r.get("error") or "") for r in res),
              json.dumps(res)[:250])

        # ---------------------------------------------------------- 5. numeric validation
        for bad in (["-s", "0"], ["-s", "-2"], ["--width", "0", "--height", "10"],
                    ["--timeout", "0"], ["--wait-ms", "-5"]):
            proc = run([str(simple)] + bad)
            check("%s is rejected" % " ".join(bad),
                  proc.returncode == 2 and "Traceback" not in proc.stderr,
                  "rc=%s %s" % (proc.returncode, (proc.stderr or "")[-150:]))

        # ---------------------------------------------------------- 6. bad input dir
        proc = run(["--input-dir", str(root / "nope"), "--outdir", str(root / "x")])
        check("a missing --input-dir is a clean error",
              proc.returncode == 2 and "not found" in (proc.stderr or "")
              and "Traceback" not in proc.stderr,
              "rc=%s %s" % (proc.returncode, (proc.stderr or "")[-200:]))

        # ---------------------------------------------------------- 7. progress output
        proc = run(["--input-dir", str(nested), "--outdir", str(root / "out-progress"),
                    "--recursive"])
        check("batch mode prints progress on stderr",
              "[1/2]" in (proc.stderr or "") and "[2/2]" in (proc.stderr or ""),
              repr((proc.stderr or "")[:200]))

        proc = run(["--input-dir", str(nested), "--outdir", str(root / "out-quiet"),
                    "--recursive", "--json"])
        check("--json keeps stdout machine-readable",
              (proc.stdout or "").lstrip().startswith("{"), repr((proc.stdout or "")[:80]))

        # ---------------------------------------------------------- 8. dry run
        proc = run([str(simple), "-o", str(root / "dry.png"), "--dry-run"])
        check("--dry-run writes nothing", not (root / "dry.png").exists())
        check("--dry-run exits 0", proc.returncode == 0, proc.stderr[-150:])

        # ---------------------------------------------------------- 9. blank verdict vs Pillow
        # Optional: Pillow is the independent reference for "is this image
        # uniform". Skipped when it is not installed.
        try:
            from PIL import Image
        except ImportError:
            print("SKIP Pillow cross-check (Pillow not installed)")
        else:
            for name, path in (("simple", simple.with_suffix(".png")),
                               ("tiny", tiny.with_suffix(".png")),
                               ("blank", blank.with_suffix(".png"))):
                if not path.is_file():
                    continue
                image = Image.open(path).convert("RGBA")
                colors = image.getcolors(maxcolors=1 << 24)
                if colors is None or len(colors) != 1:
                    expected = False
                else:
                    r, g, b, a = colors[0][1]
                    expected = a == 0 or (r == g == b == 255 and a == 255)
                check("blank verdict matches Pillow for %s" % name,
                      module.png_info(path)["blank"] == expected,
                      "png_info said %s, Pillow said %s" % (module.png_info(path)["blank"], expected))

    finally:
        shutil.rmtree(root, ignore_errors=True)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        print("FAILED: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
