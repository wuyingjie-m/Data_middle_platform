import argparse
import ast
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tdm_trip_speed import haversine_distance, parse_array_field

INPUT_FILE = Path(__file__).resolve().parent / "valid_all.csv"
OUTPUT_FILE = Path(__file__).resolve().parent / "tdm_tag_road_geom.csv"


@dataclass
class GeomCandidate:
    route_geom: str
    distance_m: float
    coord_count: int
    source_trip_id: str
    occurrence_count: int = 0


def parse_route_geom_list(value: str | None) -> list[str]:
    if not value:
        return []

    try:
        geoms = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return []

    if not isinstance(geoms, list):
        return []

    return [geom for geom in geoms if isinstance(geom, str)]


def parse_linestring(linestring: str) -> list[tuple[float, float]]:
    content = linestring.strip()
    if not content.startswith("LINESTRING (") or not content.endswith(")"):
        return []

    points: list[tuple[float, float]] = []
    for pair in content[len("LINESTRING ("):-1].split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            return []
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            return []

    return points


def compute_linestring_distance_m(points: list[tuple[float, float]]) -> float:
    distance = 0.0
    for index in range(1, len(points)):
        lon1, lat1 = points[index - 1]
        lon2, lat2 = points[index]
        distance += haversine_distance(lon1, lat1, lon2, lat2)
    return distance


def build_road_geom(input_file: Path) -> dict[int, GeomCandidate]:
    candidates: dict[int, dict[str, GeomCandidate]] = defaultdict(dict)

    with input_file.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)

        for row_index, row in enumerate(reader, start=1):
            route = parse_array_field(row.get("route"), int)
            route_geoms = parse_route_geom_list(row.get("route_geom"))
            trip_id = row.get("trip_id") or str(row_index)

            for road_id, route_geom in zip(route, route_geoms):
                points = parse_linestring(route_geom)
                if len(points) < 2:
                    continue

                road_candidates = candidates[road_id]
                candidate = road_candidates.get(route_geom)
                if candidate is None:
                    candidate = GeomCandidate(
                        route_geom=route_geom,
                        distance_m=compute_linestring_distance_m(points),
                        coord_count=len(points),
                        source_trip_id=trip_id,
                    )
                    road_candidates[route_geom] = candidate

                candidate.occurrence_count += 1

    result: dict[int, GeomCandidate] = {}
    for road_id, road_candidates in candidates.items():
        result[road_id] = max(
            road_candidates.values(),
            key=lambda item: (item.occurrence_count, item.coord_count, item.distance_m),
        )

    return result


def write_road_geom(road_geom: dict[int, GeomCandidate], output_file: Path) -> None:
    fieldnames = ["road_id", "route_geom", "distance_m", "coord_count", "source_trip_id"]
    with output_file.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        for road_id in sorted(road_geom):
            geom = road_geom[road_id]
            writer.writerow(
                {
                    "road_id": road_id,
                    "route_geom": geom.route_geom,
                    "distance_m": f"{geom.distance_m:.3f}",
                    "coord_count": geom.coord_count,
                    "source_trip_id": geom.source_trip_id,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 road_id 对应的路段几何和距离。")
    parser.add_argument("--input", type=Path, default=INPUT_FILE, help="输入 CSV，默认 valid_all.csv。")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="输出 CSV，默认 tdm_tag_road_geom.csv。")
    args = parser.parse_args()

    road_geom = build_road_geom(args.input)
    write_road_geom(road_geom, args.output)
    print(f"已生成：{args.output}")
    print(f"路段数量：{len(road_geom)}")


if __name__ == "__main__":
    main()
