#!/usr/bin/env python3
"""Split an SVG into a grid of tiles and reassemble into a mosaic.

By default, tiles are kept in row-major order. Use --shuffle to randomize
tile positions and apply a random 90-degree rotation to each tile.

Usage:
    python svg-tiles-shuffler.py <input_svg> <n> [options]
    python svg-tiles-shuffler.py <input_svg> --rows R --cols C [options]

Examples:
    python svg-tiles-shuffler.py drawing.svg 4                   4x4 square grid
    python svg-tiles-shuffler.py drawing.svg 4 --shuffle --seed 42
    python svg-tiles-shuffler.py drawing.svg --rows 3 --cols 5   3x5 rectangular
    python svg-tiles-shuffler.py drawing.svg 4 --paper a4        output on A4
    python svg-tiles-shuffler.py drawing.svg 4 --paper a4 --square  square on A4
    python svg-tiles-shuffler.py drawing.svg 4 --shuffle --no-rotate
"""

import argparse
import random
import shutil
import subprocess
import sys
from pathlib import Path


# Paper dimensions in mm (portrait: short side first).
# Used to auto-derive canvas proportions when --paper is set.
DEFAULT_PAGE_SIZE = (1000, 1000)  # px — canvas size when --paper is not set

PAPER_SIZES = {
    "a6": (105, 148),
    "a5": (148, 210),
    "a4": (210, 297),
    "a3": (297, 420),
    "a2": (420, 594),
    "letter": (216, 279),
    "legal":  (216, 356),
    "tabloid": (279, 432),
}


def fmt(v: float) -> str:
    """Format a float cleanly for vpype arguments (no trailing zeros)."""
    return f"{v:g}"



def parse_length(s: str) -> float:
    """Parse a length string (e.g. '5mm', '1cm', '0.5in', '20px', '20') to CSS px."""
    s = s.strip().lower()
    if s.endswith("mm"):
        return float(s[:-2]) * 96 / 25.4
    elif s.endswith("cm"):
        return float(s[:-2]) * 96 / 2.54
    elif s.endswith("in"):
        return float(s[:-2]) * 96
    elif s.endswith("px"):
        return float(s[:-2])
    else:
        return float(s)  # bare number = px
def run_vpype(args: list[str]) -> None:
    """Run vpype with the given arguments, abort on failure."""
    # Find vpype executable next to the running python (works inside venvs)
    vpype_bin = Path(sys.executable).parent / ("vpype.exe" if sys.platform == "win32" else "vpype")
    if vpype_bin.exists():
        cmd = [str(vpype_bin)] + args
    else:
        cmd = ["vpype"] + args  # fallback: assume vpype is on PATH
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("vpype reported an error. Aborting.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split an SVG into a grid of tiles and reassemble.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s drawing.svg 4                                 4x4 square mosaic
  %(prog)s drawing.svg 4 --shuffle --seed 42             reproducible shuffle
  %(prog)s drawing.svg --rows 3 --cols 5                  3 rows x 5 columns
  %(prog)s drawing.svg 4 --paper a4                       output on A4
  %(prog)s drawing.svg 4 --paper a4 --margin 15mm         A4 with 15mm margin
  %(prog)s drawing.svg 4 --paper a5 --landscape           landscape A5
  %(prog)s drawing.svg --rows 3 --cols 5 --paper a4 --square  rectangular grid, square canvas
  %(prog)s drawing.svg 4 --shuffle --no-rotate            shuffle without rotation
""",
    )
    parser.add_argument("input_svg", type=str, help="Path to the input SVG file")
    parser.add_argument(
        "n", type=int, nargs="?", default=None,
        help="Square grid shorthand: n rows x n cols",
    )
    parser.add_argument(
        "--rows", type=int, default=None,
        help="Number of rows in the grid",
    )
    parser.add_argument(
        "--cols", type=int, default=None,
        help="Number of columns in the grid",
    )
    parser.add_argument(
        "--paper", type=str, default=None,
        help="Output paper size (e.g. a6, a5, a4, a3, letter). Also sets canvas proportions.",
    )
    parser.add_argument(
        "--margin", type=str, default=None,
        help="Output margin (e.g. 1cm, 10mm, 0.5in). Default: 1cm with --paper",
    )
    parser.add_argument(
        "--landscape", action="store_true",
        help="Use landscape orientation for the output paper",
    )
    parser.add_argument(
        "--square", action="store_true",
        help="Force a square grid with square tiles, centered on the page.",
    )
    parser.add_argument(
        "--gap", type=str, default="5mm",
        help="Gap between tiles (e.g. 5mm, 1cm, 0.5in, 20px). Default: 5mm.",
    )
    parser.add_argument(
        "--shuffle", action="store_true",
        help="Randomly shuffle tile positions (with rotation unless --no-rotate)",
    )
    parser.add_argument(
        "--no-rotate", action="store_true",
        help="Disable tile rotation when shuffling",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible shuffles",
    )
    parser.add_argument(
        "--keep-tiles", action="store_true",
        help="Keep the intermediate tile directory",
    )
    args = parser.parse_args()

    # --- Resolve grid dimensions ---------------------------------------
    rows = args.rows
    cols = args.cols

    if args.n is not None:
        if rows is None:
            rows = args.n
        if cols is None:
            cols = args.n
    else:
        if rows is None or cols is None:
            parser.error(
                "Either provide n for a square grid, or both --rows and --cols."
            )

    # --square: force rows = cols
    if args.square:
        if rows is not None and cols is None:
            cols = rows
        elif cols is not None and rows is None:
            rows = cols
        elif rows is None and cols is None:
            parser.error("--square needs n, --rows, or --cols.")

    # --- Dimensions (compute tile sizes accounting for gap & margin) --
    MM2PX = 96 / 25.4
    gap_px = parse_length(args.gap)
    margin_px = parse_length(args.margin or "1cm")

    if args.paper:
        # Paper mode: compute tile sizes from paper - margin - gaps
        paper_key = args.paper.lower()
        if paper_key in PAPER_SIZES:
            pw_mm, ph_mm = PAPER_SIZES[paper_key]
        elif "x" in paper_key:
            try:
                parts = paper_key.split("x")
                # parse_length handles units (mm, cm, in, px); bare numbers = px
                pw_mm = parse_length(parts[0]) / MM2PX
                ph_mm = parse_length(parts[1]) / MM2PX
            except (ValueError, IndexError):
                print(f"Warning: cannot parse '{args.paper}' as WxH. Using A4.",
                      file=sys.stderr)
                pw_mm, ph_mm = 210, 297
        else:
            pw_mm, ph_mm = 210, 297

        if args.landscape:
            pw_mm, ph_mm = ph_mm, pw_mm

        margin_mm = margin_px / MM2PX
        gap_mm = gap_px / MM2PX

        # Available area on paper (mm)
        avail_w = pw_mm - 2 * margin_mm
        avail_h = ph_mm - 2 * margin_mm

        # Tile size in mm, then convert to CSS px
        tw_mm = (avail_w - (cols - 1) * gap_mm) / cols
        th_mm = (avail_h - (rows - 1) * gap_mm) / rows

        if args.square:
            tile_mm = min(tw_mm, th_mm)
            tw_mm = th_mm = tile_mm

        uw = tw_mm * MM2PX
        uh = th_mm * MM2PX

        # Canvas = tile-only area (for scaleto/crop in step 1)
        w = cols * uw
        h = rows * uh
    else:
        # No paper: canvas is the output page
        w_page, h_page = 1000, 1000

        # Available area (page minus margin)
        avail_w = w_page - 2 * margin_px
        avail_h = h_page - 2 * margin_px

        # Tile size accounting for gaps
        uw = (avail_w - (cols - 1) * gap_px) / cols
        uh = (avail_h - (rows - 1) * gap_px) / rows

        if args.square:
            tile_px = min(uw, uh)
            uw = uh = tile_px


        # Canvas = tile-only area
        w = cols * uw
        h = rows * uh

    shuffle = args.shuffle
    rotate = shuffle and not args.no_rotate
    square_tiles = abs(uw - uh) < 0.01

    # --- Seed ----------------------------------------------------------
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Random seed: {args.seed}")

    # --- Paths ---------------------------------------------------------
    input_svg = Path(args.input_svg).resolve()
    if not input_svg.is_file():
        print(f"Error: file not found: {input_svg}", file=sys.stderr)
        sys.exit(1)

    base_name = input_svg.stem
    input_dir = input_svg.parent
    tile_dir = input_dir / f"{base_name}_tiles"
    # Build descriptive output filename
    parts = [base_name]
    parts.append(f"{rows}x{cols}")
    if args.paper:
        parts.append(args.paper.replace("x", "x"))
    if args.gap != "5mm":
        parts.append(f"gap{args.gap}")
    if args.margin and args.margin != "1cm":
        parts.append(f"m{args.margin}")
    if shuffle:
        parts.append("shuffled")
        if args.seed is not None:
            parts.append(f"s{args.seed}")
        if args.no_rotate:
            parts.append("norot")
    else:
        parts.append("mosaic")
    if args.square:
        parts.append("square")
    if args.landscape:
        parts.append("land")
    out_file = input_dir / ("_".join(parts) + ".svg")

    # Ensure the tile directory exists and is empty
    if tile_dir.exists():
        print(f"Clearing existing tile directory: {tile_dir}")
        shutil.rmtree(tile_dir)
    tile_dir.mkdir(parents=True, exist_ok=True)

    total = rows * cols

    # vpype layout defaults to portrait (swaps dims so H >= W).
    # We must pass -l when the page is landscape (wider than tall).
    # Page string is always SHORT x LONG; -l flag picks orientation.
    def layout_page(width, height):
        short, long_ = sorted([width, height])
        flag = ["-l"] if width > height else []
        return flag, f"{fmt(short)}x{fmt(long_)}"

    # Page layout helpers
    tile_orient, tile_size = layout_page(uw, uh)

    if args.paper:
        # Mosaic computed to fit paper exactly — layout with exact margin
        margin_str = args.margin or "1cm"
        paper_flags = ["--landscape"] if args.landscape else []
        final_layout_cmd = ["layout", "--fit-to-margins", margin_str, *paper_flags, args.paper]
        page_orient, page_size = layout_page(w, h)  # for step 1 only
    else:
        # No paper: output page = 1000x1000 (or square canvas)
        out_orient, out_page = layout_page(1000, 1000)
        page_orient, page_size = layout_page(w, h)  # for step 1 (tile-only area)
        final_layout_cmd = ["layout", *out_orient, "-m", fmt(margin_px), out_page]

    print(f"Grid: {rows}x{cols} = {total} tiles of {fmt(uw)}x{fmt(uh)} px")
    if args.paper:
        print(f"Paper: {args.paper}{'  landscape' if args.landscape else ''}")
        print(f"Tile: {tw_mm:.1f} x {th_mm:.1f} mm  |  gap: {gap_mm:.1f} mm  |  margin: {margin_mm:.1f} mm")
    else:
        print(f"Canvas: 1000x1000 px  |  tile: {fmt(uw)}x{fmt(uh)} px")

    # ------------------------------------------------------------------
    # Step 1: Create tiles as layers, then write each layer to a file
    # ------------------------------------------------------------------
    print(f"Cropping {input_svg} into tiles...")

    tile_output = str(tile_dir / "%_lid%.svg").replace("\\", "/")

    # vpype expressions for tile coordinates (row-major order)
    # col index = _i mod cols,  row index = floor(_i / cols)
    expr_x = f"%{fmt(uw)}*(_i - {cols}*floor(_i/{cols}))%"
    expr_y = f"%{fmt(uh)}*floor(_i/{cols})%"

    vp_args_1 = [
        "begin",
            "repeat", f"%{rows}*{cols}%",
                "read", "-l", "%_i+1%", str(input_svg),
                "scaleto", str(w), str(h),
                "layout", *page_orient, "-m", "0", page_size,
                "crop", expr_x, expr_y, fmt(uw), fmt(uh),
                "rect", "--layer", "%_i+1%", expr_x, expr_y, fmt(uw), fmt(uh),
            "end",
            "forlayer", "layout", *tile_orient, "-m", "0", tile_size, "write", tile_output,
        "end",
    ]
    run_vpype(vp_args_1)

    tiles = sorted(tile_dir.glob("*.svg"))
    tile_count = len(tiles)
    print(f"Number of tiles created: {tile_count}")

    if tile_count == 0:
        print("No tiles were created. Aborting.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Rename (and optionally shuffle) tiles
    # ------------------------------------------------------------------
    numeric_tiles = [f for f in tile_dir.glob("*.svg") if f.stem.isdigit()]
    numeric_tiles.sort(key=lambda f: int(f.stem))

    if shuffle:
        print("Shuffling the list of files...")
        random.shuffle(numeric_tiles)

    digits = max(2, len(str(len(numeric_tiles) - 1)))
    for i, tile_path in enumerate(numeric_tiles):
        new_name = f"t{i:0{digits}d}.svg"
        tile_path.rename(tile_dir / new_name)

    # ------------------------------------------------------------------
    # Step 3: Build the mosaic
    # ------------------------------------------------------------------
    glob_path = str(tile_dir).replace("\\", "/")

    eval_arg = f"files=sorted(glob('{glob_path}/t*.svg'))"

    vp_args_2 = [
        "eval", eval_arg,
        "grid", "-o", fmt(uw + gap_px), fmt(uh + gap_px), str(cols), str(rows),
            "read", "--no-fail", "%files[_i] if _i < len(files) else ''%",
    ]

    if rotate:
        vp_args_2 += ["rotate", "%_i*90%" if square_tiles else "%_i*180%"]

    vp_args_2 += [
            "rect", "0", "0", fmt(uw), fmt(uh),
        "end",
        # --- Final layout: paper mode or size mode ---
        *final_layout_cmd,
        "lmove", "all", "new",
        "splitall", "linemerge", "linesort",
        "write", str(out_file),
    ]
    run_vpype(vp_args_2)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    if args.keep_tiles:
        print(f"Tile directory kept: {tile_dir}")
    else:
        shutil.rmtree(tile_dir)

    print(f"{'Shuffled SVG' if shuffle else 'Mosaic SVG'} created: {out_file}")


if __name__ == "__main__":
    main()
