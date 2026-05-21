import pandas as pd
import requests
import time
import math
import ast

# ================== 高德 API 配置 ==================
API_KEY = "0618c3e58ea55b7bfb47747023a7c81f"
URL = "https://restapi.amap.com/v3/direction/driving"


# ================== 坐标转换函数（WGS-84 → GCJ-02）==================
def wgs84_to_gcj02(lon, lat):
    a = 6378245.0
    ee = 0.00669342162296594323

    def out_of_china(lon, lat):
        return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)

    if out_of_china(lon, lat):
        return lon, lat

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    gcj_lat = lat + dlat
    gcj_lon = lon + dlon
    return gcj_lon, gcj_lat


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


# ================== 半正矢距离计算（GCJ-02坐标系，单位：米）==================
def haversine_distance(lon1, lat1, lon2, lat2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ================== 解析 LINESTRING 字符串 ==================
def parse_linestring(linestring_str):
    content = linestring_str.strip()
    if content.startswith("LINESTRING ("):
        content = content[12:-1]
    else:
        raise ValueError(f"Unexpected LINESTRING format: {linestring_str}")
    points = []
    for pair in content.split(','):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid coordinate pair: {pair}")
        lon = float(parts[0])
        lat = float(parts[1])
        points.append((lon, lat))
    return points


# ================== 从 LINESTRING 列表计算实际行驶距离 ==================
def compute_actual_distance_from_strings(linestring_strings):
    total_dist = 0.0
    prev_point = None
    for ls_str in linestring_strings:
        wgs_points = parse_linestring(ls_str)
        for lon_wgs, lat_wgs in wgs_points:
            lon_gcj, lat_gcj = wgs84_to_gcj02(lon_wgs, lat_wgs)
            if prev_point is not None:
                dist = haversine_distance(prev_point[0], prev_point[1], lon_gcj, lat_gcj)
                total_dist += dist
            prev_point = (lon_gcj, lat_gcj)
    return total_dist


# ================== 调用高德 API 获取最短路径距离 ==================
def get_shortest_distance(start_lon, start_lat, end_lon, end_lat, retry=3):
    params = {
        "key": API_KEY,
        "origin": f"{start_lon},{start_lat}",
        "destination": f"{end_lon},{end_lat}",
        "extensions": "base",
        "strategy": 0
    }
    for attempt in range(retry):
        try:
            resp = requests.get(URL, params=params, timeout=10)
            data = resp.json()
            if data["status"] == "1" and data["route"]["paths"]:
                return int(data["route"]["paths"][0]["distance"])
            else:
                print(f"API错误: {data.get('info', '未知错误')}")
                return None
        except Exception as e:
            print(f"请求失败 (尝试 {attempt + 1}/{retry}): {e}")
            time.sleep(0.5)
    return None


# ================== 主处理流程 ==================
def main():
    # 需要处理的司机ID集合
    test_devid = {
        300018856, 300042163, 100305621, 300020709, 300061639, 300039456,
        300061574, 300040015, 100324051, 300019684, 300042216, 100320548,
        300023732, 300025652, 300019996, 300020338, 300015885, 300061078,
        300019530, 300061821, 100324266, 300024336, 300042331, 300023555,
        300020293, 300024231
    }

    # ---------- 1. 读取 dw_trip.csv，计算最短距离 ----------
    print("正在读取 dw_trip.csv ...")
    df_trip = pd.read_csv(
        "D:\\wechat_file\\xwechat_files\\wxid_twjg2uwvf98812_f3fe\\msg\\file\\2026-05\\data\\dw_trip.csv")
    # 过滤司机
    df_trip = df_trip[df_trip["devid"].isin(test_devid)].copy()

    shortest_results = []
    for idx, row in df_trip.iterrows():
        devid = row["devid"]
        start_lon, start_lat = row["start_lon"], row["start_lat"]
        end_lon, end_lat = row["end_lon"], row["end_lat"]
        o_lon, o_lat = wgs84_to_gcj02(start_lon, start_lat)
        d_lon, d_lat = wgs84_to_gcj02(end_lon, end_lat)

        dist = get_shortest_distance(o_lon, o_lat, d_lon, d_lat)
        if dist is None:
            print(f"第 {idx} 行计算失败，trip_id={row['trip_id']}")
            dist = -1
        else:
            print(f"第 {idx} 行计算成功，trip_id={row['trip_id']}，距离={dist}米")

        shortest_results.append({
            "trip_id": row["trip_id"],
            "devid": devid,
            "stat_date": row["stat_date"],
            "shortest_distance": dist
        })
        time.sleep(1)  # 控制API频率

    df_shortest = pd.DataFrame(shortest_results)
    # 去重（防止原数据有重复）
    df_shortest = df_shortest.drop_duplicates(subset=["trip_id", "devid"])

    # ---------- 2. 读取 dw_route.csv，计算实际行驶距离 ----------
    print("正在读取 dw_route.csv ...")
    # 使用 csv.DictReader 逐行处理（避免一次性加载大文件，但此处过滤后数据量小，也可用pandas）
    route_data = []
    with open("D:\\BaiduNetdisk\\dw_route.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            devid = int(row["devid"])
            if devid not in test_devid:
                continue
            trip_id = row["trip_id"]
            route_geom_arr_str = row["route_geom_arr"]
            try:
                linestring_list = ast.literal_eval(route_geom_arr_str)
                if not isinstance(linestring_list, list):
                    raise ValueError("route_geom_arr is not a list")
                trip_dis = compute_actual_distance_from_strings(linestring_list)
                print(f"正在计算订单 {trip_id}，实际距离={trip_dis:.2f}米")
            except Exception as e:
                print(f"Error parsing or computing for trip {trip_id}: {e}")
                trip_dis = 0.0
            route_data.append({
                "trip_id": trip_id,
                "devid": devid,
                "trip_dis": round(trip_dis, 2)
            })

    df_dis = pd.DataFrame(route_data)
    df_dis = df_dis.drop_duplicates(subset=["trip_id", "devid"])

    # ---------- 3. 合并并计算 detour ----------
    merged = pd.merge(df_dis, df_shortest, on=["trip_id", "devid"], how="inner")
    merged["detour"] = (merged["trip_dis"] > 2 * merged["shortest_distance"]).astype(int)

    result = merged[["trip_id", "devid", "stat_date", "trip_dis", "shortest_distance", "detour"]]
    output_path = "D:\\wechat_file\\xwechat_files\\wxid_twjg2uwvf98812_f3fe\\msg\\file\\2026-05\\data\\tdm_daily_detour.csv"
    result.to_csv(output_path, index=False)
    print(f"处理完成，结果已保存至 {output_path}")


if __name__ == "__main__":
    import csv  # 确保csv模块可用

    main()