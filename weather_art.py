#!/usr/bin/env python3
"""
WeatherChartArt — Generate high-resolution, poster-quality weather art images.

Fetches historical weather data from the free Open-Meteo API for a geographic
grid, interpolates it to a high-resolution raster, and applies configurable
colour schemes defined in a YAML config file.

Usage:
    python weather_art.py [config.yaml] [options]

See README.md and config.yaml for full documentation.
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import requests
import yaml
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from scipy.interpolate import NearestNDInterpolator, RegularGridInterpolator
from scipy.ndimage import gaussian_filter

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load and return the YAML configuration file."""
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg


def apply_cli_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    """Merge command-line overrides into the config dict."""
    if args.variable:
        cfg.setdefault("data", {})["variable"] = args.variable
    if args.date:
        cfg.setdefault("data", {})["date"] = args.date
    if args.hour is not None:
        cfg.setdefault("data", {})["hour"] = args.hour
    if args.output:
        cfg.setdefault("output", {})["filename"] = args.output
    if args.colormap:
        cfg.setdefault("output", {})["colormap"] = args.colormap
    if args.dpi:
        cfg.setdefault("output", {})["dpi"] = args.dpi
    if args.width:
        cfg.setdefault("output", {})["width"] = args.width
    if args.height:
        cfg.setdefault("output", {})["height"] = args.height
    if args.smooth is not None:
        cfg.setdefault("output", {})["smooth_sigma"] = args.smooth
    return cfg


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _fetch_one(lat: float, lon: float, variable: str, date: str, hour: int, timeout: int = 30):
    """Fetch a single data-point value from the Open-Meteo archive API.

    Returns the float value, or None if the request fails or data is missing.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": date,
        "end_date": date,
        "hourly": variable,
        "timezone": "UTC",
    }
    try:
        resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        values = payload.get("hourly", {}).get(variable, [])
        if values and hour < len(values) and values[hour] is not None:
            return float(values[hour])
    except Exception as exc:  # noqa: BLE001
        print(f"  Warning: ({lat:.2f}, {lon:.2f}) — {exc}", file=sys.stderr)
    return None


def fetch_weather_grid(cfg: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fetch weather data for a regular lat/lon grid.

    Returns (lats, lons, values) where values is a 2-D array shaped
    (len(lats), len(lons)) and may contain NaN for missing points.
    """
    region = cfg["region"]
    data_cfg = cfg["data"]

    lat_min = float(region["lat_min"])
    lat_max = float(region["lat_max"])
    lon_min = float(region["lon_min"])
    lon_max = float(region["lon_max"])
    resolution = float(region.get("grid_resolution", 1.0))

    variable: str = data_cfg["variable"]
    date: str = str(data_cfg["date"])
    hour: int = int(data_cfg.get("hour", 12))
    max_workers: int = int(cfg.get("fetch", {}).get("max_workers", 20))
    timeout: int = int(cfg.get("fetch", {}).get("timeout", 30))

    lats = np.arange(lat_min, lat_max + resolution * 0.5, resolution)
    lons = np.arange(lon_min, lon_max + resolution * 0.5, resolution)

    total = len(lats) * len(lons)
    print(f"Fetching {total} data points ({len(lats)} lats × {len(lons)} lons) "
          f"for '{variable}' on {date} hour={hour} UTC …")

    values = np.full((len(lats), len(lons)), np.nan)

    tasks = [(i, j, lat, lon)
             for i, lat in enumerate(lats)
             for j, lon in enumerate(lons)]

    completed = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as pool:
        future_map = {
            pool.submit(_fetch_one, lat, lon, variable, date, hour, timeout): (i, j)
            for i, j, lat, lon in tasks
        }
        for future in as_completed(future_map):
            i, j = future_map[future]
            try:
                val = future.result()
                if val is not None:
                    values[i, j] = val
            except Exception:  # noqa: BLE001
                pass
            completed += 1
            if completed % max(1, total // 20) == 0 or completed == total:
                pct = 100 * completed / total
                print(f"  {completed}/{total} ({pct:.0f}%) …", end="\r", flush=True)

    valid_count = int(np.sum(~np.isnan(values)))
    print(f"\nFetch complete — {valid_count}/{total} valid points.")
    return lats, lons, values


# ---------------------------------------------------------------------------
# Colour mapping
# ---------------------------------------------------------------------------

def build_colormap(name: str, colormaps_cfg: dict) -> tuple:
    """Return (cmap, vmin, vmax) for the requested colormap name.

    If *name* is found in *colormaps_cfg* it is built from the colour stops
    defined there.  Otherwise matplotlib's built-in colormaps are tried.
    vmin/vmax are None when the colormap has no value domain (built-ins).
    """
    if name in colormaps_cfg:
        stops = sorted(colormaps_cfg[name], key=lambda s: s["value"])
        stop_values = [s["value"] for s in stops]
        stop_colors = [s["color"] for s in stops]
        vmin, vmax = stop_values[0], stop_values[-1]
        span = vmax - vmin or 1.0
        norm_positions = [(v - vmin) / span for v in stop_values]
        cmap = LinearSegmentedColormap.from_list(
            name, list(zip(norm_positions, stop_colors))
        )
        return cmap, float(vmin), float(vmax)

    # Fall back to a matplotlib built-in
    try:
        cmap = plt.get_cmap(name)
        return cmap, None, None
    except ValueError:
        print(f"Warning: colormap '{name}' not found — falling back to 'viridis'.",
              file=sys.stderr)
        return plt.get_cmap("viridis"), None, None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fill_nans(lats: np.ndarray, lons: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Replace NaN cells with nearest-neighbour values."""
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    mask = np.isnan(values)
    if not np.any(mask):
        return values
    valid_pts = np.column_stack([lat_grid[~mask], lon_grid[~mask]])
    nn = NearestNDInterpolator(valid_pts, values[~mask])
    filled = values.copy()
    filled[mask] = nn(lat_grid[mask], lon_grid[mask])
    return filled


def render_image(
    lats: np.ndarray,
    lons: np.ndarray,
    values: np.ndarray,
    cfg: dict,
) -> str:
    """Interpolate data to a high-res grid, apply colour map, and save a PNG.

    Returns the path of the saved image.
    """
    out_cfg = cfg.get("output", {})
    colormaps_cfg = cfg.get("colormaps", {})

    colormap_name: str = out_cfg.get("colormap", "viridis")
    dpi: int = int(out_cfg.get("dpi", 300))
    filename: str = out_cfg.get("filename", "weather_art.png")
    img_w: int = int(out_cfg.get("width", 3840))
    img_h: int = int(out_cfg.get("height", 2160))
    smooth_sigma: float = float(out_cfg.get("smooth_sigma", 2.0))
    # Optional explicit data range override
    vmin_override = out_cfg.get("vmin", None)
    vmax_override = out_cfg.get("vmax", None)

    # --- Validate data ---
    if not np.any(~np.isnan(values)):
        print("Error: no valid data points to render.", file=sys.stderr)
        sys.exit(1)

    # --- Fill missing cells ---
    filled = _fill_nans(lats, lons, values)

    # --- Build colour map ---
    cmap, cmap_vmin, cmap_vmax = build_colormap(colormap_name, colormaps_cfg)

    vmin = vmin_override if vmin_override is not None else (cmap_vmin if cmap_vmin is not None else float(np.nanmin(values)))
    vmax = vmax_override if vmax_override is not None else (cmap_vmax if cmap_vmax is not None else float(np.nanmax(values)))

    # --- Interpolate to output resolution ---
    # Account for longitude shrinkage at latitude (simple cylindrical equidistant)
    mean_lat_rad = np.deg2rad(np.mean(lats))
    lon_scale = np.cos(mean_lat_rad)          # longitude degree is shorter by this factor
    lat_span = lats[-1] - lats[0]
    lon_span = (lons[-1] - lons[0]) * lon_scale

    # Derive pixel counts that honour the geographic aspect ratio
    aspect = lon_span / lat_span if lat_span > 0 else 1.0
    if img_w / img_h > aspect:
        # height-limited — shrink width
        px_h = img_h
        px_w = max(1, round(img_h * aspect))
    else:
        # width-limited — shrink height
        px_w = img_w
        px_h = max(1, round(img_w / aspect))

    interp = RegularGridInterpolator(
        (lats, lons), filled, method="linear", bounds_error=False, fill_value=None
    )
    hi_lats = np.linspace(lats[0], lats[-1], px_h)
    hi_lons = np.linspace(lons[0], lons[-1], px_w)
    hi_lat_g, hi_lon_g = np.meshgrid(hi_lats, hi_lons, indexing="ij")

    print(f"Interpolating to {px_w}×{px_h} pixels …")
    hi_vals = interp((hi_lat_g, hi_lon_g))

    # --- Optional smoothing ---
    if smooth_sigma > 0:
        # Scale sigma to pixel units (relative to grid resolution)
        lat_px_per_deg = px_h / lat_span if lat_span > 0 else 1
        sigma_px = smooth_sigma * lat_px_per_deg
        print(f"Applying Gaussian smoothing (sigma={smooth_sigma:.1f}°, {sigma_px:.1f} px) …")
        hi_vals = gaussian_filter(hi_vals, sigma=sigma_px)

    # --- Apply colour map ---
    hi_vals = np.clip(hi_vals, vmin, vmax)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    rgba = cmap(norm(hi_vals))

    # --- Save image ---
    rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
    img = Image.fromarray(rgb)
    img.save(filename, dpi=(dpi, dpi))
    print(f"Saved: {filename}  ({px_w}×{px_h} px, {dpi} DPI)")
    return filename


# ---------------------------------------------------------------------------
# Colour bar / legend (optional)
# ---------------------------------------------------------------------------

def save_colorbar(cfg: dict, output_path: str | None = None) -> str | None:
    """Save a standalone colour bar PNG alongside the main image.

    Only produced when ``output.colorbar`` is true in the config.
    """
    out_cfg = cfg.get("output", {})
    if not out_cfg.get("colorbar", False):
        return None

    colormaps_cfg = cfg.get("colormaps", {})
    colormap_name: str = out_cfg.get("colormap", "viridis")
    variable: str = cfg.get("data", {}).get("variable", "")

    cmap, cmap_vmin, cmap_vmax = build_colormap(colormap_name, colormaps_cfg)
    vmin = out_cfg.get("vmin", cmap_vmin) or 0.0
    vmax = out_cfg.get("vmax", cmap_vmax) or 1.0

    fig, ax = plt.subplots(figsize=(6, 0.5))
    fig.subplots_adjust(bottom=0.5)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    cb = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=cmap),
        cax=ax,
        orientation="horizontal",
    )
    cb.set_label(variable)

    bar_path = output_path or out_cfg.get("filename", "weather_art.png")
    bar_path = os.path.splitext(bar_path)[0] + "_colorbar.png"
    fig.savefig(bar_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"Colour bar saved: {bar_path}")
    return bar_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate high-resolution weather art images from Open-Meteo data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python weather_art.py
  python weather_art.py config.yaml --date 2023-07-15 --variable temperature_2m
  python weather_art.py config.yaml --colormap temperature_neon --output summer.png
  python weather_art.py config.yaml --width 7680 --height 4320 --dpi 300
""",
    )
    p.add_argument("config", nargs="?", default="config.yaml",
                   help="Path to YAML configuration file (default: config.yaml)")
    p.add_argument("--variable", metavar="VAR",
                   help="Weather variable (e.g. temperature_2m, wind_speed_10m)")
    p.add_argument("--date", metavar="YYYY-MM-DD",
                   help="Date for historical data")
    p.add_argument("--hour", type=int, metavar="H",
                   help="Hour of day in UTC (0–23)")
    p.add_argument("--output", "-o", metavar="FILE",
                   help="Output image filename")
    p.add_argument("--colormap", "-c", metavar="NAME",
                   help="Colormap name (config key or matplotlib name)")
    p.add_argument("--dpi", type=int, metavar="N",
                   help="Output DPI (e.g. 300 for print quality)")
    p.add_argument("--width", type=int, metavar="PX",
                   help="Maximum output width in pixels")
    p.add_argument("--height", type=int, metavar="PX",
                   help="Maximum output height in pixels")
    p.add_argument("--smooth", type=float, metavar="SIGMA",
                   help="Gaussian smoothing sigma in degrees (0 = off)")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not os.path.isfile(args.config):
        parser.error(f"Config file not found: {args.config}\n"
                     "Copy config.yaml from the repo or specify a path.")

    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    lats, lons, values = fetch_weather_grid(cfg)
    out_file = render_image(lats, lons, values, cfg)
    save_colorbar(cfg, out_file)


if __name__ == "__main__":
    main()
