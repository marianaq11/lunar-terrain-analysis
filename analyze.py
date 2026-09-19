"""Sample a lunar elevation grid and make a repeatable summary."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = "https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/"


def get_data(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("LDEM_4.LBL", "LDEM_4.IMG"):
        path = folder / name
        if not path.exists():
            print(f"Downloading {name}...")
            # Rename only after the download finishes, so a failed request is retryable.
            temporary = path.with_suffix(".part")
            with urllib.request.urlopen(SOURCE + name, timeout=60) as response:
                temporary.write_bytes(response.read())
            temporary.replace(path)


def label_value(label, key):
    match = re.search(r"^\s*" + re.escape(key) + r"\s*=\s*([^\r\n]+)", label, re.M)
    if not match:
        raise ValueError(f"Missing label field: {key}")
    return match.group(1).strip().strip('"')


def read_grid(folder):
    label = (folder / "LDEM_4.LBL").read_text()
    if label_value(label, "PRODUCT_ID") != "LDEM_4":
        raise ValueError("This reader supports the LDEM_4 product only.")
    if label_value(label, "SAMPLE_TYPE") != "LSB_INTEGER" or int(label_value(label, "SAMPLE_BITS")) != 16:
        raise ValueError("Expected little-endian 16-bit signed integers.")
    rows = int(label_value(label, "LINES"))
    cols = int(label_value(label, "LINE_SAMPLES"))
    if (rows, cols) != (720, 1440):
        raise ValueError("Unexpected LDEM_4 grid dimensions.")
    image = folder / "LDEM_4.IMG"
    if image.stat().st_size != rows * cols * 2:
        raise ValueError("Image size does not match the label; download it again.")
    raw = np.fromfile(image, dtype="<i2").reshape(rows, cols)
    if raw.min() < float(label_value(label, "MINIMUM")) or raw.max() > float(label_value(label, "MAXIMUM")):
        raise ValueError("Image values fall outside the label's valid range.")
    # The offset is the reference radius. Adding it would give radius, not elevation.
    return raw.astype(float) * float(label_value(label, "SCALING_FACTOR"))


def sample_grid(grid, step):
    if not 1 <= step <= min(grid.shape):
        raise ValueError("Step must be between 1 and the smaller grid dimension.")
    rows = np.arange(step // 2, grid.shape[0], step)
    cols = np.arange(step // 2, grid.shape[1], step)
    # Coordinates refer to pixel centers; the first row is at the north pole end.
    latitudes = 90 - (rows + 0.5) * 180 / grid.shape[0]
    longitudes = (cols + 0.5) * 360 / grid.shape[1]
    lon, lat = np.meshgrid(longitudes, latitudes)
    frame = pd.DataFrame({"latitude_deg": lat.ravel(), "longitude_deg_east": lon.ravel(),
                          "elevation_m": grid[np.ix_(rows, cols)].ravel()})
    frame["hemisphere"] = np.where(frame.latitude_deg >= 0, "North", "South")
    return frame


def summarize(frame):
    elevation = frame.elevation_m
    # Equal-angle cells get smaller toward the poles. Cosine weights account for that.
    weights = np.cos(np.deg2rad(frame.latitude_deg))
    return {"sampled_cells": len(frame), "minimum_elevation_m": float(elevation.min()),
            "maximum_elevation_m": float(elevation.max()),
            "median_cell_elevation_m": float(elevation.median()),
            "mean_cell_elevation_m": float(elevation.mean()),
            "area_weighted_mean_elevation_m": float(np.average(elevation, weights=weights)),
            "cell_standard_deviation_m": float(elevation.std()),
            "reference_radius_m": 1737400}


def make_plots(frame, output):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    grid = frame.pivot(index="latitude_deg", columns="longitude_deg_east", values="elevation_m")
    plot = ax.pcolormesh(grid.columns, grid.index, grid.values / 1000, cmap="terrain", shading="nearest")
    ax.set(xlabel="Longitude (degrees east)", ylabel="Latitude (degrees)",
           title=f"Lunar elevation | {len(frame):,} sampled LOLA grid cells", xlim=(0, 360), ylim=(-90, 90))
    fig.colorbar(plot, ax=ax, label="Elevation above reference sphere (km)")
    fig.savefig(output / "elevation_map.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    axes[0].hist(frame.elevation_m / 1000, bins=45, color="#3c6485", edgecolor="white", linewidth=0.4)
    axes[0].set(title="Elevation distribution", xlabel="Elevation (km)", ylabel="Sampled cell count")
    for hemisphere, group in frame.groupby("hemisphere"):
        axes[1].hist(group.elevation_m / 1000, bins=np.linspace(-10, 12, 45),
                     histtype="step", linewidth=1.8, label=hemisphere)
    axes[1].set(title="Northern and southern hemispheres", xlabel="Elevation (km)", ylabel="Sampled cell count")
    axes[1].legend()
    fig.savefig(output / "elevation_distribution.png", dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", type=int, default=8, help="Sample every Nth row and column (default: 8).")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    if not 1 <= args.step <= 360:
        parser.error("--step must be between 1 and 360")
    try:
        get_data(args.data_dir)
        grid = read_grid(args.data_dir)
        frame = sample_grid(grid, args.step)
        summary = summarize(frame)
        args.output.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.output / "sampled_elevation.csv", index=False)
        frame.groupby("hemisphere").elevation_m.agg(["count", "mean", "median", "min", "max"]).to_csv(args.output / "hemisphere_summary.csv")
        summary["sampling_step"] = args.step
        summary["source_grid_cells"] = int(grid.size)
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        provenance = {name: {"url": SOURCE + name, "sha256": hashlib.sha256((args.data_dir / name).read_bytes()).hexdigest()}
                      for name in ("LDEM_4.LBL", "LDEM_4.IMG")}
        (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        make_plots(frame, args.output)
        report = ["# Analysis results", "", f"Analyzed {len(frame):,} cells from the LDEM_4 lunar elevation grid.", "",
                  "| Measurement | Value |", "| --- | ---: |"]
        report += [f"| {key.replace('_', ' ')} | {value:,.2f} |" for key, value in summary.items()]
        report += ["", "These are sampled grid cells, not raw laser shots. Elevations are relative to a 1,737.4 km reference sphere.",
                   "The histogram and hemisphere summaries describe cell counts, not surface-area fractions.",
                   "The area-weighted mean uses cosine latitude weights; this coarse sample is an approximation.",
                   "Sample extrema are not necessarily the highest and lowest points on the Moon."]
        (args.output / "report.md").write_text("\n".join(report) + "\n")
        print(f"Analyzed {len(frame):,} cells. Results: {args.output.resolve()}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Analysis failed: {exc}\n")


if __name__ == "__main__":
    main()
