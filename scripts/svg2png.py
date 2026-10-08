#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg2png - render SVG to PNG using a headless Chromium-family browser.

Zero third-party dependencies: Python standard library only.
The single external requirement is an already-installed Chrome / Edge /
Chromium / Brave / Opera / Vivaldi (override with --browser or $SVG2PNG_BROWSER).

Why a browser instead of a rasterizer library:
  headless Chromium is the only renderer that needs NO installation yet still
  supports the full feature set - CSS in <style>, filters, masks, clipPath,
  foreignObject, CSS variables, and system fonts.

Usage:
  svg2png.py icon.svg                      -> icon.png (1x)
  svg2png.py icon.svg -s 2                 -> 2x resolution
  svg2png.py icon.svg -s 3 -b transparent  -> 3x, transparent background
  svg2png.py --input-dir ./svg --outdir ./png -s 2
  svg2png.py --list-browsers
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib
from pathlib import Path

# "--headless" is correct on every Chrome version: old headless before 132,
# new headless from 132 on. The others are fallbacks for unusual builds.
HEADLESS_FLAGS = ("--headless", "--headless=new", "--headless=old")
DEFAULT_TIMEOUT = 60

# Chromium fails to paint a *sizeless* SVG document (viewBox only, no
# width/height) when the window is smaller than roughly this many pixels -
# it silently produces a fully transparent image. Rather than depend on that
# threshold, such SVGs are always patched to carry explicit pixel dimensions.
SMALL_WINDOW_RISK = 200


# --------------------------------------------------------------------------
# browser discovery
# --------------------------------------------------------------------------

_WIN_RELATIVE = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
    r"Chromium\Application\chrome.exe",
    r"Vivaldi\Application\vivaldi.exe",
    r"Opera\Application\opera.exe",
)

_MAC_ABSOLUTE = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
    "/Applications/Opera.app/Contents/MacOS/Opera",
)

_LINUX_NAMES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser", "vivaldi", "opera",
)


def _win_registry_browsers():
    """Read App Paths from the registry via stdlib winreg (never spawns reg.exe)."""
    found = []
    try:
        import winreg  # type: ignore
    except ImportError:
        return found
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for exe in ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe"):
            try:
                with winreg.OpenKey(hive, sub + "\\" + exe) as key:
                    value = winreg.QueryValueEx(key, "")[0]
                if value:
                    found.append(value)
            except OSError:
                pass
    return found


def find_browsers():
    """Return existing browser executables, most preferred first."""
    candidates = []
    override = os.environ.get("SVG2PNG_BROWSER")
    if override:
        candidates.append(override)

    if sys.platform.startswith("win"):
        candidates.extend(_win_registry_browsers())
        for root in (os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.extend(os.path.join(root, rel) for rel in _WIN_RELATIVE)
    elif sys.platform == "darwin":
        candidates.extend(_MAC_ABSOLUTE)
        candidates.extend(filter(None, (shutil.which(n) for n in _LINUX_NAMES)))
    else:
        candidates.extend(filter(None, (shutil.which(n) for n in _LINUX_NAMES)))

    seen, ordered = set(), []
    for path in candidates:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(path):
            ordered.append(path)
    return ordered


# --------------------------------------------------------------------------
# SVG inspection / patching
# --------------------------------------------------------------------------

_UNIT_TO_PX = {
    "": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0,
    "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0,
    "em": 16.0, "ex": 8.0, "q": 96.0 / 101.6,
}
_LENGTH_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*([a-zA-Z%]*)$")
_ROOT_TAG_RE = re.compile(r"<svg\b[^>]*>", re.I | re.S)
_SIZE_ATTR_RE = re.compile(r"""(?<![-\w])(width|height)\s*=\s*("[^"]*"|'[^']*')""", re.I)
_STYLE_ATTR_RE = re.compile(r"""(style\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
_STYLE_DECL_RE = re.compile(r"(?i)(?:^|;)\s*(?:min-|max-)?(?:width|height)\s*:[^;]*")


def _length_to_px(raw):
    if not raw:
        return None
    match = _LENGTH_RE.match(raw.strip())
    if not match:
        return None
    value, unit = match.group(1), match.group(2).lower()
    if unit == "%":
        return None
    factor = _UNIT_TO_PX.get(unit)
    return None if factor is None else float(value) * factor


def _root_attr(tag, name):
    for quote in ('"', "'"):
        match = re.search(r"\b%s\s*=\s*%s([^%s]*)%s" % (name, quote, quote, quote), tag, re.I)
        if match:
            return match.group(1)
    return None


def inspect_svg(path):
    """Return a dict describing the SVG's intrinsic size.

    keys: text, tag_match, width, height, source, explicit, viewbox
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    tag_match = _ROOT_TAG_RE.search(text)
    if not tag_match:
        return {"error": "no <svg> root element found"}

    tag = tag_match.group(0)

    # Parsed first because it decides whether a forced --width/--height will
    # scale the drawing or merely enlarge the viewport around it.
    viewbox = _root_attr(tag, "viewBox")
    viewbox_size = None
    if viewbox:
        parts = re.split(r"[\s,]+", viewbox.strip())
        if len(parts) >= 4:
            try:
                viewbox_size = (float(parts[2]), float(parts[3]))
            except ValueError:
                viewbox_size = None

    width = _length_to_px(_root_attr(tag, "width"))
    height = _length_to_px(_root_attr(tag, "height"))
    if width and height:
        return {"text": text, "tag_match": tag_match, "width": width,
                "height": height, "source": "width/height attributes", "explicit": True,
                "viewbox": viewbox_size is not None}

    if viewbox_size:
        return {"text": text, "tag_match": tag_match,
                "width": viewbox_size[0], "height": viewbox_size[1],
                "source": "viewBox", "explicit": False, "viewbox": True}

    return {"error": "no usable width/height/viewBox - pass --width and --height"}


def _strip_style_size(match):
    body = _STYLE_DECL_RE.sub("", match.group(3)).strip().strip(";")
    return "" if not body else match.group(1) + match.group(2) + body + match.group(2)


def build_patched_svg(info, width, height):
    """Rewrite the root <svg> tag with explicit pixel width/height."""
    tag = info["tag_match"].group(0)
    rest = _SIZE_ATTR_RE.sub("", tag[4:], count=1)          # drop width=...
    rest = _SIZE_ATTR_RE.sub("", rest, count=1)             # drop height=...
    rest = _STYLE_ATTR_RE.sub(_strip_style_size, rest)      # drop style width/height
    new_tag = '<svg width="%g" height="%g"%s' % (width, height, rest)
    return info["text"][:info["tag_match"].start()] + new_tag + info["text"][info["tag_match"].end():]


def write_patched_svg(src, text):
    """Write the patched copy next to the source so relative refs still resolve."""
    token = uuid.uuid4().hex[:8]
    candidates = [
        src.parent / (".svg2png-%s.svg" % token),
        Path(tempfile.gettempdir()) / ("svg2png-%s.svg" % token),
    ]
    last_error = None
    for path in candidates:
        try:
            path.write_text(text, encoding="utf-8")
            return path
        except OSError as exc:
            last_error = exc
    raise OSError("cannot write a patched SVG copy: %s" % last_error)


# --------------------------------------------------------------------------
# PNG inspection (stdlib decoder - used to catch silent failures)
# --------------------------------------------------------------------------

def png_info(path):
    """Return width/height/color_type plus a `blank` verdict.

    `blank` is True only when the image is *entirely transparent* or
    *entirely opaque white* - the two signatures of a render that drew
    nothing. A deliberately flat-coloured image (say a solid green square)
    is NOT flagged.

    Every pixel is considered: rows are unfiltered one at a time and the scan
    stops at the first pixel that differs from the first one seen. Uniform rows
    are matched in C, so neither a large canvas nor a tiny element can skew the
    verdict.
    """
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")

    pos, idat = 8, bytearray()
    width = height = bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length

    info = {"width": width, "height": height, "color_type": color_type, "blank": None}
    if bit_depth != 8 or interlace != 0 or color_type not in (2, 6):
        return info
    if not width or not height or width * height > 64_000_000:
        return info

    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(idat))

    # Walk every row and stop at the first pixel that differs from the first one
    # seen - that alone proves the image is not blank. Rows that are uniform
    # (all-transparent, all-white, or any solid colour) are recognised with a
    # C-speed bytes.count(), so genuinely blank images stay cheap as well.
    # The old code sampled a 64x64 grid instead, which could miss a small
    # element and report a perfectly good render as blank.
    prev = bytearray(stride)
    cursor = 0
    first = None
    for _ in range(height):
        if cursor + 1 + stride > len(raw):
            break
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor:cursor + stride])
        cursor += stride
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                upleft = prev[i - channels] if i >= channels else 0
                estimate = left + up - upleft
                da, db, dc = abs(estimate - left), abs(estimate - up), abs(estimate - upleft)
                predictor = left if (da <= db and da <= dc) else (up if db <= dc else upleft)
                line[i] = (line[i] + predictor) & 0xFF

        if line.count(line[0]) == stride:
            pixel = bytes(line[:channels])          # uniform row: one value
            if channels == 3:
                pixel += b"\xff"
            if first is None:
                first = pixel
            elif pixel != first:
                info["blank"] = False
                return info
        else:
            for x in range(width):
                offset = x * channels
                pixel = bytes(line[offset:offset + channels])
                if channels == 3:
                    pixel += b"\xff"
                if first is None:
                    first = pixel
                elif pixel != first:
                    info["blank"] = False
                    return info
        prev = line

    if first is None:
        return info                                 # nothing decoded; blank stays None
    alpha = first[3]
    rgb = first[:3]
    info["blank"] = (alpha == 0) or (rgb == b"\xff\xff\xff" and alpha == 0xFF)
    return info


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def parse_background(value):
    """Return the AARRGGBB string Chromium expects, or None to leave it alone."""
    if value is None:
        return None
    token = value.strip().lower()
    if token in ("transparent", "none"):
        return "00000000"
    if token == "white":
        return "FFFFFFFF"
    if token == "black":
        return "FF000000"
    if token.startswith("#"):
        digits = token[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 6:
            return "FF" + digits.upper()
        if len(digits) == 8:            # #RRGGBBAA -> AARRGGBB
            return (digits[6:8] + digits[0:6]).upper()
    raise ValueError("unsupported background: %r (use transparent|white|#RRGGBB)" % value)


def build_command(browser, headless_flag, svg_uri, out_png, logical_w, logical_h,
                  scale, background, profile_dir, wait_ms, no_sandbox):
    cmd = [
        browser, headless_flag,
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--user-data-dir=%s" % profile_dir,
        "--force-device-scale-factor=%s" % ("%g" % scale),
        "--window-size=%d,%d" % (round(logical_w), round(logical_h)),
        "--screenshot=%s" % out_png,
    ]
    if background:
        cmd.append("--default-background-color=%s" % background)
    if wait_ms:
        cmd.append("--virtual-time-budget=%d" % wait_ms)
    if no_sandbox:
        cmd.append("--no-sandbox")
    cmd.append(svg_uri)
    return cmd


def render_one(browser, src, dest, scale, background, profile_dir, wait_ms,
               timeout, no_sandbox, force_size=None, dry_run=False):
    src = Path(src).resolve()
    dest = Path(dest).resolve()

    # A missing input used to escape as an uncaught FileNotFoundError and kill
    # the whole batch with a traceback. Report it as a per-file failure instead.
    if not src.is_file():
        return {"ok": False, "error": "input not found: %s" % src}

    try:
        info = inspect_svg(src)
    except OSError as exc:
        return {"ok": False, "error": "cannot read input: %s" % exc}
    if "error" in info:
        return {"ok": False, "error": info["error"]}

    logical_w, logical_h = info["width"], info["height"]
    if force_size:
        logical_w, logical_h = force_size

    # Always hand Chromium an SVG with explicit pixel dimensions: a sizeless
    # SVG document is not painted at all in small windows.
    patched = None
    target = src
    if force_size or not info["explicit"]:
        try:
            patched = write_patched_svg(src, build_patched_svg(info, logical_w, logical_h))
            target = patched
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    staging = Path(tempfile.mkdtemp(prefix="svg2png-out-"))
    staged_png = staging / "render.png"
    uri = target.as_uri()

    try:
        if dry_run:
            return {"ok": True, "dry_run": True,
                    "command": build_command(browser, HEADLESS_FLAGS[0], uri, staged_png,
                                             logical_w, logical_h, scale, background,
                                             profile_dir, wait_ms, no_sandbox)}

        last_error = None
        for headless_flag in HEADLESS_FLAGS:
            cmd = build_command(browser, headless_flag, uri, staged_png, logical_w,
                                logical_h, scale, background, profile_dir, wait_ms, no_sandbox)
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                      text=True, errors="replace")
            except subprocess.TimeoutExpired:
                # A timeout means the render itself is too slow, not that the
                # browser rejected the flag (an unknown flag fails instantly).
                # Retrying the other headless variants would just burn two more
                # full timeouts, so stop here.
                return {"ok": False, "error": "browser timed out after %ss" % timeout}
            except OSError as exc:
                return {"ok": False, "error": "cannot launch browser: %s" % exc}

            if staged_png.exists() and staged_png.stat().st_size > 0:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_png), str(dest))
                result = {
                    "ok": True,
                    "output": str(dest),
                    "logical": [round(logical_w), round(logical_h)],
                    "scale": scale,
                    "size_source": info["source"],
                    "bytes": dest.stat().st_size,
                }

                warnings = []

                # A forced size only scales the drawing when the SVG has a
                # viewBox. Without one it enlarges the viewport and leaves the
                # artwork at its original size in the corner - a render that
                # looks successful but is mostly empty canvas. `blank` cannot
                # catch it, because the image does contain pixels.
                if force_size and not info.get("viewbox") and (
                        round(logical_w), round(logical_h)
                ) != (round(info["width"]), round(info["height"])):
                    warnings.append(
                        "--width/--height enlarged the viewport but did not scale the "
                        "drawing: this SVG has no viewBox, so its content stays at "
                        "%gx%g in the corner. Add a viewBox to the SVG to scale it."
                        % (info["width"], info["height"]))

                try:
                    png = png_info(dest)
                    result["pixels"] = [png["width"], png["height"]]
                    if png["blank"]:
                        warnings.append("output is empty (fully transparent or plain white) - "
                                        "the SVG may have failed to paint")
                except Exception:
                    pass

                if warnings:
                    result["warning"] = " ".join(warnings)
                return result

            tail = (proc.stderr or "").strip().splitlines()
            last_error = tail[-1] if tail else "browser produced no output file"
        return {"ok": False, "error": last_error or "render failed"}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if patched is not None:
            try:
                patched.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def collect_inputs(args):
    """Return a list of (source_path, relative_output_path) pairs.

    The second element is the path the PNG takes *under* --outdir. A recursive
    run mirrors the source tree, because flattening it let `a/icon.svg` and
    `b/icon.svg` silently overwrite each other - only one PNG survived and
    nothing was reported. Pass --flat to get the old single-directory layout
    back; real collisions are then reported as failures instead of ignored.
    """
    if args.input_dir:
        root = Path(args.input_dir)
        if not root.is_dir():
            raise ValueError("input directory not found: %s" % root)
        files = sorted(root.rglob(args.pattern) if args.recursive else root.glob(args.pattern))
        pairs = []
        for path in files:
            if not path.is_file():
                continue
            if args.recursive and not args.flat:
                relative = path.relative_to(root)
            else:
                relative = Path(path.name)
            pairs.append((path, relative.with_suffix(".png")))
        return pairs
    return [(Path(p), None) for p in args.input]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="svg2png",
        description="Render SVG to PNG with a headless Chromium-family browser (stdlib only).",
    )
    parser.add_argument("input", nargs="*", help="SVG file(s) to render")
    parser.add_argument("-o", "--output", help="output PNG path (single input only)")
    parser.add_argument("--input-dir", help="render every SVG in this directory")
    parser.add_argument("--outdir", help="output directory for batch mode")
    parser.add_argument("--pattern", default="*.svg", help="glob for --input-dir (default: *.svg)")
    parser.add_argument("--recursive", action="store_true", help="recurse into subdirectories")
    parser.add_argument("--flat", action="store_true",
                        help="with --recursive, write every PNG straight into --outdir "
                             "instead of mirroring the source tree")
    parser.add_argument("-s", "--scale", type=float, default=1.0, help="pixel scale factor (default: 1)")
    parser.add_argument("--width", type=float, help="force logical width in px")
    parser.add_argument("--height", type=float, help="force logical height in px")
    parser.add_argument("-b", "--background", default=None,
                        help="transparent | white | black | #RRGGBB | #RRGGBBAA")
    parser.add_argument("--browser", help="path to the browser executable")
    parser.add_argument("--wait-ms", type=int, default=0,
                        help="virtual time budget in ms, for animated SVG (default: 0)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="per-file timeout in seconds")
    parser.add_argument("--no-sandbox", action="store_true",
                        help="pass --no-sandbox (needed in some containers)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--dry-run", action="store_true", help="print the command instead of running it")
    parser.add_argument("--list-browsers", action="store_true", help="show detected browsers and exit")
    args = parser.parse_args(argv)

    browsers = find_browsers()
    if args.list_browsers:
        if not browsers:
            print("no Chromium-family browser found")
            return 1
        for path in browsers:
            print(path)
        return 0

    if args.browser:
        if not os.path.isfile(args.browser):
            print("browser not found: %s" % args.browser, file=sys.stderr)
            return 2
        browser = args.browser
    elif browsers:
        browser = browsers[0]
    else:
        print("No Chrome / Edge / Chromium found. Install one, or set --browser / $SVG2PNG_BROWSER.",
              file=sys.stderr)
        return 2

    if not args.no_sandbox and hasattr(os, "geteuid") and os.geteuid() == 0:
        args.no_sandbox = True   # Chromium refuses to start as root otherwise

    # Numeric validation up front: a scale of 0 or a negative one used to be
    # passed straight through as --force-device-scale-factor=0.
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a positive, finite number")
    for name in ("width", "height"):
        value = getattr(args, name)
        if value is not None and (not math.isfinite(value) or value <= 0):
            parser.error("--%s must be a positive, finite number" % name)
    if args.wait_ms < 0:
        parser.error("--wait-ms must be 0 or greater")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")

    try:
        inputs = collect_inputs(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not inputs:
        parser.error("no input given (pass SVG files or --input-dir)")
    if args.output and len(inputs) > 1:
        parser.error("--output only works with a single input; use --outdir for batches")

    force_size = None
    if args.width and args.height:
        force_size = (args.width, args.height)
    elif args.width or args.height:
        parser.error("--width and --height must be given together")

    try:
        background = parse_background(args.background)
    except ValueError as exc:
        parser.error(str(exc))

    profile_dir = tempfile.mkdtemp(prefix="svg2png-profile-")
    results, failures = [], 0
    claimed = {}
    total = len(inputs)
    try:
        for index, (src, relative) in enumerate(inputs, 1):
            if args.output:
                dest = Path(args.output)
            elif args.outdir:
                dest = Path(args.outdir) / (relative if relative is not None
                                            else src.stem + ".png")
            else:
                dest = src.with_suffix(".png")

            if total > 1 and not args.json:
                print("[%d/%d] %s" % (index, total, src), file=sys.stderr)

            # Two inputs mapping to one output silently lost a file before.
            key = os.path.normcase(str(dest))
            if key in claimed:
                result = {"ok": False,
                          "error": "output collision: %s is also the target of %s "
                                   "(use --flat with --recursive to flatten on purpose)"
                                   % (dest, claimed[key])}
            else:
                claimed[key] = str(src)
                result = render_one(browser, src, dest, args.scale, background, profile_dir,
                                    args.wait_ms, args.timeout, args.no_sandbox, force_size,
                                    args.dry_run)
            result["input"] = str(src)
            results.append(result)
            if not result.get("ok"):
                failures += 1
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    if args.json:
        print(json.dumps({"browser": browser, "results": results}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            if result.get("ok"):
                if result.get("dry_run"):
                    print("DRY RUN " + " ".join(result["command"]))
                    continue
                pixels = result.get("pixels") or result["logical"]
                print("OK   %s  ->  %s  (%sx%s, %s bytes)"
                      % (result["input"], result["output"], pixels[0], pixels[1], result["bytes"]))
                if result.get("warning"):
                    print("     WARNING: " + result["warning"])
            else:
                print("FAIL %s  ->  %s" % (result["input"], result["error"]))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
