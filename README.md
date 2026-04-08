# WeatherChartArt

Generate **high-resolution, poster-quality weather art images** from free
historical weather data — without menus, watermarks, or UI clutter.

Inspired by sites like [Ventusky](https://www.ventusky.com/) and
[Zoom Earth](https://zoom.earth/), but producing clean images you can
download and print at any size.

---

## Features

- **Free data** — uses the [Open-Meteo](https://open-meteo.com/) historical
  archive API.  No API key, no registration required.
- **Any weather variable** — temperature, wind speed, pressure, precipitation,
  cloud cover, solar radiation, humidity, and more.
- **Fully configurable colours** — define your own colour gradients in
  `config.yaml` using simple value/colour stops.  No Python editing needed.
- **High resolution** — renders at any pixel size (4K, 8K, A0 poster, …).
- **Smooth interpolation** — bilinear + optional Gaussian smoothing turns a
  coarse data grid into a silky image.
- **Optional colour bar** — save a matching legend alongside the image.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run with the default config (Europe, temperature, summer day)
python weather_art.py

# 3. Open weather_art.png
```

The default config fetches a 2° grid over Europe for 15 July 2023 at noon UTC
and renders a 3840 × 2160 px image.  The fetch takes roughly 30–60 seconds
depending on your connection.

---

## Usage

```
python weather_art.py [config.yaml] [options]
```

All settings live in `config.yaml`, but every important one can be overridden
on the command line:

| Option | Description |
|---|---|
| `--variable VAR` | Weather variable (e.g. `temperature_2m`, `wind_speed_10m`) |
| `--date YYYY-MM-DD` | Historical date |
| `--hour H` | UTC hour of day (0–23) |
| `--colormap Name` | Colour map name (config key or matplotlib name) |
| `--output FILE` | Output filename |
| `--width PX` | Maximum image width in pixels |
| `--height PX` | Maximum image height in pixels |
| `--dpi N` | DPI embedded in the PNG (default: 300) |
| `--smooth SIGMA` | Gaussian smoothing in degrees (0 = off) |

### Examples

```bash
# Temperature over Europe with the neon colour scheme
python weather_art.py config.yaml --colormap temperature_neon

# Wind speed, different region, 8 K resolution
python weather_art.py config.yaml \
    --variable wind_speed_10m \
    --colormap wind_aurora \
    --width 7680 --height 4320 \
    --output wind_8k.png

# Surface pressure with a fast preview grid
python weather_art.py config.yaml \
    --variable surface_pressure \
    --colormap pressure_classic \
    --width 1920 --height 1080

# US east coast, precipitation, hurricane season
python weather_art.py my_us_config.yaml \
    --date 2023-08-30 \
    --variable precipitation \
    --colormap precipitation_radar \
    --output hurricane.png
```

---

## Configuration reference (`config.yaml`)

### `region`

| Key | Description |
|---|---|
| `lat_min` / `lat_max` | Latitude bounds in degrees (negative = South) |
| `lon_min` / `lon_max` | Longitude bounds in degrees (negative = West) |
| `grid_resolution` | Sampling step in degrees.  `1.0` is a good default; use `0.5` for detail or `2.0` for a quick preview. |

### `data`

| Key | Description |
|---|---|
| `date` | ISO date string, e.g. `"2023-07-15"`.  Must be at least 5 days in the past. |
| `hour` | UTC hour (0–23).  `12` = noon UTC. |
| `variable` | Open-Meteo variable name — see table below. |

**Supported variables** (see the [full list](https://open-meteo.com/en/docs/historical-weather-api)):

| Variable | Units | Suggested colormap |
|---|---|---|
| `temperature_2m` | °C | `temperature_europe`, `temperature_neon` |
| `apparent_temperature` | °C | `temperature_pastel` |
| `wind_speed_10m` | km/h | `wind_calm_to_storm`, `wind_aurora` |
| `wind_gusts_10m` | km/h | `wind_fire` |
| `surface_pressure` | hPa | `pressure_classic`, `pressure_ocean` |
| `precipitation` | mm | `precipitation_blues`, `precipitation_radar` |
| `cloud_cover` | % | `cloud_sky` |
| `shortwave_radiation` | W/m² | `solar_heat` |
| `relative_humidity_2m` | % | `humidity_desert_to_tropics` |

### `output`

| Key | Description |
|---|---|
| `filename` | Output PNG path |
| `width` / `height` | Upper bound on image size in pixels.  Actual size respects geographic aspect ratio. |
| `dpi` | Print resolution metadata (300 for poster printing) |
| `smooth_sigma` | Gaussian blur radius in degrees.  Larger = softer/painterly. `0` = off. |
| `colormap` | Key from `colormaps` section, or any matplotlib colormap name |
| `colorbar` | `true` to save a matching colour bar PNG |
| `vmin` / `vmax` | Hard-code the value range (overrides colormap stops and data range) |

### `colormaps`

Each custom colormap is a list of `{value, color}` stops.

```yaml
colormaps:
  my_palette:
    - { value: -10, color: "#0000ff" }   # cold = blue
    - { value:   0, color: "#ffffff" }   # zero = white
    - { value:  10, color: "#ff0000" }   # hot  = red
```

- **`value`** is in the same units as the weather variable (°C, km/h, hPa, …).
- **`color`** can be a hex string (`#rrggbb`) or any matplotlib colour name
  (`"navy"`, `"gold"`, `"white"`, …).
- Stops are automatically sorted and normalised — you can add as many as you like.
- Closer stops create sharper transitions; wider gaps create smooth gradients.

You can also use **any matplotlib built-in colormap** by name in `colormap:`:
`viridis`, `plasma`, `inferno`, `magma`, `RdBu_r`, `coolwarm`, `turbo`,
`YlOrRd`, `BuPu`, etc.

---

## Printing tips

| Print size | Recommended resolution | DPI |
|---|---|---|
| A4 / letter | 2480 × 3508 | 300 |
| A3 | 3508 × 4961 | 300 |
| A2 | 4961 × 7016 | 300 |
| A1 | 7016 × 9933 | 300 |
| A0 poster | 9933 × 14043 | 300 |
| 24″ × 36″ poster | 7200 × 10800 | 300 |

Set `width` and `height` in `config.yaml` accordingly, then send the output
PNG directly to a print lab.

---

## How it works

1. **Grid sampling** — The geographic region is divided into a regular
   lat/lon grid at the configured resolution.
2. **Parallel fetching** — Each grid point is fetched concurrently from the
   Open-Meteo historical archive API using a thread pool.
3. **Gap filling** — Any missing values (rare API failures) are filled with
   nearest-neighbour interpolation.
4. **Bilinear interpolation** — The sparse data grid is upsampled to the
   full output pixel resolution using `scipy.interpolate.RegularGridInterpolator`.
5. **Gaussian smoothing** — An optional blur pass removes interpolation
   artefacts and creates painterly, smooth colour transitions.
6. **Colourmap application** — Each pixel value is mapped to an RGB colour
   through the chosen colormap.
7. **PNG export** — The image is saved with DPI metadata for print use.

---

## Dependencies

| Package | Purpose |
|---|---|
| `numpy` | Array operations |
| `scipy` | Interpolation and smoothing |
| `matplotlib` | Colourmap engine |
| `requests` | HTTP fetching |
| `PyYAML` | Config file parsing |
| `Pillow` | PNG export with DPI metadata |

Install with:

```bash
pip install -r requirements.txt
```

---

## License

MIT
