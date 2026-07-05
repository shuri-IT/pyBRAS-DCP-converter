#!/usr/bin/env python3
"""
pyBRAS_preparador_video.py

Automated "Etapa 0" for pyBRAS-DCP-converter: takes a raw sign-language
interpreter video and produces a file already in the shape the converter
wants (portrait 3:4, 480x640, 24 fps progressive, H.264 @ 1 Mbps, black
background), so that pyBRAS_conversor_libras_wav.py never needs to warn
about letterboxing.

What it automates
-----------------
1. Finds WHERE the interpreter is in the frame (they may be off-center),
   assuming they stay in roughly the same spot for the whole video:

   * If the video was shot on green/blue screen, the chroma itself is used
     as a person detector: everything that is NOT key-colored is foreground.
     Sampling frames across the whole duration and taking the union of the
     foreground captures the full signing space (arms/hands at their
     widest), not just one pose.

   * If there is no chroma, motion is used instead: with a static signer,
     frame-to-frame differences concentrate exactly on the moving hands,
     arms and face. The union of motion across sampled frame pairs outlines
     the signing space.

2. Expands that detection box with a safety margin, grows it to an exact
   3:4 portrait aspect centered on the interpreter, and crops there.

3. Optionally removes the chroma key (auto-detected color, or forced via
   flags) and composites the interpreter over solid black, with despill.

4. Encodes to H.264 1 Mbps, 24 fps, yuv420p, scaled/padded to 480x640.

Everything is pure Python standard library + the same ffmpeg/ffprobe the
converter already requires. Frames are exchanged with ffmpeg as PPM images
and parsed by hand, so there is nothing to pip-install.

Limitations (by design): assumes the interpreter does not walk around the
frame. Always check the result with --preview before batch runs.
"""

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# Target geometry: must match pyBRAS_conversor_libras_wav.py.
TARGET_WIDTH = 480
TARGET_HEIGHT = 640
TARGET_ASPECT = TARGET_WIDTH / TARGET_HEIGHT  # 3:4 portrait = 0.75
TARGET_FPS = 24
TARGET_BITRATE = "1000k"          # Etapa 0 recommends H.264 @ 1 Mbps

ANALYSIS_WIDTH = 320              # frames are downscaled to this for analysis
DEFAULT_SAMPLES = 12              # frames sampled across the duration
MOTION_THRESHOLD = 26             # 0-255 gray delta considered "movement"
OCCUPANCY_FRACTION = 0.02         # row/col must be >=2% foreground to count
KEY_DETECT_FACTOR = 1.30          # channel dominance for border detection
KEY_MASK_FACTOR = 1.15            # looser dominance when building the mask
KEY_MIN_LEVEL = 70                # minimum channel level to look key-like
MIN_KEY_FRACTION = 0.30           # >=30% of all pixels key-colored => chroma video


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"erro: ferramenta obrigatória '{name}' não encontrada no PATH")


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------

def probe(input_path: Path):
    """Return (width, height, duration_secs) for the first video stream,
    already adjusted for rotation metadata (same logic as the converter)."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(input_path),
    ]
    try:
        result = run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        sys.exit(f"erro: {input_path} não pôde ser lido (arquivo corrompido ou formato não suportado)")

    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        sys.exit(f"erro: {input_path} não contém nenhuma trilha de vídeo")
    stream = streams[0]

    w = int(stream.get("width", 0) or 0)
    h = int(stream.get("height", 0) or 0)

    rotation = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
            break
    if rotation == 0:
        tag = stream.get("tags", {}).get("rotate")
        if tag:
            try:
                rotation = int(tag)
            except ValueError:
                rotation = 0
    if abs(rotation) in (90, 270):
        w, h = h, w

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    if w <= 0 or h <= 0:
        sys.exit(f"erro: não foi possível determinar a resolução de {input_path}")
    if duration <= 0:
        sys.exit(f"erro: não foi possível determinar a duração de {input_path}")
    return w, h, duration


# --------------------------------------------------------------------------
# Frame sampling (PPM in, parsed by hand — no pip dependencies)
# --------------------------------------------------------------------------

def parse_ppm(data: bytes):
    """Parse a binary P6 PPM. Returns (width, height, rgb_bytes)."""
    tokens = []
    pos = 0
    while len(tokens) < 4:
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":  # comment line
            while pos < len(data) and data[pos] != 0x0A:
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    if tokens[0] != b"P6":
        raise ValueError("frame extraído não está em formato PPM/P6")
    w, h, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    if maxval != 255:
        raise ValueError(f"PPM com maxval {maxval} não suportado")
    pos += 1  # single whitespace after maxval
    rgb = data[pos:pos + w * h * 3]
    if len(rgb) < w * h * 3:
        raise ValueError("frame PPM truncado")
    return w, h, rgb


def extract_samples(input_path: Path, duration: float, n_samples: int, tmp_dir: Path):
    """Extract n_samples frames evenly spread over the middle 90% of the
    video, downscaled to ANALYSIS_WIDTH, as parsed PPMs.
    Returns (frames, aw, ah) where frames is a list of rgb byte strings."""
    t0, t1 = 0.05 * duration, 0.95 * duration
    times = [t0 + (t1 - t0) * i / max(1, n_samples - 1) for i in range(n_samples)]

    frames = []
    aw = ah = None
    for i, t in enumerate(times):
        out = tmp_dir / f"sample_{i:03d}.ppm"
        cmd = [
            "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
            "-ss", f"{t:.3f}", "-i", str(input_path),
            "-frames:v", "1",
            "-vf", f"scale={ANALYSIS_WIDTH}:-2:flags=area",
            "-f", "image2", "-c:v", "ppm", str(out),
        ]
        run(cmd)
        if not out.exists():
            continue
        w, h, rgb = parse_ppm(out.read_bytes())
        if aw is None:
            aw, ah = w, h
        if (w, h) == (aw, ah):
            frames.append(rgb)
    if not frames or aw is None:
        sys.exit("erro: não foi possível extrair frames de análise do vídeo")
    return frames, aw, ah


# --------------------------------------------------------------------------
# Chroma detection
# --------------------------------------------------------------------------

def is_keyish(r: int, g: int, b: int, channel: str, factor: float) -> bool:
    if channel == "verde":
        return g >= KEY_MIN_LEVEL and g > r * factor and g > b * factor
    if channel == "azul":
        return b >= KEY_MIN_LEVEL and b > r * factor and b > g * factor
    return False


def detect_chroma(frames, aw: int, ah: int):
    """Decide whether the video is chroma-keyed and with which color.
    The whole frame is sampled (not just the borders): real-world backdrops
    often do not reach the frame edges, sitting inside a room with walls and
    furniture around them. If at least MIN_KEY_FRACTION of all pixels are
    green- or blue-dominant, that channel is the key; the mean color of
    those pixels becomes the chromakey reference. Returns
    ('verde'|'azul', '0xRRGGBB') or (None, None)."""
    counts = {"verde": 0, "azul": 0}
    sums = {"verde": [0, 0, 0], "azul": [0, 0, 0]}
    total = 0
    for rgb in frames:
        for y in range(0, ah, 2):
            row = y * aw * 3
            for x in range(0, aw, 2):
                i = row + x * 3
                r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
                total += 1
                for ch in ("verde", "azul"):
                    if is_keyish(r, g, b, ch, KEY_DETECT_FACTOR):
                        counts[ch] += 1
                        s = sums[ch]
                        s[0] += r; s[1] += g; s[2] += b
                        break
    if total == 0:
        return None, None
    best = max(("verde", "azul"), key=lambda ch: counts[ch])
    if counts[best] / total >= MIN_KEY_FRACTION:
        n = counts[best]
        mean = [sums[best][0] // n, sums[best][1] // n, sums[best][2] // n]
        return best, "0x{:02X}{:02X}{:02X}".format(*mean)
    return None, None


# --------------------------------------------------------------------------
# Interpreter localization
# --------------------------------------------------------------------------
#
# v2: robust against real-world frames where the green screen does NOT cover
# the whole image and where non-green objects (fans, walls, doors, shelves)
# would otherwise be mistaken for the interpreter or survive the keying.
#
#   1. Find the green backdrop's own area (row/column green occupancy).
#   2. Inside it, foreground = non-green pixels. Split the foreground into
#      connected components: the interpreter is the highest-scoring blob
#      (area, with a bonus for touching the bottom of the backdrop, where a
#      waist-up-framed signer always is). Every other sizable blob (a fan,
#      a cable, the edge of a door) is recorded as an OBSTACLE.
#   3. The final 3:4 crop is grown around the interpreter but constrained to
#      the backdrop area and steered away from the obstacles, so everything
#      inside the crop is either the interpreter or keyable green. After
#      keying, the background is guaranteed pure black; if the crop could
#      not reach full 3:4 inside the backdrop, the black padding completes
#      it seamlessly (black on black).
#
# Motion mode gets the same treatment: motion is accumulated over all frame
# pairs into one energy map, components are extracted from it, the signing
# space is the dominant component cluster and independent movers (a spinning
# fan, a TV) become obstacles instead of stretching the crop.

MIN_COMPONENT_FRACTION = 0.003   # blobs smaller than this fraction of the
                                 # search area are ignored as speckle
KEEP_MOTION_FRACTION = 0.25      # motion blobs >= 25% of the largest are
                                 # considered part of the signing space
GREEN_ROW_FRACTION = 0.08        # row/col is "backdrop" if >=8% green
BACKDROP_INSET = 0.02            # inset used when masking/clamping, to skip
                                 # the backdrop's ragged edge pixels


def bbox_from_occupancy(col_counts, row_counts, aw: int, ah: int,
                        col_min: int, row_min: int):
    xs = [x for x in range(aw) if col_counts[x] >= col_min]
    ys = [y for y in range(ah) if row_counts[y] >= row_min]
    if not xs or not ys:
        return None
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


def union_bbox(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def boxes_intersect(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def connected_components(mask, aw: int, ah: int):
    """4-connectivity components of a bytearray mask (1 = foreground).
    Returns (comps, labels): comps is a list of {'area', 'box'}, labels is a
    bytearray where labels[i] == component_index + 1."""
    seen = bytearray(aw * ah)
    labels = bytearray(aw * ah)
    comps = []
    for start in range(aw * ah):
        if not mask[start] or seen[start]:
            continue
        label = len(comps) + 1
        stack = [start]
        seen[start] = 1
        area = 0
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        while stack:
            i = stack.pop()
            labels[i] = label
            area += 1
            y, x = divmod(i, aw)
            if x < x0: x0 = x
            if y < y0: y0 = y
            if x > x1: x1 = x
            if y > y1: y1 = y
            if x > 0 and mask[i - 1] and not seen[i - 1]:
                seen[i - 1] = 1; stack.append(i - 1)
            if x < aw - 1 and mask[i + 1] and not seen[i + 1]:
                seen[i + 1] = 1; stack.append(i + 1)
            if y > 0 and mask[i - aw] and not seen[i - aw]:
                seen[i - aw] = 1; stack.append(i - aw)
            if y < ah - 1 and mask[i + aw] and not seen[i + aw]:
                seen[i + aw] = 1; stack.append(i + aw)
        comps.append({"area": area, "box": (x0, y0, x1 + 1, y1 + 1)})
    return comps, labels


def backdrop_bbox(rgb, aw: int, ah: int, channel: str):
    """Bounding box of the green/blue backdrop itself, via occupancy of
    key-colored pixels per row/column."""
    col_counts = [0] * aw
    row_counts = [0] * ah
    for y in range(ah):
        row = y * aw * 3
        for x in range(aw):
            i = row + x * 3
            if is_keyish(rgb[i], rgb[i + 1], rgb[i + 2], channel, KEY_DETECT_FACTOR):
                col_counts[x] += 1
                row_counts[y] += 1
    return bbox_from_occupancy(
        col_counts, row_counts, aw, ah,
        col_min=max(3, int(ah * GREEN_ROW_FRACTION)),
        row_min=max(3, int(aw * GREEN_ROW_FRACTION)),
    )


def median_bbox(boxes):
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    mid = len(boxes) // 2
    return tuple(sorted(b[k] for b in boxes)[mid] for k in range(4))


def locate_by_chroma(frames, aw, ah, channel):
    """Return (person_box, backdrop_box, obstacle_boxes) in analysis coords,
    or (None, None, []) if the interpreter could not be found."""
    backdrops = [backdrop_bbox(rgb, aw, ah, channel) for rgb in frames]
    backdrop = median_bbox(backdrops)
    if backdrop is None:
        return None, None, []

    inset_x = max(1, int((backdrop[2] - backdrop[0]) * BACKDROP_INSET))
    inset_y = max(1, int((backdrop[3] - backdrop[1]) * BACKDROP_INSET))
    bx0, by0 = backdrop[0] + inset_x, backdrop[1] + inset_y
    bx1, by1 = backdrop[2] - inset_x, backdrop[3] - inset_y
    region_area = max(1, (bx1 - bx0) * (by1 - by0))
    min_area = max(20, int(region_area * MIN_COMPONENT_FRACTION))
    bottom_band = by1 - max(2, int((by1 - by0) * 0.20))

    person = None
    obstacles = []
    person_frames = []   # (labels, best_label) per frame, for paintability
    for rgb in frames:
        mask = bytearray(aw * ah)
        for y in range(by0, by1):
            row = y * aw * 3
            base = y * aw
            for x in range(bx0, bx1):
                i = row + x * 3
                if not is_keyish(rgb[i], rgb[i + 1], rgb[i + 2], channel, KEY_MASK_FACTOR):
                    mask[base + x] = 1
        all_comps, labels = connected_components(mask, aw, ah)
        comps = [(idx + 1, c) for idx, c in enumerate(all_comps) if c["area"] >= min_area]
        if not comps:
            continue

        def score(item):
            touches_bottom = item[1]["box"][3] >= bottom_band
            return item[1]["area"] * (2.0 if touches_bottom else 1.0)

        best_label, best = max(comps, key=score)
        person = union_bbox(person, best["box"])
        person_frames.append((labels, best_label))
        for label, c in comps:
            if label != best_label:
                obstacles.append(c["box"])

    paintable, unavoidable = [], []
    for box in merge_boxes(obstacles):
        # An obstacle can be safely painted black only if the interpreter's
        # silhouette never enters it (with a small dilation) in any frame.
        ox0 = max(box[0] - 2, 0); oy0 = max(box[1] - 2, 0)
        ox1 = min(box[2] + 2, aw); oy1 = min(box[3] + 2, ah)
        touched = False
        for labels, best_label in person_frames:
            for y in range(oy0, oy1):
                base = y * aw
                if best_label in labels[base + ox0:base + ox1]:
                    touched = True
                    break
            if touched:
                break
        if not touched:
            paintable.append((ox0, oy0, ox1, oy1))
            continue
        # The silhouette touches this blob: it is either a body part that
        # momentarily disconnected in the downscaled mask (a hand at full
        # extension) or an object the interpreter passes in front of. In
        # both cases the crop must CONTAIN it, so merge it into the person.
        # Only warn when the merge grows the framing substantially — that
        # signals a real foreign object rather than a stray limb.
        before = (person[2] - person[0]) * (person[3] - person[1])
        merged = union_bbox(person, (ox0, oy0, ox1, oy1))
        after = (merged[2] - merged[0]) * (merged[3] - merged[1])
        person = merged
        if after > before * 1.25:
            unavoidable.append((ox0, oy0, ox1, oy1))
    return person, (bx0, by0, bx1, by1), paintable, unavoidable


def locate_by_motion(frames, aw, ah):
    """Return (person_box, None, obstacle_boxes). Motion is accumulated over
    all consecutive sample pairs into one energy map; the signing space is
    the dominant component cluster of that map."""
    if len(frames) < 2:
        return None, None, [], []
    energy = bytearray(aw * ah)
    for prev, cur in zip(frames, frames[1:]):
        for p in range(aw * ah):
            i = p * 3
            g0 = (2 * prev[i] + 4 * prev[i + 1] + prev[i + 2]) // 7
            g1 = (2 * cur[i] + 4 * cur[i + 1] + cur[i + 2]) // 7
            if abs(g1 - g0) >= MOTION_THRESHOLD:
                energy[p] = 1
    min_area = max(20, int(aw * ah * MIN_COMPONENT_FRACTION))
    all_comps, _ = connected_components(energy, aw, ah)
    comps = [c for c in all_comps if c["area"] >= min_area]
    if not comps:
        return None, None, [], []
    largest = max(c["area"] for c in comps)
    person = None
    obstacles = []
    for c in comps:
        if c["area"] >= largest * KEEP_MOTION_FRACTION:
            person = union_bbox(person, c["box"])
        else:
            obstacles.append(c["box"])
    # An "obstacle" already engulfed by the signing space is not an obstacle.
    obstacles = [b for b in obstacles if not boxes_intersect(b, person)] if person else obstacles
    # In motion mode there is no chroma to hide a black patch in, so nothing
    # is paintable: independent movers are geometric obstacles only.
    return person, None, [], merge_boxes(obstacles)


def merge_boxes(boxes):
    """Merge overlapping boxes so the crop-steering step deals with few,
    stable obstacles instead of one box per frame."""
    boxes = list(boxes)
    merged = True
    while merged:
        merged = False
        out = []
        while boxes:
            b = boxes.pop()
            for j, o in enumerate(out):
                if boxes_intersect(b, o):
                    out[j] = union_bbox(b, o)
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def steer_away_from_obstacles(bounds, person, obstacles):
    """Shrink the allowed crop area so it excludes each obstacle while still
    containing the interpreter. For each obstacle, the side (top/bottom/left/
    right) whose shrink loses the least area is chosen. Obstacles that
    overlap the interpreter's own box cannot be excluded geometrically and
    are reported back so the user can be warned."""
    ax0, ay0, ax1, ay1 = bounds
    px0, py0, px1, py1 = person
    unavoidable = []
    for ox0, oy0, ox1, oy1 in obstacles:
        if not boxes_intersect((ox0, oy0, ox1, oy1), (ax0, ay0, ax1, ay1)):
            continue
        options = []
        if oy1 <= py0:                      # obstacle fully above the person
            options.append(("top", oy1, (oy1 - ay0) * (ax1 - ax0)))
        if oy0 >= py1:                      # fully below
            options.append(("bottom", oy0, (ay1 - oy0) * (ax1 - ax0)))
        if ox1 <= px0:                      # fully to the left
            options.append(("left", ox1, (ox1 - ax0) * (ay1 - ay0)))
        if ox0 >= px1:                      # fully to the right
            options.append(("right", ox0, (ax1 - ox0) * (ay1 - ay0)))
        if not options:
            unavoidable.append((ox0, oy0, ox1, oy1))
            continue
        side, value, _ = min(options, key=lambda o: o[2])
        if side == "top":
            ay0 = max(ay0, value)
        elif side == "bottom":
            ay1 = min(ay1, value)
        elif side == "left":
            ax0 = max(ax0, value)
        elif side == "right":
            ax1 = min(ax1, value)
    return (ax0, ay0, ax1, ay1), unavoidable


# --------------------------------------------------------------------------
# Crop geometry
# --------------------------------------------------------------------------

def expand_to_aspect(box, margin: float, bounds):
    """Add a safety margin around the detection box, then grow it toward an
    exact 3:4 portrait rectangle centered on the interpreter, WITHOUT ever
    leaving `bounds` (the usable area: backdrop minus obstacles). If 3:4
    does not fit inside bounds, the crop stops at the bounds and the final
    black padding completes the aspect seamlessly."""
    ax0, ay0, ax1, ay1 = bounds
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0

    mx, my = bw * margin, bh * margin
    x0, y0 = max(x0 - mx, ax0), max(y0 - my, ay0)
    x1, y1 = min(x1 + mx, ax1), min(y1 + my, ay1)

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0

    if w / h < TARGET_ASPECT:
        w = h * TARGET_ASPECT
    else:
        h = w / TARGET_ASPECT

    w = min(w, ax1 - ax0)
    h = min(h, ay1 - ay0)
    x = min(max(cx - w / 2, ax0), ax1 - w)
    y = min(max(cy - h / 2, ay0), ay1 - h)
    return x, y, w, h


def to_even_source_crop(crop, scale_back: float, src_w: int, src_h: int):
    """Scale an analysis-space (x, y, w, h) crop to source pixels, with even
    integer values (yuv420p-friendly), clamped to the source frame."""
    x, y, w, h = (v * scale_back for v in crop)
    xi, yi = int(x) // 2 * 2, int(y) // 2 * 2
    wi, hi = int(w) // 2 * 2, int(h) // 2 * 2
    xi, yi = min(max(xi, 0), src_w - 2), min(max(yi, 0), src_h - 2)
    wi = max(2, min(wi, (src_w - xi) // 2 * 2))
    hi = max(2, min(hi, (src_h - yi) // 2 * 2))
    return xi, yi, wi, hi


def verify_hand_coverage(input_path: Path, aw: int, ah: int, person, bounds,
                         margin: float, coverage_fps: float, chroma_channel,
                         skip_boxes):
    """Full-video guarantee pass: the detection above looked at a handful of
    sampled frames, so a hand reaching its widest point for only an instant
    could still fall outside the chosen crop. This pass streams the ENTIRE
    video (at coverage_fps frames per second, analysis resolution) and checks
    every decoded frame: if any foreground appears outside the current crop,
    the person box is widened on the spot and checking continues with the
    enlarged crop. Foreground = non-key pixels (chroma mode) or moving
    pixels vs. the previous frame (motion mode). skip_boxes (the painted
    obstacles) are ignored. Returns (person, frames_checked, expansions)."""
    ax0, ay0, ax1, ay1 = (int(v) for v in bounds)
    frame_bytes = aw * ah * 3

    def crop_rect():
        x, y, w, h = expand_to_aspect(person, margin, bounds)
        return int(x), int(y), int(x + w) + 1, int(y + h) + 1

    def in_skip(x, y):
        for (sx0, sy0, sx1, sy1) in skip_boxes:
            if sx0 <= x < sx1 and sy0 <= y < sy1:
                return True
        return False

    cmd = [
        "ffmpeg", "-loglevel", "error", "-hide_banner",
        "-i", str(input_path),
        "-vf", f"fps={coverage_fps},scale={ANALYSIS_WIDTH}:-2:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    frames_checked = 0
    expansions = 0
    prev = None
    try:
        while True:
            buf = b""
            while len(buf) < frame_bytes:
                chunk = proc.stdout.read(frame_bytes - len(buf))
                if not chunk:
                    break
                buf += chunk
            if len(buf) < frame_bytes:
                break
            frames_checked += 1
            cx0, cy0, cx1, cy1 = crop_rect()

            count = 0
            ox0 = oy0 = 10 ** 9
            ox1 = oy1 = -1
            for y in range(ay0, ay1, 2):
                inside_y = cy0 <= y < cy1
                row = y * aw * 3
                for x in range(ax0, ax1, 2):
                    if inside_y and cx0 <= x < cx1:
                        continue
                    if in_skip(x, y):
                        continue
                    i = row + x * 3
                    if chroma_channel is not None:
                        fg = not is_keyish(buf[i], buf[i + 1], buf[i + 2],
                                           chroma_channel, KEY_MASK_FACTOR)
                    else:
                        if prev is None:
                            fg = False
                        else:
                            g0 = (2 * prev[i] + 4 * prev[i + 1] + prev[i + 2]) // 7
                            g1 = (2 * buf[i] + 4 * buf[i + 1] + buf[i + 2]) // 7
                            fg = abs(g1 - g0) >= MOTION_THRESHOLD
                    if fg:
                        count += 1
                        if x < ox0: ox0 = x
                        if y < oy0: oy0 = y
                        if x > ox1: ox1 = x
                        if y > oy1: oy1 = y
            # >=6 sampled pixels (stride 2 in both axes) ~ a real hand-sized
            # region; below that it is compression speckle.
            if count >= 6:
                person = union_bbox(person, (ox0, oy0, ox1 + 1, oy1 + 1))
                expansions += 1
            prev = buf
    finally:
        proc.stdout.close()
        proc.wait()
    return person, frames_checked, expansions


def parse_manual_crop(text: str):
    m = re.fullmatch(r"(\d+):(\d+):(\d+):(\d+)", text.strip())
    if not m:
        sys.exit("erro: --crop deve estar no formato LARGURA:ALTURA:X:Y (ex.: 600:800:200:0)")
    w, h, x, y = (int(v) for v in m.groups())
    return x, y, w, h


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------

def build_filtergraph(crop, chroma_color, chroma_channel, similarity, blend,
                      paint_boxes=()):
    """Return the -filter_complex string: (paint obstacles black) -> crop ->
    (chromakey over black) -> fps/scale/pad to 480x640. paint_boxes are
    (x, y, w, h) rectangles in SOURCE coordinates covering static objects
    sitting on the backdrop (a fan, a cable): painted black, they merge
    invisibly into the keyed-black background."""
    x, y, w, h = crop
    paint = "".join(
        f"drawbox=x={px}:y={py}:w={pw}:h={ph}:color=black:t=fill,"
        for (px, py, pw, ph) in paint_boxes
    )
    tail = (
        f"fps={TARGET_FPS},"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,format=yuv420p"
    )
    crop_expr = f"{paint}crop={w}:{h}:{x}:{y}"
    if chroma_color:
        despill_type = "green" if chroma_channel == "verde" else "blue"
        return (
            f"[0:v]{crop_expr},"
            f"chromakey={chroma_color}:{similarity}:{blend},"
            f"despill=type={despill_type}[fg];"
            f"color=black:s={w}x{h}[bg];"
            f"[bg][fg]overlay=shortest=1,{tail}[vout]"
        )
    return f"[0:v]{crop_expr},{tail}[vout]"


def encode(input_path: Path, output_path: Path, graph: str) -> None:
    cmd = [
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-i", str(input_path),
        "-filter_complex", graph,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
        "-b:v", TARGET_BITRATE, "-maxrate", TARGET_BITRATE, "-bufsize", "2000k",
        "-an", "-sn", "-movflags", "+faststart",
        str(output_path),
    ]
    run(cmd)


def write_previews(input_path: Path, duration: float, graph: str,
                   crop, stem: Path) -> None:
    """Write (a) the final-look preview frame and (b) a debug frame with the
    chosen crop drawn on the original video."""
    mid = f"{duration / 2:.3f}"
    preview = stem.with_name(stem.name + "_preparado.preview.jpg")
    run([
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-ss", mid, "-i", str(input_path),
        "-filter_complex", graph, "-map", "[vout]",
        "-frames:v", "1", str(preview),
    ])
    x, y, w, h = crop
    debug = stem.with_name(stem.name + "_deteccao.jpg")
    run([
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-ss", mid, "-i", str(input_path),
        "-vf", f"drawbox=x={x}:y={y}:w={w}:h={h}:color=red@0.9:thickness=6",
        "-frames:v", "1", str(debug),
    ])
    print(f"Preview do resultado final:   {preview}")
    print(f"Área detectada (caixa verm.): {debug}")


def verify_output(output_path: Path) -> None:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(output_path),
    ]
    result = run(cmd, capture_output=True, text=True)
    stream = next(
        (s for s in json.loads(result.stdout).get("streams", [])
         if s.get("codec_type") == "video"), {},
    )
    w, h = stream.get("width"), stream.get("height")
    codec = stream.get("codec_name")
    fps = stream.get("avg_frame_rate", "?")
    ok = (w, h, codec) == (TARGET_WIDTH, TARGET_HEIGHT, "h264") and fps in ("24/1", "24")
    label = "OK" if ok else "FALHOU"
    print(f"{label}: {output_path.name} — {codec} {w}x{h} @ {fps} fps"
          + ("" if ok else f" (esperado h264 {TARGET_WIDTH}x{TARGET_HEIGHT} @ 24 fps)"))
    if not ok:
        sys.exit(1)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepara automaticamente um vídeo de intérprete de Libras para o "
                    "pyBRAS_conversor_libras_wav.py: encontra o(a) intérprete no quadro, "
                    "recorta em 3:4 ao redor dele(a), remove chroma key (fundo verde/azul) "
                    "sobre preto e exporta em 480x640, 24 fps, H.264 1 Mbps."
    )
    parser.add_argument("input", type=Path, help="arquivo de vídeo de origem")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="caminho do vídeo de saída (padrão: <entrada>_preparado.mp4)")
    parser.add_argument("--preview", action="store_true",
                        help="não codifica o vídeo inteiro; gera dois .jpg: o resultado final "
                             "de um frame e o frame original com a área detectada marcada")
    parser.add_argument("--chroma", choices=["auto", "verde", "azul", "nao"], default="auto",
                        help="remoção de chroma key: auto-detectar (padrão), forçar verde/azul, "
                             "ou 'nao' para desativar mesmo que haja fundo colorido")
    parser.add_argument("--cor-chroma", default=None, metavar="0xRRGGBB",
                        help="cor exata do chroma (sobrepõe a média auto-detectada)")
    parser.add_argument("--similaridade", type=float, default=0.10,
                        help="tolerância do chromakey, 0.01-0.5 (padrão: 0.10; aumente se "
                             "sobrar fundo, diminua se a pessoa ficar transparente)")
    parser.add_argument("--mistura", type=float, default=0.05,
                        help="suavização das bordas do chromakey (padrão: 0.05)")
    parser.add_argument("--margem", type=float, default=0.10,
                        help="folga ao redor da área detectada, como fração dela (padrão: 0.10)")
    parser.add_argument("--cobertura-fps", type=float, default=6.0,
                        help="verificação final de cobertura: o vídeo INTEIRO é varrido a esta "
                             "taxa de frames por segundo para garantir que as mãos nunca saem "
                             "do recorte, ampliando-o se necessário (padrão: 6; use 0 para "
                             "desativar, ou 12 para sinais muito rápidos)")
    parser.add_argument("--amostras", type=int, default=DEFAULT_SAMPLES,
                        help=f"quantos frames analisar ao longo do vídeo (padrão: {DEFAULT_SAMPLES})")
    parser.add_argument("--crop", default=None, metavar="L:A:X:Y",
                        help="pula a detecção e usa este recorte manual, em pixels do vídeo "
                             "original (LARGURA:ALTURA:X:Y)")
    args = parser.parse_args()

    require_tool("ffmpeg")
    require_tool("ffprobe")

    if not args.input.exists():
        sys.exit(f"erro: {args.input}: arquivo não encontrado")

    stem = args.input.with_suffix("")
    output_path = args.output or stem.with_name(stem.name + "_preparado.mp4")
    if not args.preview and output_path.exists():
        sys.exit(f"erro: {output_path} já existe, abortando")

    src_w, src_h, duration = probe(args.input)
    print(f"Analisando {args.input.name} ({src_w}x{src_h}, {duration:.1f}s)")

    with tempfile.TemporaryDirectory(prefix="slv_prep_") as tmp_str:
        tmp_dir = Path(tmp_str)
        frames, aw, ah = extract_samples(args.input, duration, max(2, args.amostras), tmp_dir)
    scale_back = src_w / aw  # analysis px -> source px

    # --- chroma -----------------------------------------------------------
    chroma_channel = chroma_color = None
    if args.chroma != "nao":
        detected_channel, detected_color = detect_chroma(frames, aw, ah)
        if args.chroma in ("verde", "azul"):
            chroma_channel = args.chroma
            chroma_color = detected_color if detected_channel == args.chroma else None
            if chroma_color is None:
                chroma_color = "0x00FF00" if args.chroma == "verde" else "0x0000FF"
        else:
            chroma_channel, chroma_color = detected_channel, detected_color
    if args.cor_chroma:
        chroma_color = args.cor_chroma
        if chroma_channel is None:
            chroma_channel = "verde"
    if chroma_channel:
        print(f"  chroma key:       fundo {chroma_channel} detectado (cor média {chroma_color}) — "
              f"será removido e substituído por preto")
    else:
        print("  chroma key:       nenhum fundo verde/azul detectado — mantendo o fundo original")

    # --- interpreter localization ------------------------------------------
    paint_src = []
    if args.crop:
        crop = parse_manual_crop(args.crop)
        print(f"  recorte manual:   {crop[2]}x{crop[3]} em x={crop[0]}, y={crop[1]}")
    else:
        if chroma_channel:
            person, backdrop, paintable, unavoidable = locate_by_chroma(frames, aw, ah, chroma_channel)
            method = "silhueta sobre o chroma"
        else:
            person, backdrop, paintable, unavoidable = locate_by_motion(frames, aw, ah)
            method = "movimento (mãos/rosto)"
        if person is None:
            sys.exit(
                "erro: não foi possível localizar o(a) intérprete automaticamente "
                "(pouco contraste ou pouco movimento nas amostras analisadas). "
                "Use --crop L:A:X:Y para definir o recorte manualmente, ou aumente --amostras."
            )

        bounds = backdrop if backdrop is not None else (0, 0, aw, ah)
        if backdrop is not None:
            back_cov = ((backdrop[2] - backdrop[0]) * (backdrop[3] - backdrop[1])) / (aw * ah)
            if back_cov < 0.90:
                print(f"  fundo verde:      cobre ~{back_cov:.0%} do quadro — o recorte será "
                      f"limitado à área do chroma (o que está fora dele não pode virar preto)")

        if paintable:
            print(f"  objetos:          {len(paintable)} objeto(s) sobre o fundo verde "
                  f"(ex.: ventilador, cabo) serão cobertos com preto, já que o(a) "
                  f"intérprete nunca passa na frente deles")
        if unavoidable and chroma_channel:
            print("  atenção:          há objeto(s) que o(a) intérprete encobre em algum momento — "
                  "não podem ser removidos automaticamente. Confira com --preview; se aparecerem, "
                  "use --crop ou a Etapa 0 manual", file=sys.stderr)
        if not chroma_channel:
            bounds, unavoidable = steer_away_from_obstacles(bounds, person, unavoidable)
            if unavoidable:
                print("  atenção:          há área(s) de movimento sobrepostas ao(à) intérprete "
                      "(reflexo, TV, ventilador?) — confira com --preview; se aparecerem, "
                      "use --crop ou a Etapa 0 manual", file=sys.stderr)

        # Paint boxes go to ffmpeg in source coordinates.
        paint_src = []
        for (ox0, oy0, ox1, oy1) in paintable:
            px = int(ox0 * scale_back); py = int(oy0 * scale_back)
            pw = int((ox1 - ox0) * scale_back) + 2
            ph = int((oy1 - oy0) * scale_back) + 2
            paint_src.append((max(px, 0), max(py, 0),
                              min(pw, src_w - max(px, 0)), min(ph, src_h - max(py, 0))))

        cov_w = (person[2] - person[0]) / aw
        print(f"  intérprete:       localizado por {method} "
              f"(ocupa ~{cov_w:.0%} da largura do quadro original)")

        if args.cobertura_fps > 0:
            print(f"  cobertura:        varrendo o vídeo inteiro a {args.cobertura_fps:g} "
                  f"frames/s para garantir que as mãos nunca saem do recorte...")
            person, n_checked, n_expanded = verify_hand_coverage(
                args.input, aw, ah, person, bounds, args.margem,
                args.cobertura_fps, chroma_channel if chroma_channel else None,
                paintable if chroma_channel else [],
            )
            if n_expanded:
                print(f"  cobertura:        recorte ampliado — mãos encontradas fora do "
                      f"enquadramento inicial em {n_expanded} de {n_checked} frames "
                      f"verificados (momentos que as amostras iniciais não pegaram)")
            else:
                print(f"  cobertura:        ok — silhueta dentro do recorte em todos os "
                      f"{n_checked} frames verificados")

        crop_a = expand_to_aspect(person, args.margem, bounds)
        crop = to_even_source_crop(crop_a, scale_back, src_w, src_h)
        print(f"  recorte 3:4:      {crop[2]}x{crop[3]} em x={crop[0]}, y={crop[1]}")

    graph = build_filtergraph(crop, chroma_color, chroma_channel,
                              args.similaridade, args.mistura,
                              paint_boxes=paint_src if not args.crop else ())

    if args.preview:
        write_previews(args.input, duration, graph, crop, stem)
        return

    print(f"  saída:            {TARGET_WIDTH}x{TARGET_HEIGHT}, {TARGET_FPS} fps, "
          f"H.264 @ {TARGET_BITRATE}bps, sem áudio\n")
    encode(args.input, output_path, graph)
    print(f"Sucesso! {output_path} foi gravado — use este arquivo como entrada do "
          f"pyBRAS_conversor_libras_wav.py")
    verify_output(output_path)


if __name__ == "__main__":
    main()
