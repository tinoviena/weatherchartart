"""
Tests for weather_art.py — exercises the rendering and colormap logic
using synthetic data so no network access is required.
"""

import os
import sys
import tempfile

import numpy as np
import pytest
import yaml

# Make sure the project root is on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weather_art  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_cfg(tmp_path, colormap="temperature_europe", variable="temperature_2m"):
    """Return a minimal configuration dict wired to *tmp_path*."""
    cfg = {
        "region": {
            "lat_min": 40, "lat_max": 50,
            "lon_min": 0,  "lon_max": 10,
            "grid_resolution": 5.0,
        },
        "data": {"variable": variable, "date": "2023-07-15", "hour": 12},
        "output": {
            "filename": str(tmp_path / "test_out.png"),
            "width": 200, "height": 100, "dpi": 72,
            "smooth_sigma": 0,
            "colormap": colormap,
            "colorbar": False,
        },
        "colormaps": {
            "temperature_europe": [
                {"value": -10, "color": "#0000ff"},
                {"value":  20, "color": "#ffffff"},
                {"value":  40, "color": "#ff0000"},
            ]
        },
    }
    return cfg


def _small_grid():
    """Return a tiny 3×3 synthetic data grid."""
    lats = np.array([40.0, 45.0, 50.0])
    lons = np.array([0.0, 5.0, 10.0])
    values = np.array([
        [5.0, 10.0, 15.0],
        [0.0,  8.0, 20.0],
        [-5.0, 2.0, 12.0],
    ])
    return lats, lons, values


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_roundtrip(self, tmp_path):
        cfg = {"region": {"lat_min": 35}, "data": {"variable": "temperature_2m"}}
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(cfg))
        loaded = weather_art.load_config(str(path))
        assert loaded["region"]["lat_min"] == 35
        assert loaded["data"]["variable"] == "temperature_2m"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            weather_art.load_config(str(tmp_path / "no_such.yaml"))


# ---------------------------------------------------------------------------
# build_colormap
# ---------------------------------------------------------------------------

class TestBuildColormap:
    def test_custom_colormap_returns_cmap_and_range(self):
        stops = [
            {"value": -10, "color": "#0000ff"},
            {"value":  10, "color": "#ff0000"},
        ]
        cmap, vmin, vmax = weather_art.build_colormap("my_cmap", {"my_cmap": stops})
        assert vmin == -10.0
        assert vmax == 10.0
        # Coloring at the extremes
        color_min = cmap(0.0)
        color_max = cmap(1.0)
        # Blue channel should be high at vmin, red channel high at vmax
        assert color_min[2] > 0.8, "Left stop should be blue-ish"
        assert color_max[0] > 0.8, "Right stop should be red-ish"

    def test_matplotlib_builtin_fallback(self):
        cmap, vmin, vmax = weather_art.build_colormap("viridis", {})
        assert vmin is None
        assert vmax is None
        assert callable(cmap)

    def test_unknown_name_falls_back_to_viridis(self, capsys):
        cmap, vmin, vmax = weather_art.build_colormap("nonexistent_xyz", {})
        assert callable(cmap)
        captured = capsys.readouterr()
        assert "viridis" in captured.err

    def test_stops_sorted_automatically(self):
        stops = [
            {"value": 30, "color": "#ff0000"},
            {"value":  0, "color": "#ffffff"},
            {"value": -10, "color": "#0000ff"},
        ]
        cmap, vmin, vmax = weather_art.build_colormap("c", {"c": stops})
        assert vmin == -10.0
        assert vmax == 30.0


# ---------------------------------------------------------------------------
# _fill_nans
# ---------------------------------------------------------------------------

class TestFillNans:
    def test_no_nans_unchanged(self):
        lats = np.array([0.0, 1.0])
        lons = np.array([0.0, 1.0])
        vals = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = weather_art._fill_nans(lats, lons, vals)
        np.testing.assert_array_equal(result, vals)

    def test_single_nan_filled(self):
        lats = np.array([0.0, 1.0, 2.0])
        lons = np.array([0.0, 1.0, 2.0])
        vals = np.full((3, 3), 5.0)
        vals[1, 1] = np.nan
        result = weather_art._fill_nans(lats, lons, vals)
        assert not np.any(np.isnan(result))
        # Nearest neighbour should give ~5
        assert abs(result[1, 1] - 5.0) < 1e-9

    def test_all_valid_returns_copy(self):
        lats = np.array([0.0, 1.0])
        lons = np.array([0.0, 1.0])
        vals = np.ones((2, 2))
        result = weather_art._fill_nans(lats, lons, vals)
        np.testing.assert_array_equal(result, vals)


# ---------------------------------------------------------------------------
# render_image (end-to-end — no network)
# ---------------------------------------------------------------------------

class TestRenderImage:
    def test_creates_png_file(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        assert os.path.isfile(out)
        assert out.endswith(".png")

    def test_output_file_is_valid_image(self, tmp_path):
        from PIL import Image as PILImage
        cfg = _minimal_cfg(tmp_path)
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        img = PILImage.open(out)
        assert img.width > 0
        assert img.height > 0

    def test_vmin_vmax_override_accepted(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["vmin"] = 0
        cfg["output"]["vmax"] = 30
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        assert os.path.isfile(out)

    def test_smooth_sigma_zero_accepted(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["smooth_sigma"] = 0
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        assert os.path.isfile(out)

    def test_smooth_sigma_positive_accepted(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["smooth_sigma"] = 2.0
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        assert os.path.isfile(out)

    def test_matplotlib_builtin_colormap(self, tmp_path):
        cfg = _minimal_cfg(tmp_path, colormap="viridis")
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        assert os.path.isfile(out)

    def test_all_nans_exits(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        lats, lons, _ = _small_grid()
        values = np.full((3, 3), np.nan)
        with pytest.raises(SystemExit):
            weather_art.render_image(lats, lons, values, cfg)

    def test_image_has_dpi_metadata(self, tmp_path):
        from PIL import Image as PILImage
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["dpi"] = 150
        lats, lons, values = _small_grid()
        out = weather_art.render_image(lats, lons, values, cfg)
        img = PILImage.open(out)
        dpi = img.info.get("dpi")
        assert dpi is not None
        assert abs(dpi[0] - 150) < 1  # PNG DPI is stored with slight float rounding
        assert abs(dpi[1] - 150) < 1


# ---------------------------------------------------------------------------
# save_colorbar
# ---------------------------------------------------------------------------

class TestSaveColorbar:
    def test_colorbar_disabled_returns_none(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["colorbar"] = False
        result = weather_art.save_colorbar(cfg)
        assert result is None

    def test_colorbar_enabled_creates_file(self, tmp_path):
        cfg = _minimal_cfg(tmp_path)
        cfg["output"]["colorbar"] = True
        out = str(tmp_path / "test_out.png")
        result = weather_art.save_colorbar(cfg, out)
        assert result is not None
        assert os.path.isfile(result)
        assert "_colorbar.png" in result


# ---------------------------------------------------------------------------
# apply_cli_overrides
# ---------------------------------------------------------------------------

class TestApplyCliOverrides:
    def _args(self, **kwargs):
        import argparse
        defaults = {
            "variable": None, "date": None, "hour": None,
            "output": None, "colormap": None, "dpi": None,
            "width": None, "height": None, "smooth": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_no_overrides_leaves_config_unchanged(self):
        cfg = {"data": {"variable": "temperature_2m"}}
        result = weather_art.apply_cli_overrides(cfg, self._args())
        assert result["data"]["variable"] == "temperature_2m"

    def test_variable_override(self):
        cfg = {"data": {"variable": "temperature_2m"}}
        result = weather_art.apply_cli_overrides(cfg, self._args(variable="wind_speed_10m"))
        assert result["data"]["variable"] == "wind_speed_10m"

    def test_date_override(self):
        cfg = {"data": {"date": "2023-01-01"}}
        result = weather_art.apply_cli_overrides(cfg, self._args(date="2024-06-01"))
        assert result["data"]["date"] == "2024-06-01"

    def test_colormap_override(self):
        cfg = {"output": {"colormap": "viridis"}}
        result = weather_art.apply_cli_overrides(cfg, self._args(colormap="plasma"))
        assert result["output"]["colormap"] == "plasma"
