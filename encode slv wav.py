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


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: required tool '{name}' not found on PATH")


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
        "-vf", f"fps={FORCED_FPS},scale={FORCED_WIDTH}:{FORCED_HEIGHT}:flags=lanczos,setsar=1",
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encode a video into a DCP channel 15 (Sign Language Video) PCM WAV file."
    )
    parser.add_argument("input", type=Path, help="source video file")
    parser.add_argument("-o", "--output", type=Path, default=None,
                         help="output .wav path (default: <input>.wav)")
    parser.add_argument("-c", "--chunk-duration", type=float, default=2.0,
                         help="seconds of audio/VP9 per block (default: 2.0, per spec)")
    args = parser.parse_args()

    require_tool("ffmpeg")

    if not args.input.exists():
        sys.exit(f"error: {args.input}: no such file")

    output_path = args.output or args.input.with_suffix(".wav")
    if output_path.exists():
        sys.exit(f"error: {output_path} already exists, aborting")

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


if __name__ == "__main__":
    main()
