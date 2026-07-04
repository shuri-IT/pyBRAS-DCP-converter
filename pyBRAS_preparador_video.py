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
BORDER_RING = 0.10                # outer 10% ring sampled for chroma detection
BORDER_KEY_FRACTION = 0.45        # ring must be >=45% key-like to auto-enable


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
    """Inspect the outer border ring of every sampled frame. If it is
    dominated by green or blue, return ('verde'|'azul', '0xRRGGBB' mean key
    color); otherwise (None, None)."""
    ring_w = max(2, int(aw * BORDER_RING))
    ring_h = max(2, int(ah * BORDER_RING))

    counts = {"verde": 0, "azul": 0}
    sums = {"verde": [0, 0, 0], "azul": [0, 0, 0]}
    total = 0

    for rgb in frames:
        for y in range(ah):
            on_band_y = y < ring_h or y >= ah - ring_h
            row = y * aw * 3
            for x in range(0, aw, 2):  # every 2nd pixel: plenty for statistics
                if not (on_band_y or x < ring_w or x >= aw - ring_w):
                    continue
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
    for ch in ("verde", "azul"):
        if counts[ch] / total >= BORDER_KEY_FRACTION:
            n = counts[ch]
            mean = [sums[ch][0] // n, sums[ch][1] // n, sums[ch][2] // n]
            return ch, "0x{:02X}{:02X}{:02X}".format(*mean)
    return None, None


# --------------------------------------------------------------------------
# Interpreter localization
# --------------------------------------------------------------------------

def bbox_from_occupancy(col_counts, row_counts, aw: int, ah: int):
    """Turn per-column / per-row foreground counts into a bbox, ignoring
    rows/cols with only speckle noise. Returns (x0, y0, x1, y1) or None."""
    col_min = max(2, int(ah * OCCUPANCY_FRACTION))
    row_min = max(2, int(aw * OCCUPANCY_FRACTION))
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


def locate_by_chroma(frames, aw, ah, channel):
    """Foreground = anything that is not key-colored. Union over time."""
    box = None
    for rgb in frames:
        col_counts = [0] * aw
        row_counts = [0] * ah
        for y in range(ah):
            row = y * aw * 3
            for x in range(aw):
                i = row + x * 3
                if not is_keyish(rgb[i], rgb[i + 1], rgb[i + 2], channel, KEY_MASK_FACTOR):
                    col_counts[x] += 1
                    row_counts[y] += 1
        box = union_bbox(box, bbox_from_occupancy(col_counts, row_counts, aw, ah))
    return box


def locate_by_motion(frames, aw, ah):
    """Foreground = pixels that changed between consecutive samples (the
    signer's hands, arms and face). Union over all pairs."""
    if len(frames) < 2:
        return None
    box = None
    for prev, cur in zip(frames, frames[1:]):
        col_counts = [0] * aw
        row_counts = [0] * ah
        for y in range(ah):
            row = y * aw * 3
            for x in range(aw):
                i = row + x * 3
                # cheap luma approximation: (2R + 4G + B) / 7
                g0 = (2 * prev[i] + 4 * prev[i + 1] + prev[i + 2]) // 7
                g1 = (2 * cur[i] + 4 * cur[i + 1] + cur[i + 2]) // 7
                if abs(g1 - g0) >= MOTION_THRESHOLD:
                    col_counts[x] += 1
                    row_counts[y] += 1
        box = union_bbox(box, bbox_from_occupancy(col_counts, row_counts, aw, ah))
    return box


# --------------------------------------------------------------------------
# Crop geometry
# --------------------------------------------------------------------------

def expand_to_aspect(box, margin: float, src_w: int, src_h: int):
    """Add a safety margin around the detection box, then grow it to an
    exact 3:4 portrait rectangle centered on the interpreter, clamped to the
    source frame. Returns (x, y, w, h) with even values."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0

    mx, my = bw * margin, bh * margin
    x0, y0 = x0 - mx, y0 - my
    x1, y1 = x1 + mx, y1 + my

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0

    # Grow the short direction to hit exactly 3:4 (never shrink content).
    if w / h < TARGET_ASPECT:
        w = h * TARGET_ASPECT
    else:
        h = w / TARGET_ASPECT

    w, h = min(w, src_w), min(h, src_h)
    x = min(max(cx - w / 2, 0), src_w - w)
    y = min(max(cy - h / 2, 0), src_h - h)

    # Even integers for yuv420p-friendly cropping.
    xi, yi = int(x) // 2 * 2, int(y) // 2 * 2
    wi, hi = int(w) // 2 * 2, int(h) // 2 * 2
    wi = min(wi, (src_w - xi) // 2 * 2)
    hi = min(hi, (src_h - yi) // 2 * 2)
    return xi, yi, max(wi, 2), max(hi, 2)


def parse_manual_crop(text: str):
    m = re.fullmatch(r"(\d+):(\d+):(\d+):(\d+)", text.strip())
    if not m:
        sys.exit("erro: --crop deve estar no formato LARGURA:ALTURA:X:Y (ex.: 600:800:200:0)")
    w, h, x, y = (int(v) for v in m.groups())
    return x, y, w, h


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------

def build_filtergraph(crop, chroma_color, chroma_channel, similarity, blend):
    """Return the -filter_complex string: crop -> (chromakey over black) ->
    fps/scale/pad to 480x640."""
    x, y, w, h = crop
    tail = (
        f"fps={TARGET_FPS},"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,format=yuv420p"
    )
    crop_expr = f"crop={w}:{h}:{x}:{y}"
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
    if args.crop:
        crop = parse_manual_crop(args.crop)
        print(f"  recorte manual:   {crop[2]}x{crop[3]} em x={crop[0]}, y={crop[1]}")
    else:
        if chroma_channel:
            box = locate_by_chroma(frames, aw, ah, chroma_channel)
            method = "silhueta sobre o chroma"
        else:
            box = locate_by_motion(frames, aw, ah)
            method = "movimento (mãos/rosto)"
        if box is None:
            sys.exit(
                "erro: não foi possível localizar o(a) intérprete automaticamente "
                "(pouco contraste ou pouco movimento nas amostras analisadas). "
                "Use --crop L:A:X:Y para definir o recorte manualmente, ou aumente --amostras."
            )
        src_box = tuple(v * scale_back for v in box)
        crop = expand_to_aspect(src_box, args.margem, src_w, src_h)
        cov_w = (box[2] - box[0]) / aw
        print(f"  intérprete:       localizado por {method} "
              f"(ocupa ~{cov_w:.0%} da largura do quadro original)")
        print(f"  recorte 3:4:      {crop[2]}x{crop[3]} em x={crop[0]}, y={crop[1]}")

    graph = build_filtergraph(crop, chroma_color, chroma_channel,
                              args.similaridade, args.mistura)

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
