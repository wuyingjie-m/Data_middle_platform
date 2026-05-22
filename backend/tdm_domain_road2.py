import os
import pandas as pd


# =========================
# 1. 配置区
# =========================

DW_FILE = "dw_output/tdm_domain_road1.csv"

OUTPUT_DIR = "ads_output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "tdm_domain_road2.csv")

CHUNKSIZE = 500000

os.makedirs(OUTPUT_DIR, exist_ok=True)


# =========================
# 2. 生成 30 分钟时间段字符串
# =========================

def format_slot_30min(time_start):
    """
    把 30 分钟时间槽格式化成好识别的字符串。

    示例：
    00:00-00:30
    08:30-09:00
    23:30-24:00
    """

    time_end = time_start + pd.Timedelta(minutes=30)

    start_str = time_start.strftime("%H:%M")

    if (
        time_end.hour == 0
        and time_end.minute == 0
        and time_end.date() != time_start.date()
    ):
        end_str = "24:00"
    else:
        end_str = time_end.strftime("%H:%M")

    return f"{start_str}-{end_str}"


# =========================
# 3. 处理单个 CSV 分块
# =========================

def build_chunk_flow_30min(dw_chunk):
    """
    对一个分块计算：
    road_id + date + slot_30min 维度下的通行次数和去重行程集合。

    注意：
    这里不能直接在每个分块里算 nunique 后相加，
    因为同一个 trip_id 可能出现在多个分块中。
    所以这里先保留去重后的明细：
    road_id + date + slot_30min + trip_id
    后面统一再做最终聚合。
    """

    required_cols = {"trip_id", "road_id", "pass_datetime"}
    missing_cols = required_cols - set(dw_chunk.columns)

    if missing_cols:
        raise ValueError(f"输入 CSV 缺少必要字段：{missing_cols}")

    dw_chunk["pass_datetime"] = pd.to_datetime(
        dw_chunk["pass_datetime"],
        errors="coerce"
    )

    dw_chunk = dw_chunk.dropna(subset=["pass_datetime"]).copy()

    dw_chunk["date"] = dw_chunk["pass_datetime"].dt.date
    dw_chunk["time_start"] = dw_chunk["pass_datetime"].dt.floor("30min")
    dw_chunk["slot_30min"] = dw_chunk["time_start"].apply(format_slot_30min)

    # pass_count：通行次数，可以在分块内先 count，后面再 sum
    # 现在按 trip_id 计数，表示路段通行记录数
    pass_count_part = (
        dw_chunk.groupby(["road_id", "date", "slot_30min"], as_index=False)
        .agg(pass_count=("trip_id", "count"))
    )

    # unique_trip：必须保留 trip_id 去重后的中间结果，不能直接分块 nunique 后相加
    unique_part = (
        dw_chunk[["road_id", "date", "slot_30min", "trip_id"]]
        .drop_duplicates()
    )

    return pass_count_part, unique_part


# =========================
# 4. 构建完整 30 分钟流量统计表
# =========================

def build_ads_route_flow_30min_from_csv():
    """
    从 CSV 分块读取 DW 层数据，生成 ADS 层 30 分钟流量统计表。

    输出字段：
    1. road_id
    2. slot_30min
    3. date
    4. pass_count
    5. unique_trip
    6. daily_avg_unique_trip_30min
    """

    pass_count_parts = []
    unique_parts = []

    total_rows = 0
    chunk_idx = 0

    for dw_chunk in pd.read_csv(DW_FILE, chunksize=CHUNKSIZE):
        chunk_idx += 1
        total_rows += len(dw_chunk)

        print(f"正在处理第 {chunk_idx} 个分块，行数：{len(dw_chunk)}")

        pass_count_part, unique_part = build_chunk_flow_30min(dw_chunk)

        pass_count_parts.append(pass_count_part)
        unique_parts.append(unique_part)

        print(
            f"第 {chunk_idx} 个分块完成："
            f"pass_count_part={len(pass_count_part)} 行，"
            f"unique_part={len(unique_part)} 行"
        )

    print(f"DW CSV 总读取行数：{total_rows}")

    if not pass_count_parts:
        return pd.DataFrame(
            columns=[
                "road_id",
                "slot_30min",
                "date",
                "pass_count",
                "unique_trip",
                "daily_avg_unique_trip_30min"
            ]
        )

    # =========================
    # 4.1 合并 pass_count
    # =========================

    pass_count_all = pd.concat(pass_count_parts, ignore_index=True)

    pass_count_final = (
        pass_count_all.groupby(["road_id", "date", "slot_30min"], as_index=False)
        .agg(pass_count=("pass_count", "sum"))
    )

    # =========================
    # 4.2 合并 unique_trip
    # =========================

    unique_all = pd.concat(unique_parts, ignore_index=True)

    unique_final = (
        unique_all.drop_duplicates(["road_id", "date", "slot_30min", "trip_id"])
        .groupby(["road_id", "date", "slot_30min"], as_index=False)
        .agg(unique_trip=("trip_id", "nunique"))
    )

    # =========================
    # 4.3 合并两个统计结果
    # =========================

    ads = pass_count_final.merge(
        unique_final,
        on=["road_id", "date", "slot_30min"],
        how="left"
    )

    ads["unique_trip"] = ads["unique_trip"].fillna(0).astype(int)

    # =========================
    # 4.4 排序辅助字段
    # =========================

    ads["date"] = pd.to_datetime(ads["date"]).dt.date

    ads["slot_start"] = ads["slot_30min"].str.split("-").str[0]

    ads["time_start"] = pd.to_datetime(
        ads["date"].astype(str) + " " + ads["slot_start"],
        errors="coerce"
    )

    # =========================
    # 4.5 计算每天每条 road 的 30 分钟平均 unique_trip
    # =========================

    ads["daily_avg_unique_trip_30min"] = (
        ads.groupby(["road_id", "date"])["unique_trip"]
        .transform("mean")
        .round(2)
    )

    # =========================
    # 4.6 排序和字段顺序
    # =========================

    ads = ads.sort_values(
        ["road_id", "date", "time_start"],
        ascending=True
    ).reset_index(drop=True)

    ads = ads[
        [
            "road_id",
            "slot_30min",
            "date",
            "pass_count",
            "unique_trip",
            "daily_avg_unique_trip_30min"
        ]
    ]

    return ads


# =========================
# 5. 主程序
# =========================

def main():
    print("开始分块读取 DW 层 CSV 数据...")
    print(f"输入文件：{DW_FILE}")

    ads = build_ads_route_flow_30min_from_csv()

    ads.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print("ADS 统计完成")
    print(f"输出文件：{OUTPUT_FILE}")
    print(f"统计结果行数：{len(ads)}")

    print("\n前 20 行结果：")
    print(ads.head(20))


if __name__ == "__main__":
    main()