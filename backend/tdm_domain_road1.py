import os
import re
import pandas as pd


# =========================
# 1. 配置区
# =========================

INPUT_FILE = "valid_all.csv"
OUTPUT_DIR = "dw_output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "tdm_domain_road1.csv")

# CSV 分块大小，真实 1GB 数据建议分块处理
CHUNKSIZE = 50000

os.makedirs(OUTPUT_DIR, exist_ok=True)


# =========================
# 2. 数组解析函数
# =========================

def parse_int_array(value):
    """
    解析数组字符串，支持整数和小数。
    会把 1420214433.0 正确转成 1420214433。
    """
    if pd.isna(value):
        return []

    s = str(value)
    nums = re.findall(r"-?\d+(?:\.\d+)?", s)
    return [int(float(x)) for x in nums]


# =========================
# 3. 压缩 roads/time 观测点
# =========================

def compress_observed_roads(roads, times):
    """
    roads 是每个 time 时刻车辆所在的道路。
    如果连续多次出现在同一条 road 上，只保留第一次出现的时间。
    """

    observed = []
    last_road = None

    for road, t in zip(roads, times):
        if road != last_road:
            observed.append((road, t))
            last_road = road

    return observed


# =========================
# 4. 将 roads/time 锚点匹配到 route
# =========================

def align_observed_to_route(route, observed):
    """
    把 roads/time 中观测到的 road，按顺序匹配到 route 中。
    """

    anchors = []
    search_start = 0

    for road_id, tms in observed:
        matched_idx = None

        for idx in range(search_start, len(route)):
            if route[idx] == road_id:
                matched_idx = idx
                break

        if matched_idx is not None:
            anchors.append({
                "route_idx": matched_idx,
                "road_id": road_id,
                "tms": int(tms)
            })
            search_start = matched_idx + 1

    return anchors


# =========================
# 5. 给 route 中每条 road 补时间
# =========================

def interpolate_route_times(route, anchors):
    """
    根据 roads/time 锚点，给 route 中每条 road 分配时间。
    两个锚点之间的 route 路段，时间均匀分配。
    """

    n = len(route)

    if n == 0:
        return []

    pass_tms_list = [None] * n

    # 没有锚点，无法补时间
    if len(anchors) == 0:
        return [
            {
                "route_idx": idx,
                "road_id": route[idx],
                "pass_tms": None
            }
            for idx in range(n)
        ]

    # 先填入观测锚点时间
    for anchor in anchors:
        idx = anchor["route_idx"]
        pass_tms_list[idx] = anchor["tms"]

    # 第一个锚点之前的 route，统一使用第一个锚点时间
    first_anchor = anchors[0]
    first_idx = first_anchor["route_idx"]

    for idx in range(0, first_idx):
        pass_tms_list[idx] = first_anchor["tms"]

    # 相邻两个锚点之间，均匀分配时间
    for left, right in zip(anchors[:-1], anchors[1:]):
        left_idx = left["route_idx"]
        right_idx = right["route_idx"]

        left_tms = left["tms"]
        right_tms = right["tms"]

        idx_gap = right_idx - left_idx

        if idx_gap <= 0:
            continue

        time_gap = right_tms - left_tms

        for idx in range(left_idx, right_idx + 1):
            ratio = (idx - left_idx) / idx_gap
            pass_tms_list[idx] = int(round(left_tms + ratio * time_gap))

    # 最后一个锚点之后的 route，统一使用最后一个锚点时间
    last_anchor = anchors[-1]
    last_idx = last_anchor["route_idx"]

    for idx in range(last_idx + 1, n):
        pass_tms_list[idx] = last_anchor["tms"]

    result = []

    for idx in range(n):
        result.append({
            "route_idx": idx,
            "road_id": route[idx],
            "pass_tms": pass_tms_list[idx]
        })

    return result


# =========================
# 6. 处理单条行程
# =========================

def build_one_trip_route_pass(row, row_global_idx):
    """
    原始数据一行 = 一次行程。

    输入字段：
    devid
    route
    roads
    time

    输出：
    多行 route 通行记录。

    trip_id：
    原始数据中没有 trip_id，因此这里人工生成：
    trip_id = devid + 原始数据全局行号
    """

    devid = row["devid"]

    # 人工构造 trip_id
    trip_id = f"{devid}_{row_global_idx}"

    route = parse_int_array(row["route"])
    roads = parse_int_array(row["roads"])
    times = parse_int_array(row["time"])

    if len(route) == 0:
        return []

    # roads 和 time 理论上一一对应，这里做保护
    n = min(len(roads), len(times))
    roads = roads[:n]
    times = times[:n]

    observed = compress_observed_roads(roads, times)
    anchors = align_observed_to_route(route, observed)
    route_time_records = interpolate_route_times(route, anchors)

    records = []

    for item in route_time_records:
        records.append({
            "trip_id": trip_id,
            "devid": devid,
            "route_idx": item["route_idx"],
            "road_id": item["road_id"],
            "pass_tms": item["pass_tms"]
        })

    return records


# =========================
# 7. 构建一个分块的 DW 层表
# =========================

def build_dw_fact_route_pass(df_chunk, chunk_start_idx):
    """
    构建当前分块的 DW 层 route 通行明细表。

    输出字段：
    trip_id
    devid
    route_idx
    road_id
    pass_tms
    pass_datetime
    """

    all_records = []

    for local_idx, row in df_chunk.reset_index(drop=True).iterrows():
        row_global_idx = chunk_start_idx + local_idx
        records = build_one_trip_route_pass(row, row_global_idx)
        all_records.extend(records)

    dw = pd.DataFrame(all_records)

    if dw.empty:
        return dw

    # 时间戳转北京时间
    dw["pass_datetime"] = (
        pd.to_datetime(dw["pass_tms"], unit="s", errors="coerce", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.tz_localize(None)
    )

    dw = dw[
        [
            "trip_id",
            "devid",
            "route_idx",
            "road_id",
            "pass_tms",
            "pass_datetime"
        ]
    ]

    return dw


# =========================
# 8. 主程序：分块读取 CSV
# =========================

def main():
    print("开始读取 CSV 原始数据...")

    # 如果之前已经有输出文件，先删除，避免重复追加
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    total_input_rows = 0
    total_output_rows = 0
    chunk_idx = 0

    required_cols = {"devid", "route", "roads", "time"}

    for df_chunk in pd.read_csv(INPUT_FILE, chunksize=CHUNKSIZE):
        chunk_idx += 1

        # 记录当前分块在原始全表中的起始行号
        chunk_start_idx = total_input_rows

        total_input_rows += len(df_chunk)

        print(f"正在处理第 {chunk_idx} 个分块，原始行数：{len(df_chunk)}")

        missing_cols = required_cols - set(df_chunk.columns)
        if missing_cols:
            raise ValueError(f"CSV 缺少必要字段：{missing_cols}")

        dw_chunk = build_dw_fact_route_pass(df_chunk, chunk_start_idx)
        total_output_rows += len(dw_chunk)

        # 第一个分块写入表头，后续分块追加但不写表头
        dw_chunk.to_csv(
            OUTPUT_FILE,
            mode="a",
            header=not os.path.exists(OUTPUT_FILE),
            index=False,
            encoding="utf-8-sig"
        )

        print(f"第 {chunk_idx} 个分块完成，输出 DW 行数：{len(dw_chunk)}")

    print("DW 层构建完成")
    print(f"输入原始行数：{total_input_rows}")
    print(f"输出 DW 记录数：{total_output_rows}")
    print(f"输出文件：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()