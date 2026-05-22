import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from tdm_trip_speed import (
    clean_row,
    haversine_distance,
    parse_array_field,
)

INPUT_FILE = Path(__file__).resolve().parent / "valid_all.csv"
OUTPUT_FILE = Path(__file__).resolve().parent / "tdm_tag_road_speed.csv"

MPS_TO_KMH = 3.6


@dataclass
class RoadSpeedStats:
    speed_sum_kmh: float = 0.0
    total_orders: int = 0
    speeding_orders: int = 0


@dataclass
class TripRoadStats:
    speed_sum_kmh: float = 0.0
    speed_count: int = 0
    max_speed_kmh: float = 0.0


def build_road_speed_stats(input_file: Path, threshold_kmh: float) -> dict[int, RoadSpeedStats]:
    road_stats: dict[int, RoadSpeedStats] = {}

    with input_file.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)

        for raw_row in reader:
            row = clean_row(raw_row)
            lon = parse_array_field(row.get("lon"), float)
            lat = parse_array_field(row.get("lat"), float)
            tms = parse_array_field(row.get("tms"), float)
            roads = parse_array_field(row.get("roads"), int)

            n = min(len(lon), len(lat), len(tms), len(roads))
            if n < 2:
                continue

            trip_road_stats: dict[int, TripRoadStats] = {}
            for index in range(1, n):
                dt = tms[index] - tms[index - 1]
                if dt <= 0:
                    continue

                distance = haversine_distance(lon[index - 1], lat[index - 1], lon[index], lat[index])
                if distance <= 0:
                    continue

                road_id = roads[index]
                speed_kmh = distance / dt * MPS_TO_KMH
                stats = trip_road_stats.setdefault(road_id, TripRoadStats())
                stats.speed_sum_kmh += speed_kmh
                stats.speed_count += 1
                stats.max_speed_kmh = max(stats.max_speed_kmh, speed_kmh)

            for road_id, trip_stats in trip_road_stats.items():
                if trip_stats.speed_count == 0:
                    continue

                road_stats_item = road_stats.setdefault(road_id, RoadSpeedStats())
                road_stats_item.total_orders += 1
                road_stats_item.speed_sum_kmh += trip_stats.speed_sum_kmh / trip_stats.speed_count
                if trip_stats.max_speed_kmh > threshold_kmh:
                    road_stats_item.speeding_orders += 1

    return road_stats


def write_road_speed_stats(road_stats: dict[int, RoadSpeedStats], output_file: Path) -> None:
    fieldnames = ["road_id", "total_orders", "speeding_orders", "avg_speed_kmh", "speeding_rate"]

    with output_file.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        for road_id in sorted(road_stats):
            stats = road_stats[road_id]
            if stats.total_orders == 0:
                continue

            writer.writerow(
                {
                    "road_id": road_id,
                    "total_orders": stats.total_orders,
                    "speeding_orders": stats.speeding_orders,
                    "avg_speed_kmh": f"{stats.speed_sum_kmh / stats.total_orders:.3f}",
                    "speeding_rate": f"{stats.speeding_orders / stats.total_orders:.2%}",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="按路段 ID 统计平均速度和超速比率。")
    parser.add_argument("--input", type=Path, default=INPUT_FILE, help="输入 CSV 文件，默认 valid.csv。")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="输出 CSV 文件，默认 tdm_tag_road_speed.csv。")
    parser.add_argument("--threshold-kmh", type=float, default=80.0, help="超速阈值，默认 80 km/h。")
    args = parser.parse_args()

    road_stats = build_road_speed_stats(args.input, args.threshold_kmh)
    write_road_speed_stats(road_stats, args.output)
    print(f"已生成：{args.output}")


if __name__ == "__main__":
    main()
