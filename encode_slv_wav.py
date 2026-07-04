#!/usr/bin/env python3
"""
encode_slv_wav.py

Encode a video into a 24-bit / 48 kHz uncompressed PCM WAV file suitable for
DCP audio channel 15 (Sign Language Video / MCA tag "Sign Language Video
Stream"), per ISDCF Doc13 "Sign Language Video Encoding for Digital Cinema":

    https://github.com/ISDCF/Sign-Language-Video-Encoding

Pipeline
--------
1. ffmpeg transcodes the source video to a VP9 elementary stream, forced to
   24.0 fps and 480x640, using the 'webm_chunk' muxer so ffmpeg itself splits
   the bitstream into fixed-duration segments time-aligned to the PCM grid
   (one shared EBML/WebM header + N VP9 segment files). VP9 keyframes are
   forced at every chunk boundary so each block is independently decodable.
2. Each VP9 segment is wrapped into a fixed-size PCM block:

       H1 = 0xFFFFFFFF                              (4 bytes, big-endian)
       Lv = len(VP9 segment)                         (4 bytes, big-endian)
       Lb = length of this PCM block                 (4 bytes, big-endian)
       Le = len(VP9 EBML header)                     (4 bytes, big-endian)
       H2 = 0xFFFFFFFF                                (4 bytes, big-endian)
       E  = VP9 EBML header                           (Le bytes)
       P  = b'\\x00' * (Lb - Lv - Le - 20)             (padding)

   i.e. 20 bytes of header fields + E + the VP9 segment + null padding,
   for a total of exactly Lb bytes per block.
3. The concatenated blocks are raw 24-bit/48kHz mono PCM samples. ffmpeg
   wraps that raw stream in a standard WAV container (no re-encoding, just
   header construction) to produce the final .wav file.

Requires ffmpeg/ffprobe with libvpx-vp9 and the webm_chunk muxer (ffmpeg
>= 3.2.4, per the upstream tool's own requirement).
"""

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# --- DCP / ISDCF Doc13 constants -------------------------------------------
MARKER = 0xFFFFFFFF        # H1 / H2 sync markers
SAMPLE_RATE = 48000         # DCP-mandated PCM sample rate (96 kHz prohibited)
BITS_PER_SAMPLE = 24        # DCP-mandated bit depth
CHANNELS = 1                # channel 15 carries one mono PCM stream
BLOCK_HEADER_LEN = 20       # H1 + Lv + Lb + Le + H2 = 5 * 4 bytes

FORCED_FPS = 24             # spec: 24.0 fps regardless of the reel's fps
FORCED_WIDTH = 480          # spec: portrait 480 (w) x 640 (h)
FORCED_HEIGHT = 640

# Video bitrate left under the full channel bit-rate (48000*24 = 1.152 Mbps)
# to leave headroom for block headers/padding; matches the reference encoder.
VIDEO_BITRATE_BPS = SAMPLE_RATE * BITS_PER_SAMPLE // 2  # 576,000 bps

# If the source's aspect ratio is far enough from 3:4 that letterboxing would
# shrink it below this fraction of the 480x640 frame, refuse to proceed
# silently — this is the threshold that triggers the pre-flight warning.
MIN_FRAME_COVERAGE = 0.70


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: required tool '{name}' not found on PATH")


def probe_duration_secs(input_path: Path) -> float:
    """Return the source's duration in seconds via ffprobe, or 0.0 if unknown."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(input_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0.0))
    except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        return 0.0


def probe_video_geometry(input_path: Path):
    """Return (width, height, has_video) for the first video stream, with
    width/height already swapped if rotation metadata says the display
    orientation differs from the coded orientation (e.g. phone video shot
    in portrait but stored coded as landscape with a 90/270 rotate tag)."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(input_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return (0, 0, False)

    video_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        return (0, 0, False)
    stream = video_streams[0]

    w = int(stream.get("width", 0) or 0)
    h = int(stream.get("height", 0) or 0)

    rotation = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
            break
    if rotation == 0:
        tag_rotate = stream.get("tags", {}).get("rotate")
        if tag_rotate:
            try:
                rotation = int(tag_rotate)
            except ValueError:
                rotation = 0

    if abs(rotation) in (90, 270):
        w, h = h, w

    return (w, h, True)


def letterbox_coverage(src_w: int, src_h: int, target_w: int = FORCED_WIDTH,
                        target_h: int = FORCED_HEIGHT) -> float:
    """Fraction of the target_w x target_h frame actually covered by the
    source content after an aspect-preserving scale-to-fit (i.e. how much
    of the frame is signal vs. how much is letterbox padding)."""
    if src_w <= 0 or src_h <= 0:
        return 1.0  # unknown geometry: don't block on a probe failure
    scale = min(target_w / src_w, target_h / src_h)
    fitted_w = src_w * scale
    fitted_h = src_h * scale
    return (fitted_w * fitted_h) / (target_w * target_h)


def encode_vp9_chunks(input_path: Path, build_dir: Path, chunk_len_frames: int) -> Path:
    """Transcode input_path to chunked VP9 (forced 24fps/480x640) using ffmpeg's
    webm_chunk muxer. Returns the path to the shared EBML header file; the
    individual VP9 segment files are written alongside it as chunk_NNNNN.chk.
    """
    header_path = build_dir / "chunk.hdr"
    chunk_pattern = build_dir / "chunk_%05d.chk"

    cmd = [
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-i", str(input_path),
        "-map", "0:v:0",
        # Force 24.0 fps and exact 480x640 resolution as required by the spec.
        # Scale to fit *without* distorting the source's aspect ratio, then
        # letterbox-pad to hit the exact 480x640 the spec requires. For a
        # source that's already 480x640 (or already 3:4) this is a no-op —
        # existing correctly-shaped inputs are unaffected.
        "-vf", (
            f"fps={FORCED_FPS},"
            f"scale={FORCED_WIDTH}:{FORCED_HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={FORCED_WIDTH}:{FORCED_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        ),
        "-pix_fmt", "yuv420p",
        "-c:v", "libvpx-vp9",
        "-keyint_min", str(chunk_len_frames), "-g", str(chunk_len_frames),
        "-speed", "6", "-tile-columns", "4", "-frame-parallel", "1", "-threads", "8",
        "-static-thresh", "0", "-max-intra-rate", "300", "-deadline", "realtime",
        "-lag-in-frames", "0", "-error-resilient", "1",
        "-b:v", str(VIDEO_BITRATE_BPS),
        "-minrate", str(VIDEO_BITRATE_BPS),
        "-maxrate", str(VIDEO_BITRATE_BPS),
        "-an", "-sn",
        "-f", "webm_chunk",
        "-header", str(header_path),
        "-chunk_start_index", "1",
        str(chunk_pattern),
    ]
    subprocess.run(cmd, check=True)

    if not header_path.exists():
        sys.exit("error: ffmpeg did not produce a VP9/EBML header file")
    return header_path


def build_pcm_blocks(build_dir: Path, ebml_header: bytes, chunk_len_bytes: int) -> Path:
    """Read each VP9 segment chunk, wrap it per the H1/Lv/Lb/Le/H2/E/P layout,
    pad to chunk_len_bytes, and write the concatenated blocks as raw PCM."""
    le = len(ebml_header)
    raw_pcm_path = build_dir / "slv_pcm.raw"

    chunk_files = sorted(build_dir.glob("chunk_*.chk"))
    if not chunk_files:
        sys.exit("error: no VP9 segment chunks were produced")

    with open(raw_pcm_path, "wb") as out:
        for chunk_file in chunk_files:
            vp9_seg = chunk_file.read_bytes()
            lv = len(vp9_seg)
            lb = chunk_len_bytes

            if BLOCK_HEADER_LEN + le + lv > lb:
                sys.exit(
                    f"error: {chunk_file.name} segment ({lv} bytes) + EBML header "
                    f"({le} bytes) exceeds block size ({lb} bytes). "
                    f"Increase --chunk-duration or lower the VP9 bitrate."
                )

            block_header = struct.pack(">IIIII", MARKER, lv, lb, le, MARKER)
            padding = b"\x00" * (lb - lv - le - BLOCK_HEADER_LEN)
            block = block_header + ebml_header + vp9_seg + padding

            assert len(block) == lb, "constructed PCM block has the wrong length"
            out.write(block)

    return raw_pcm_path


def export_preview_frame(input_path: Path, preview_path: Path) -> None:
    """Extract a single representative frame *after* the same scale/pad
    filter chain used for encoding, so a human can eyeball the framing
    before committing to a full encode."""
    cmd = [
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-i", str(input_path),
        "-vf", (
            f"scale={FORCED_WIDTH}:{FORCED_HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={FORCED_WIDTH}:{FORCED_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        ),
        "-vframes", "1",
        str(preview_path),
    ]
    subprocess.run(cmd, check=True)


def wrap_as_wav(raw_pcm_path: Path, output_path: Path) -> None:
    """Wrap raw 24-bit/48kHz mono PCM samples in a standard WAV container."""
    cmd = [
        "ffmpeg", "-loglevel", "error", "-hide_banner", "-y",
        "-f", "s24le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "-i", str(raw_pcm_path),
        "-c:a", "pcm_s24le",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


WAVE_FORMAT_PCM = 1
WAVE_FORMAT_EXTENSIBLE = 0xFFFE


def read_riff_chunks(data: bytes):
    """Yield (chunk_id: bytes, data_offset: int, size: int) for each RIFF
    sub-chunk after the 12-byte RIFF/WAVE preamble. Chunks are word-aligned
    per the RIFF spec, so odd-sized chunks are followed by a pad byte."""
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        yield (chunk_id, pos + 8, size)
        pos += 8 + size + (size & 1)  # word-align


def validate_wav(wav_path: Path, chunk_duration: float) -> None:
    """Read back a produced WAV and verify it actually conforms to the ISDCF
    Doc13 block layout: correct PCM format, whole number of fixed-size
    blocks, valid H1/H2 markers, and internally-consistent Lb/Le/Lv fields.
    Exits non-zero on any failure so this is usable in scripts/CI.

    Walks RIFF sub-chunks generically rather than assuming a fixed 44-byte
    header — real-world encoders (including ffmpeg) may write
    WAVE_FORMAT_EXTENSIBLE fmt chunks and extra chunks (e.g. LIST/INFO)
    before 'data'."""
    if not wav_path.exists():
        sys.exit(f"error: {wav_path}: no such file")

    data = wav_path.read_bytes()

    def fail(msg: str) -> None:
        sys.exit(f"FAIL: {msg}")

    try:
        chunks = list(read_riff_chunks(data))
    except ValueError as e:
        fail(str(e))
        return

    fmt_chunk = next((c for c in chunks if c[0] == b"fmt "), None)
    data_chunk = next((c for c in chunks if c[0] == b"data"), None)

    if fmt_chunk is None:
        fail("no 'fmt ' chunk found")
    if data_chunk is None:
        fail("no 'data' chunk found")

    _, fmt_off, fmt_size = fmt_chunk
    if fmt_size < 16:
        fail(f"'fmt ' chunk is only {fmt_size} bytes, expected at least 16")

    audio_format = struct.unpack("<H", data[fmt_off:fmt_off + 2])[0]
    channels = struct.unpack("<H", data[fmt_off + 2:fmt_off + 4])[0]
    sample_rate = struct.unpack("<I", data[fmt_off + 4:fmt_off + 8])[0]
    bits_per_sample = struct.unpack("<H", data[fmt_off + 14:fmt_off + 16])[0]

    if audio_format not in (WAVE_FORMAT_PCM, WAVE_FORMAT_EXTENSIBLE):
        fail(f"audio format code is 0x{audio_format:04X}, expected PCM (1) or EXTENSIBLE (0xFFFE)")
    if (sample_rate, bits_per_sample, channels) != (SAMPLE_RATE, BITS_PER_SAMPLE, CHANNELS):
        fail(
            f"format is {sample_rate} Hz / {bits_per_sample}-bit / {channels}ch, "
            f"expected {SAMPLE_RATE} Hz / {BITS_PER_SAMPLE}-bit / {CHANNELS}ch"
        )

    _, data_off, declared_size = data_chunk
    actual_available = len(data) - data_off
    data_size = min(declared_size, actual_available)
    pcm = data[data_off:data_off + data_size]

    bytes_per_second = SAMPLE_RATE * BITS_PER_SAMPLE // 8 * CHANNELS
    block_len = int(bytes_per_second * chunk_duration)

    if len(pcm) % block_len != 0:
        fail(
            f"PCM data ({len(pcm)} bytes) is not a whole number of "
            f"{block_len}-byte blocks (remainder {len(pcm) % block_len})"
        )

    num_blocks = len(pcm) // block_len
    if num_blocks == 0:
        fail("no PCM blocks found")

    for i in range(num_blocks):
        block = pcm[i * block_len : (i + 1) * block_len]
        h1, lv, lb, le, h2 = struct.unpack(">IIIII", block[:20])
        if h1 != MARKER or h2 != MARKER:
            fail(f"block {i}: missing 0xFFFFFFFF marker(s)")
        if lb != block_len:
            fail(f"block {i}: Lb={lb}, expected {block_len}")
        if BLOCK_HEADER_LEN + le + lv > lb:
            fail(f"block {i}: Le+Lv+20 ({BLOCK_HEADER_LEN + le + lv}) exceeds Lb ({lb})")

    print(
        f"OK: {wav_path.name} — {num_blocks} block(s) x {block_len} bytes, "
        f"~{num_blocks * chunk_duration:g}s of video, "
        f"{sample_rate} Hz / {bits_per_sample}-bit / {channels}ch PCM"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encode a video into a DCP channel 15 (Sign Language Video) PCM WAV file."
    )
    parser.add_argument("input", type=Path, help="source video file")
    parser.add_argument("-o", "--output", type=Path, default=None,
                         help="output .wav path (default: <input>.wav)")
    parser.add_argument("-c", "--chunk-duration", type=float, default=2.0,
                         help="seconds of audio/VP9 per block (default: 2.0, per spec)")
    parser.add_argument("--check", action="store_true",
                         help="don't encode; instead validate that 'input' (a .wav) "
                              "conforms to the ISDCF Doc13 block structure")
    parser.add_argument("--no-validate", action="store_true",
                         help="skip the automatic self-check after encoding")
    parser.add_argument("--preview", nargs="?", const="__default__", default=None,
                         help="write a single letterboxed preview frame (.jpg) instead of "
                              "encoding, so you can eyeball the framing first. Optional path; "
                              "defaults to <input>.preview.jpg")
    parser.add_argument("--force", action="store_true",
                         help="proceed even if the source's aspect ratio would result in "
                              "heavy letterboxing (skips the interactive confirmation)")
    args = parser.parse_args()

    require_tool("ffmpeg")
    require_tool("ffprobe")

    if args.check:
        validate_wav(args.input, args.chunk_duration)
        return

    if args.preview is not None:
        if not args.input.exists():
            sys.exit(f"error: {args.input}: no such file")
        preview_path = (
            args.input.with_suffix(".preview.jpg")
            if args.preview == "__default__"
            else Path(args.preview)
        )
        export_preview_frame(args.input, preview_path)
        w, h, has_video = probe_video_geometry(args.input)
        if has_video:
            coverage = letterbox_coverage(w, h)
            print(
                f"Wrote preview frame: {preview_path}\n"
                f"  source: {w}x{h} (rotation-adjusted)\n"
                f"  frame coverage after letterboxing: {coverage:.0%}"
            )
        else:
            print(f"Wrote preview frame: {preview_path}")
        return

    if not args.input.exists():
        sys.exit(f"error: {args.input}: no such file")

    output_path = args.output or args.input.with_suffix(".wav")
    if output_path.exists():
        sys.exit(f"error: {output_path} already exists, aborting")

    duration = probe_duration_secs(args.input)
    if duration and duration < args.chunk_duration:
        sys.exit(
            f"error: source is {duration:.2f}s long, shorter than one "
            f"{args.chunk_duration:g}s chunk. Need at least one full chunk to encode."
        )

    w, h, has_video = probe_video_geometry(args.input)
    if not has_video:
        sys.exit(f"error: {args.input} contains no video stream")

    coverage = letterbox_coverage(w, h)
    if coverage < MIN_FRAME_COVERAGE and not args.force:
        letterboxed_w = round(w * min(FORCED_WIDTH / w, FORCED_HEIGHT / h))
        letterboxed_h = round(h * min(FORCED_WIDTH / w, FORCED_HEIGHT / h))
        warning = (
            f"\nwarning: source is {w}x{h}; fitting it into the required "
            f"{FORCED_WIDTH}x{FORCED_HEIGHT} portrait frame without distortion means "
            f"it will be scaled to only {letterboxed_w}x{letterboxed_h} and letterboxed "
            f"with black bars — covering just {coverage:.0%} of the frame.\n"
            f"The interpreter may appear small and hard to see. Consider re-cropping the "
            f"source to roughly a 3:4 portrait ratio before encoding.\n"
            f"Run with --preview to see exactly what the output frame will look like.\n"
        )
        print(warning, file=sys.stderr)
        if sys.stdin.isatty():
            answer = input("Continue anyway with heavy letterboxing? [y/N]: ").strip().lower()
            if answer != "y":
                sys.exit("Aborted. Re-run with --force to skip this prompt once you're sure.")
        else:
            sys.exit(
                "error: refusing to proceed non-interactively with heavy letterboxing. "
                "Re-run with --force once you've confirmed this is acceptable."
            )

    chunk_len_frames = round(args.chunk_duration * FORCED_FPS)
    bytes_per_second = SAMPLE_RATE * BITS_PER_SAMPLE // 8 * CHANNELS
    chunk_len_bytes = int(bytes_per_second * args.chunk_duration)

    print(
        f"Encoding {args.input.name}\n"
        f"  forced video:  {FORCED_FPS} fps, {FORCED_WIDTH}x{FORCED_HEIGHT}, VP9 @ {VIDEO_BITRATE_BPS} bps\n"
        f"  block length:  {args.chunk_duration:g}s = {chunk_len_frames} frames = {chunk_len_bytes} bytes\n"
        f"  output PCM:    {BITS_PER_SAMPLE}-bit / {SAMPLE_RATE} Hz / {CHANNELS} channel\n"
    )

    with tempfile.TemporaryDirectory(prefix="slv_encode_") as build_dir_str:
        build_dir = Path(build_dir_str)

        header_path = encode_vp9_chunks(args.input, build_dir, chunk_len_frames)
        ebml_header = header_path.read_bytes()
        header_path.unlink()  # don't let it get swept up by the chunk_*.chk glob

        raw_pcm_path = build_pcm_blocks(build_dir, ebml_header, chunk_len_bytes)
        wrap_as_wav(raw_pcm_path, output_path)

    print(f"Success! Wrote {output_path} (use this file for DCP audio channel 15)")

    if not args.no_validate:
        validate_wav(output_path, args.chunk_duration)


if __name__ == "__main__":
    main()
