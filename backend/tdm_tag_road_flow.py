import os
import pandas as pd
import numpy as np


# =========================
# 1. 配置区
# =========================

INPUT_FILE = "ads_output/tdm_domain_road2.csv"

OUTPUT_DIR = "ads_output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "tdm_tag_road_flow.csv")

os.makedirs(OUTPUT_DIR, exist_ok=True)


# =========================
# 2. 分位数打标函数
# =========================

def assign_flow_level_by_quantile(series):
    """
    按 20% / 40% / 60% / 80% 分位数，把 unique_trip 离散成 1-5 级。

    1 = 畅通
    2 = 较畅通
    3 = 一般
    4 = 拥堵
    5 = 严重拥堵
    """

    series = pd.to_numeric(series, errors="coerce").fillna(0)

    if series.nunique() <= 1:
        return pd.Series(1, index=series.index)

    q20 = series.quantile(0.2)
    q40 = series.quantile(0.4)
    q60 = series.quantile(0.6)
    q80 = series.quantile(0.8)

    def get_level(x):
        if x <= q20:
            return 1
        elif x <= q40:
            return 2
        elif x <= q60:
            return 3
        elif x <= q80:
            return 4
        else:
            return 5

    return series.apply(get_level)


# =========================
# 3. 构建热力图流量等级表
# =========================

def build_tdm_tag_road_flow(df):
    """
    输入：
    tdm_domain_road2.csv

    需要至少包含字段：
    road_id
    slot_30min
    date
    unique_trip

    输出：
    road_id
    slot_30min
    date
    flow_level_30min
    flow_level_daily
    heat_weight_30min
    heat_weight_daily
    traffic_flow_count
    """

    required_cols = ["road_id", "slot_30min", "date", "unique_trip"]

    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"输入文件缺少必要字段：{missing_cols}")

    df = df.copy()

    # 统一日期格式
    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    # 当前流量统计口径：unique_trip
    df["unique_trip"] = pd.to_numeric(
        df["unique_trip"],
        errors="coerce"
    ).fillna(0)

    # =========================
    # 3.1 当前 slot_30min 内分级
    # =========================
    # 同一天、同一个30分钟时间段内，对所有 road 的 unique_trip 做分位数分级
    df["flow_level_30min"] = (
        df.groupby(["date", "slot_30min"], group_keys=False)["unique_trip"]
        .apply(assign_flow_level_by_quantile)
        .astype(int)
    )

    # =========================
    # 3.2 当天全时段分级
    # =========================
    # 同一天内，把所有 road、所有 slot_30min 的 unique_trip 放在一起做分位数分级
    df["flow_level_daily"] = (
        df.groupby(["date"], group_keys=False)["unique_trip"]
        .apply(assign_flow_level_by_quantile)
        .astype(int)
    )

    # =========================
    # 3.3 归一化热力权重
    # =========================
    # flow_level 是 1-5，归一化为 0.2-1.0
    df["heat_weight_30min"] = (
        df["flow_level_30min"] / 5
    ).round(2)

    df["heat_weight_daily"] = (
        df["flow_level_daily"] / 5
    ).round(2)

    # =========================
    # 3.4 新增车流量计数值
    # =========================
    # 当前口径：流量计数值 = 当前 road 在当前 30 分钟内的去重 trip 数
    df["traffic_flow_count"] = df["unique_trip"].astype(int)

    # 调整字段顺序
    result = df[
        [
            "road_id",
            "slot_30min",
            "date",
            "flow_level_30min",
            "flow_level_daily",
            "heat_weight_30min",
            "heat_weight_daily",
            "traffic_flow_count"
        ]
    ].copy()

    result = result.sort_values(
        ["date", "slot_30min", "road_id"],
        ascending=True
    ).reset_index(drop=True)

    return result


# =========================
# 4. 主程序
# =========================

def main():
    print("开始读取 30 分钟路段流量统计表...")

    df = pd.read_csv(INPUT_FILE)

    print(f"输入数据行数：{len(df)}")
    print(f"输入字段：{list(df.columns)}")

    print("开始构建路段流量等级标签表...")

    result = build_tdm_tag_road_flow(df)

    result.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print("流量等级标签表构建完成")
    print(f"输出文件：{OUTPUT_FILE}")
    print(f"输出行数：{len(result)}")

    print("\n前 20 行结果：")
    print(result.head(20))

    print("\nflow_level_30min 分布：")
    print(result["flow_level_30min"].value_counts().sort_index())

    print("\nflow_level_daily 分布：")
    print(result["flow_level_daily"].value_counts().sort_index())

    print("\ntraffic_flow_count 描述统计：")
    print(result["traffic_flow_count"].describe())


if __name__ == "__main__":
    main()