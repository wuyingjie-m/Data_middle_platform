import argparse
import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

INPUT_FILE = Path(__file__).resolve().parent / "valid_all.csv"
OUTPUT_FILE = Path(__file__).resolve().parent / "tdm_trip_speed.csv"
# 地球半径，单位米
EARTH_RADIUS_M = 6371000.0

# 定义一个函数来清理 CSV 行中的字段名，去除可能的 BOM 和空白字符
def clean_row(row: Dict[str, str]) -> Dict[str, str]:
    # 去除字段名中的 BOM 和空白字符
    return {key.strip().lstrip("\ufeff"): value for key, value in row.items()}

# 定义一个函数来解析数组字段，支持去除引号、方括号和换行符，并将字符串转换为指定类型的列表
def parse_array_field(field, dtype=float):
    """
    解析:
    "[1.0, 2.0, 3.0]"
    -> [1,2,3] 或 [1.0,2.0,3.0]
    """

    if field is None:
        return []

    field = str(field).strip()

    if field == "" or field == "[]":
        return []

    # valid.csv 里的数组既可能是逗号分隔，也可能是 numpy 风格的空格分隔。
    items = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", field)

    result = []

    for token in items:

        if token == "":
            continue

        try:
            if dtype == int:
                # 兼容 "123.0"
                result.append(int(float(token)))
            else:
                result.append(dtype(token))

        except Exception as e:
            print("parse error")
            print("token =", token)
            print("dtype =", dtype)
            raise e

    return result

# 定义一个函数来格式化开始日期，输入是时间戳列表，输出是 ISO 格式的日期字符串
def format_start_date(tms: List[float]) -> str:
    if not tms:
        return ""
    return datetime.fromtimestamp(tms[0], timezone.utc).date().isoformat()

# 定义一个函数来格式化开始时间，输入是时间戳列表，输出是 HH:MM 格式的时间字符串
def format_start_time(tms: List[float]) -> str:
    if not tms:
        return ""
    return datetime.fromtimestamp(tms[0], timezone.utc).strftime("%H:%M")


# 定义一个函数来计算两点之间的 Haversine 距离，单位米
def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    # 将经纬度转换为弧度
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    # 计算 Haversine 距离
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    # 计算距离
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c

# 定义一个函数来计算一趟行程的最高速度，输入是经度、纬度和时间戳列表，输出是最高速度，单位米/秒
def compute_trip_max_speed_by_gps(lon: List[float], lat: List[float], tms: List[float]) -> float:
    n = min(len(lon), len(lat), len(tms))
    if n < 2:
        return 0.0

    max_speed_m_s = 0.0
    for index in range(1, n):
        dt = tms[index] - tms[index - 1]
        if dt <= 0:
            continue

        distance = haversine_distance(lon[index - 1], lat[index - 1], lon[index], lat[index])
        if distance <= 0:
            continue

        speed_m_s = distance / dt
        if speed_m_s > max_speed_m_s:
            max_speed_m_s = speed_m_s

    return max_speed_m_s

def main() -> None:
    parser = argparse.ArgumentParser(
        description="按订单计算最高速度，使用原始 GPS 相邻点距离。"
    )
    parser.add_argument(
        "--threshold-kmh",
        type=float,
        default=80.0,
        help="超速阈值（km/h），默认 80 km/h。会写入 is_speeding。",
    )
    args = parser.parse_args()

    with INPUT_FILE.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as dst:
            fieldnames = ["trip_id", "devid", "date", "start_time", "max_speed_kmh", "is_speeding"]
            writer = csv.DictWriter(dst, fieldnames=fieldnames)
            writer.writeheader()

            for idx, raw_row in enumerate(reader, start=1):
                row = clean_row(raw_row)
                order_id = row.get("trip_id") or str(idx)
                devid = row.get("devid")
                if devid is None:
                    raise ValueError("输入文件中未找到 'devid' 列，请检查 top_five.csv 的表头。")

                lon = parse_array_field(row.get("lon"), float)
                lat = parse_array_field(row.get("lat"), float)
                tms = parse_array_field(row.get("tms"), float)

                max_speed_m_s = compute_trip_max_speed_by_gps(lon, lat, tms)
                max_speed_kmh = max_speed_m_s * 3.6
                is_speeding = 1 if max_speed_kmh > args.threshold_kmh else 0

                writer.writerow(
                        {
                            "trip_id": order_id,
                            "devid": devid,
                            "date": format_start_date(tms),
                            "start_time": format_start_time(tms),
                            "max_speed_kmh": f"{max_speed_kmh:.3f}",
                            "is_speeding": is_speeding,
                    }
                )

    print(f"已生成：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
