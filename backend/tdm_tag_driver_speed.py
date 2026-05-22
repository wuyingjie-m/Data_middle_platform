import argparse
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tdm_domain_trip import (
    clean_row,
    haversine_distance,
    parse_array_field,
)

INPUT_FILE = Path(__file__).resolve().parent / "valid_all.csv"
OUTPUT_FILE = Path(__file__).resolve().parent / "tdm_tag_driver_speed.csv"

MPS_TO_KMH = 3.6
TRIP_SPEEDING_THRESHOLD_KMH = 80.0
HIGH_RISK_RATE_THRESHOLD = 0.20


@dataclass
class DriverStats:
    total_trips: int = 0
    speeding_trips: int = 0
    speed_sum_kmh: float = 0.0
    speed_count: int = 0


def get_speed_level(speed_kmh: float) -> str:
    if speed_kmh < 30:
        return "low"
    if speed_kmh <= 50:
        return "normal"
    if speed_kmh <= 80:
        return "fast"
    return "very_fast"


def parse_trip_interval_speeds_kmh(row: dict[str, str]) -> list[float]:
    lon = parse_array_field(row.get("lon"), float)
    lat = parse_array_field(row.get("lat"), float)
    tms = parse_array_field(row.get("tms"), float)
    n = min(len(lon), len(lat), len(tms))
    if n < 2:
        return []

    speeds_kmh: list[float] = []
    for index in range(1, n):
        dt = tms[index] - tms[index - 1]
        if dt <= 0:
            continue

        distance = haversine_distance(lon[index - 1], lat[index - 1], lon[index], lat[index])
        if distance <= 0:
            continue

        speeds_kmh.append(distance / dt * MPS_TO_KMH)

    return speeds_kmh


def build_driver_tags(input_file: Path) -> dict[str, DriverStats]:
    driver_stats: dict[str, DriverStats] = {}

    with input_file.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        for raw_row in reader:
            row = clean_row(raw_row)
            devid = row.get("devid")
            if not devid:
                raise ValueError("输入文件中未找到 'devid' 列，请检查 CSV 表头。")

            stats = driver_stats.setdefault(devid, DriverStats())
            stats.total_trips += 1

            trip_speeds_kmh = parse_trip_interval_speeds_kmh(row)
            stats.speed_sum_kmh += sum(trip_speeds_kmh)
            stats.speed_count += len(trip_speeds_kmh)
            if trip_speeds_kmh and max(trip_speeds_kmh) > TRIP_SPEEDING_THRESHOLD_KMH:
                stats.speeding_trips += 1

    return driver_stats


def write_driver_tags(driver_stats: dict[str, DriverStats], output_file: Path, tag_dt: str) -> None:
    fieldnames = ["devid", "date", "avg_speed_kmh", "speed_level", "speeding_rate", "speeding_rule"]

    with output_file.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        for devid in sorted(driver_stats):
            stats = driver_stats[devid]
            speeding_rate = 0.0
            if stats.total_trips > 0:
                speeding_rate = stats.speeding_trips / stats.total_trips
            avg_speed_kmh = 0.0
            if stats.speed_count > 0:
                avg_speed_kmh = stats.speed_sum_kmh / stats.speed_count

            writer.writerow(
                {
                    "devid": devid,
                    "date": tag_dt,
                    "avg_speed_kmh": f"{avg_speed_kmh:.3f}",
                    "speed_level": get_speed_level(avg_speed_kmh),
                    "speeding_rate": f"{speeding_rate:.0%}",
                    "speeding_rule": "high_risk" if speeding_rate > HIGH_RISK_RATE_THRESHOLD else "normal",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成司机速度风险标签。")
    parser.add_argument("--input", type=Path, default=INPUT_FILE, help="输入 CSV 文件，默认 top_five.csv。")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="输出 CSV 文件，默认 driver_speed_tags.csv。")
    parser.add_argument("--tag-dt", default=date.today().isoformat(), help="标签日期，默认脚本运行当天。")
    args = parser.parse_args()

    driver_stats = build_driver_tags(args.input)
    write_driver_tags(driver_stats, args.output, args.tag_dt)
    print(f"已生成：{args.output}")


if __name__ == "__main__":
    main()
