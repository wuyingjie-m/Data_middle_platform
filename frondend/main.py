import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text

# 1. 明确定义变量名为 app
app = FastAPI()

# 配置跨域（允许前端 index.html 访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库连接配置
DB_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://dqw:dongqiwen2024@127.0.0.1:3306/Data_middle_platform?charset=utf8mb4",
)
engine = create_engine(DB_URL)

DEFAULT_SLOT = "10:00-10:30"


@app.get("/")
def read_root():
    return {"message": "Traffic API is running!"}


@app.get("/api/traffic/{road_id}")
async def get_traffic_stats(road_id: int):
    query = text("""
        SELECT slot_30min, flow_level_30min 
        FROM tdm_tag_road_flow
        WHERE road_id = :road_id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"road_id": road_id}).fetchall()

    if not result:
        raise HTTPException(status_code=404, detail="Road ID not found")

    stats = {i: 0 for i in range(8)}
    labels = ["00-03", "03-06", "06-09", "09-12", "12-15", "15-18", "18-21", "21-24"]

    for row in result:
        try:
            time_part = row[0].split("-")[0]
            hour = int(time_part.split(":")[0])
            bin_index = hour // 3
            if 0 <= bin_index < 8:
                stats[bin_index] += int(row[1])
        except Exception:
            continue

    return [
        {"interval": labels[i], "count": stats[i]}
        for i in range(8)
    ]


def get_latest_report_date():
    query = text("SELECT MAX(date) FROM tdm_tag_road_flow")
    with engine.connect() as conn:
        return conn.execute(query).scalar()


@app.get("/api/top-roads/slot")
async def get_top_roads_by_slot(
        slot_30min: str = DEFAULT_SLOT,
        limit: int = 10,
        date: str | None = None,
        flow_level_30min: int | None = None,
):
    selected_date = date or get_latest_report_date()
    query = text(
        """
        SELECT
            road_id,
            MAX(CAST(traffic_flow_count AS DECIMAL(10, 3))) AS flow_count
        FROM tdm_tag_road_flow
        WHERE slot_30min = :slot_30min
          AND date = :date
          AND (:flow_level_30min IS NULL OR flow_level_30min = :flow_level_30min)
        GROUP BY road_id
        ORDER BY flow_count DESC, road_id ASC
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {
                "slot_30min": slot_30min,
                "limit": limit,
                "date": selected_date,
                "flow_level_30min": flow_level_30min,
            },
        ).fetchall()

    return [
        {
            "rank": idx + 1,
            "road_id": int(row[0]),
            "flow_count": float(row[1]),
            "date": selected_date,
            "flow_level_30min": flow_level_30min,
        }
        for idx, row in enumerate(rows)
    ]


@app.get("/api/top-roads/daily")
async def get_top_roads_by_daily(
        limit: int = 10,
        date: str | None = None,
        flow_level_daily: int | None = None,
):
    selected_date = date or get_latest_report_date()
    query = text(
        """
        SELECT
            road_id,
            SUM(CAST(traffic_flow_count AS DECIMAL(10, 3))) AS flow_count
        FROM tdm_tag_road_flow
        WHERE date = :date
          AND (:flow_level_daily IS NULL OR flow_level_daily = :flow_level_daily)
        GROUP BY road_id
        ORDER BY flow_count DESC, road_id ASC
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {"limit": limit, "date": selected_date, "flow_level_daily": flow_level_daily},
        ).fetchall()

    return [
        {
            "rank": idx + 1,
            "road_id": int(row[0]),
            "flow_count": float(row[1]),
            "date": selected_date,
            "flow_level_daily": flow_level_daily,
        }
        for idx, row in enumerate(rows)
    ]


@app.get("/api/report/dates")
async def get_report_dates():
    query = text(
        """
        SELECT DISTINCT date
        FROM tdm_tag_road_flow
        ORDER BY date DESC
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    return [str(row[0]) for row in rows]


@app.get("/api/report/summary")
async def get_report_summary(date: str | None = None):
    selected_date = date or get_latest_report_date()
    summary_query = text(
        """
        SELECT
            COUNT(DISTINCT road_id) AS road_count,
            SUM(CAST(traffic_flow_count AS DECIMAL(10, 3))) AS total_flow,
            AVG(CAST(traffic_flow_count AS DECIMAL(10, 3))) AS avg_flow
        FROM tdm_tag_road_flow
        WHERE date = :date
        """
    )
    peak_slot_query = text(
        """
        SELECT
            slot_30min,
            SUM(CAST(traffic_flow_count AS DECIMAL(10, 3))) AS slot_flow
        FROM tdm_tag_road_flow
        WHERE date = :date
        GROUP BY slot_30min
        ORDER BY slot_flow DESC, slot_30min ASC
        LIMIT 1
        """
    )

    with engine.connect() as conn:
        summary = conn.execute(summary_query, {"date": selected_date}).mappings().first()
        peak_slot = conn.execute(peak_slot_query, {"date": selected_date}).mappings().first()

    return {
        "date": selected_date,
        "road_count": int(summary["road_count"] or 0),
        "total_flow": float(summary["total_flow"] or 0),
        "avg_flow": float(summary["avg_flow"] or 0),
        "peak_slot": peak_slot["slot_30min"] if peak_slot else None,
        "peak_slot_flow": float(peak_slot["slot_flow"] or 0) if peak_slot else 0,
    }


def parse_percent(value):
    if value is None:
        return 0.0
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return 0.0


def driver_row_to_dict(row):
    data = row._mapping
    speeding_rate_percent = parse_percent(data["speeding_rate"])
    return {
        "devid": str(data["devid"]),
        "date": str(data["date"]),
        "avg_speed_kmh": round(float(data["avg_speed_kmh"] or 0), 3),
        "speed_level": data["speed_level"],
        "speeding_rate": data["speeding_rate"],
        "speeding_rate_percent": speeding_rate_percent,
        "speeding_rule": data["speeding_rule"],
    }


def trip_row_to_dict(row):
    data = row._mapping
    is_speeding = int(data["is_speeding"] or 0)
    return {
        "trip_id": data["trip_id"],
        "devid": str(data["devid"]),
        "date": str(data["date"]),
        "start_time": data["start_time"],
        "max_speed_kmh": round(float(data["max_speed_kmh"] or 0), 3),
        "is_speeding": is_speeding,
    }


def road_speed_row_to_dict(row):
    data = row._mapping
    total_orders = int(data["total_orders"] or 0)
    speeding_orders = int(data["speeding_orders"] or 0)
    speeding_rate_percent = parse_percent(data["speeding_rate"])
    return {
        "road_id": str(data["road_id"]),
        "total_orders": total_orders,
        "speeding_orders": speeding_orders,
        "avg_speed_kmh": round(float(data["avg_speed_kmh"] or 0), 3),
        "speeding_rate": data["speeding_rate"],
        "speeding_rate_percent": speeding_rate_percent,
        "is_high_risk": speeding_orders > 0,
    }


def parse_linestring_geometry(route_geom):
    if not route_geom:
        return []

    content = str(route_geom).strip()
    if not content.startswith("LINESTRING (") or not content.endswith(")"):
        return []

    geometry = []
    for pair in content[len("LINESTRING ("):-1].split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            return []
        try:
            geometry.append([float(parts[0]), float(parts[1])])
        except ValueError:
            return []

    return geometry


def road_map_row_to_dict(row):
    data = row._mapping
    speeding_rate_percent = parse_percent(data["speeding_rate"])
    distance_m = float(data["distance_m"] or 0)
    coord_count = int(data["coord_count"] or 0)
    speeding_orders = int(data["speeding_orders"] or 0)
    return {
        "road_id": str(data["road_id"]),
        "distance_m": round(distance_m, 3),
        "distance_km": round(distance_m / 1000, 3),
        "geometry": parse_linestring_geometry(data["route_geom"]),
        "speeding_rate_percent": speeding_rate_percent,
        "speeding_orders": speeding_orders,
        "avg_speed_kmh": round(float(data["avg_speed_kmh"] or 0), 3),
        "total_orders": int(data["total_orders"] or 0),
        "speeding_rate": data["speeding_rate"] or "0.00%",
        "match_score": coord_count,
    }


def speeding_rate_row_to_dict(row, group_key: str):
    data = row._mapping
    total_trips = int(data["total_trips"] or 0)
    speeding_trips = int(data["speeding_trips"] or 0)
    speeding_rate = (speeding_trips / total_trips * 100) if total_trips else 0
    return {
        group_key: data[group_key],
        "total_trips": total_trips,
        "speeding_trips": speeding_trips,
        "speeding_rate_percent": round(speeding_rate, 2),
    }


def time_speeding_rate_row_to_dict(row):
    data = row._mapping
    hour_key = str(data["hour_key"]).zfill(2)
    total_trips = int(data["total_trips"] or 0)
    speeding_trips = int(data["speeding_trips"] or 0)
    speeding_rate = (speeding_trips / total_trips * 100) if total_trips else 0
    return {
        "time_slot": f"{hour_key}:00-{hour_key}:59",
        "total_trips": total_trips,
        "speeding_trips": speeding_trips,
        "speeding_rate_percent": round(speeding_rate, 2),
    }


def driver_profile_row_to_dict(row):
    """将 tdm_driver_score 表的一行转换为前端所需的字段结构"""
    data = row._mapping
    return {
        "devid": str(data["devid"]),
        "day_count": int(data["day_count"] or 0),
        "trip_count": int(data["trip_count"] or 0),
        "daily_trip_avg": round(float(data["daily_trip_avg"] or 0), 2),
        "precise_total_dist_km": round(float(data["precise_total_dist_km"] or 0), 3),
        "precise_avg_speed_kmh": round(float(data["precise_avg_speed_kmh"] or 0), 3),
        "max_period": str(data["max_period"] or ""),
        "active_level": int(data["active_level"] or 1),
        "morning_trip_cnt": int(data["morning_trip_cnt"] or 0),
        "afternoon_trip_cnt": int(data["afternoon_trip_cnt"] or 0),
        "evening_trip_cnt": int(data["evening_trip_cnt"] or 0),
        "night_trip_cnt": int(data["night_trip_cnt"] or 0),
        "speeding_rate": float(data["speeding_rate"] or 0),
        "speeding_rule": str(data["speeding_rule"] or "normal"),
        "detour_rate": float(data["detour_rate"] or 0),
        "base_score": round(float(data["base_score"] or 0), 4),
        "total_score": int(data["total_score"] or 0),
        "trip_count_score": int(data["trip_count_score"] or 0),
        "daily_trip_avg_score": int(data["daily_trip_avg_score"] or 0),
        "precise_total_dist_km_score": int(data["precise_total_dist_km_score"] or 0),
        "daily_dist_avg_score": int(data["daily_dist_avg_score"] or 0),
        "driver_score_level": int(data["driver_score_level"] or 1),
    }


# ─────────────────────────────────────────────────────────────────
# 用户画像接口（基于 tdm_driver_score 表）
# ─────────────────────────────────────────────────────────────────

@app.get("/api/driver-profiles")
async def get_driver_profiles(limit: int = Query(20, ge=1, le=200)):
    """获取司机画像列表（默认前20条）"""
    query = text("""
        SELECT
            devid,
            day_count,
            trip_count,
            daily_trip_avg,
            precise_total_dist_km,
            precise_avg_speed_kmh,
            max_period,
            active_level,
            morning_trip_cnt,
            afternoon_trip_cnt,
            evening_trip_cnt,
            night_trip_cnt,
            speeding_rate,
            speeding_rule,
            detour_rate,
            base_score,
            total_score,
            trip_count_score,
            daily_trip_avg_score,
            precise_total_dist_km_score,
            daily_dist_avg_score,
            driver_score_level
        FROM tdm_driver_score
        ORDER BY devid ASC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()

    return [driver_profile_row_to_dict(row) for row in rows]


@app.get("/api/driver-profile/{devid}")
async def get_driver_profile(devid: str):
    """根据 devid 查询单个司机画像"""
    query = text("""
        SELECT
            devid,
            day_count,
            trip_count,
            daily_trip_avg,
            precise_total_dist_km,
            precise_avg_speed_kmh,
            max_period,
            active_level,
            morning_trip_cnt,
            afternoon_trip_cnt,
            evening_trip_cnt,
            night_trip_cnt,
            speeding_rate,
            speeding_rule,
            detour_rate,
            base_score,
            total_score,
            trip_count_score,
            daily_trip_avg_score,
            precise_total_dist_km_score,
            daily_dist_avg_score,
            driver_score_level
        FROM tdm_driver_score
        WHERE CAST(devid AS CHAR) = :devid
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"devid": devid}).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Driver not found")

    return driver_profile_row_to_dict(row)


@app.get("/api/speeding/orders")
async def get_speeding_orders(
        status: str = Query("all", pattern="^(all|speeding|normal)$"),
        limit: int = Query(50, ge=1, le=200),
):
    where_sql = ""
    if status == "speeding":
        where_sql = "WHERE CAST(is_speeding AS UNSIGNED) = 1"
    elif status == "normal":
        where_sql = "WHERE CAST(is_speeding AS UNSIGNED) = 0"

    query = text("""
        SELECT trip_id, devid, date, start_time, max_speed_kmh, is_speeding
        FROM trip_speed_table
        {where_sql}
        ORDER BY CAST(is_speeding AS UNSIGNED) DESC,
                 CAST(max_speed_kmh AS DECIMAL(10, 3)) DESC,
                 date ASC,
                 start_time ASC
        LIMIT :limit
    """.format(where_sql=where_sql))

    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()

    return [trip_row_to_dict(row) for row in rows]


@app.get("/api/speeding/order/{trip_id}")
async def get_order_speeding(trip_id: str):
    query = text("""
        SELECT trip_id, devid, date, start_time, max_speed_kmh, is_speeding
        FROM trip_speed_table
        WHERE CAST(trip_id AS CHAR) = :trip_id
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"trip_id": trip_id}).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Trip ID not found")

    return trip_row_to_dict(row)


@app.get("/api/speeding/summary")
async def get_speeding_summary(sort_by: str = Query("speed", pattern="^(speed|risk)$")):
    order_sql = "max_speed_kmh DESC, speeding_rate_value DESC"
    if sort_by == "risk":
        order_sql = "speeding_rate_value DESC, max_speed_kmh DESC"

    summary_query = text("""
        SELECT
            COUNT(*) AS total_trips,
            COALESCE(SUM(CASE WHEN CAST(is_speeding AS UNSIGNED) = 1 THEN 1 ELSE 0 END), 0) AS speeding_trips
        FROM trip_speed_table
    """)
    risk_query = text("""
        SELECT COUNT(*) AS high_risk_drivers
        FROM driver_speed_table
        WHERE speeding_rule = 'high_risk'
    """)
    leaderboard_query = text("""
        SELECT
            d.devid,
            d.date,
            d.avg_speed_kmh,
            d.speed_level,
            d.speeding_rate,
            d.speeding_rule,
            CAST(REPLACE(d.speeding_rate, '%', '') AS DECIMAL(10, 2)) AS speeding_rate_value,
            COUNT(t.trip_id) AS total_trips,
            COALESCE(SUM(CASE WHEN CAST(t.is_speeding AS UNSIGNED) = 1 THEN 1 ELSE 0 END), 0) AS speeding_trips,
            COALESCE(MAX(CAST(t.max_speed_kmh AS DECIMAL(10, 3))), 0) AS max_speed_kmh
        FROM driver_speed_table d
        LEFT JOIN trip_speed_table t ON CAST(t.devid AS CHAR) = CAST(d.devid AS CHAR)
        WHERE d.speeding_rule = 'high_risk'
        GROUP BY
            d.devid,
            d.date,
            d.avg_speed_kmh,
            d.speed_level,
            d.speeding_rate,
            d.speeding_rule
        ORDER BY {order_sql}
        LIMIT 5
    """.format(order_sql=order_sql))

    with engine.connect() as conn:
        summary = conn.execute(summary_query).first()
        risk = conn.execute(risk_query).first()
        leaderboard_rows = conn.execute(leaderboard_query).fetchall()

    if summary is None:
        raise HTTPException(status_code=404, detail="Speeding data not found")

    total_trips = int(summary._mapping["total_trips"] or 0)
    speeding_trips = int(summary._mapping["speeding_trips"] or 0)
    speeding_rate = (speeding_trips / total_trips * 100) if total_trips else 0

    leaderboard = []
    for row in leaderboard_rows:
        data = row._mapping
        leaderboard.append(
            {
                "devid": str(data["devid"]),
                "date": str(data["date"]),
                "avg_speed_kmh": round(float(data["avg_speed_kmh"] or 0), 3),
                "speed_level": data["speed_level"],
                "speeding_rate": data["speeding_rate"],
                "speeding_rate_percent": parse_percent(data["speeding_rate"]),
                "speeding_rule": data["speeding_rule"],
                "total_trips": int(data["total_trips"] or 0),
                "speeding_trips": int(data["speeding_trips"] or 0),
                "max_speed_kmh": round(float(data["max_speed_kmh"] or 0), 3),
            }
        )

    return {
        "total_trips": total_trips,
        "speeding_trips": speeding_trips,
        "speeding_rate_percent": round(speeding_rate, 2),
        "high_risk_drivers": int(risk._mapping["high_risk_drivers"] or 0),
        "leaderboard": leaderboard,
    }


@app.get("/api/speeding/roads")
async def get_speeding_roads(
        sort_by: str = Query("risk", pattern="^(risk|speed|orders)$"),
        high_risk_only: bool = Query(False),
        limit: int = Query(50, ge=1, le=200),
):
    order_sql = "speeding_rate_value DESC, speeding_orders_value DESC, avg_speed_value DESC"
    if sort_by == "speed":
        order_sql = "avg_speed_value DESC, speeding_rate_value DESC"
    elif sort_by == "orders":
        order_sql = "total_orders_value DESC, speeding_rate_value DESC"

    where_sql = ""
    if high_risk_only:
        where_sql = "WHERE CAST(speeding_orders AS UNSIGNED) > 0"

    summary_query = text("""
        SELECT
            COUNT(*) AS total_roads,
            COALESCE(SUM(CASE WHEN CAST(speeding_orders AS UNSIGNED) > 0 THEN 1 ELSE 0 END), 0) AS high_risk_roads
        FROM road_speed_table
    """)
    rows_query = text("""
        SELECT
            road_id,
            total_orders,
            speeding_orders,
            avg_speed_kmh,
            speeding_rate,
            CAST(total_orders AS UNSIGNED) AS total_orders_value,
            CAST(speeding_orders AS UNSIGNED) AS speeding_orders_value,
            CAST(avg_speed_kmh AS DECIMAL(10, 3)) AS avg_speed_value,
            CAST(REPLACE(speeding_rate, '%', '') AS DECIMAL(10, 2)) AS speeding_rate_value
        FROM road_speed_table
        {where_sql}
        ORDER BY {order_sql}
        LIMIT :limit
    """.format(where_sql=where_sql, order_sql=order_sql))

    with engine.connect() as conn:
        summary = conn.execute(summary_query).first()
        rows = conn.execute(rows_query, {"limit": limit}).fetchall()

    return {
        "total_roads": int(summary._mapping["total_roads"] or 0),
        "high_risk_roads": int(summary._mapping["high_risk_roads"] or 0),
        "roads": [road_speed_row_to_dict(row) for row in rows],
    }


@app.get("/api/speeding/road-map")
async def get_speeding_road_map(
        road_id: str | None = None,
        limit: int = Query(200, ge=1, le=2000),
):
    where_sql = ""
    params = {"limit": limit}
    if road_id:
        where_sql = "WHERE CAST(rs.road_id AS CHAR) = :road_id"
        params["road_id"] = road_id

    query = text("""
        SELECT
            rs.road_id,
            rs.total_orders,
            rs.speeding_orders,
            rs.avg_speed_kmh,
            rs.speeding_rate,
            rg.route_geom,
            rg.distance_m,
            rg.coord_count
        FROM road_speed_table rs
        LEFT JOIN road_geom_table rg
          ON CAST(rs.road_id AS CHAR) = CAST(rg.road_id AS CHAR)
        {where_sql}
        ORDER BY
            CAST(REPLACE(rs.speeding_rate, '%', '') AS DECIMAL(10, 2)) DESC,
            CAST(rs.speeding_orders AS UNSIGNED) DESC,
            CAST(rs.avg_speed_kmh AS DECIMAL(10, 3)) DESC
        LIMIT :limit
    """.format(where_sql=where_sql))

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [road_map_row_to_dict(row) for row in rows]


@app.get("/api/speeding/road/{road_id}")
async def get_road_speeding(road_id: str):
    query = text("""
        SELECT
            rs.road_id,
            rs.total_orders,
            rs.speeding_orders,
            rs.avg_speed_kmh,
            rs.speeding_rate,
            rg.route_geom,
            rg.distance_m,
            rg.coord_count
        FROM road_speed_table rs
        LEFT JOIN road_geom_table rg
          ON CAST(rs.road_id AS CHAR) = CAST(rg.road_id AS CHAR)
        WHERE CAST(rs.road_id AS CHAR) = :road_id
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"road_id": road_id}).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Road ID not found")

    return road_map_row_to_dict(row)


@app.get("/api/speeding/by-time")
async def get_speeding_by_time():
    query = text("""
        SELECT hour_key, total_trips, speeding_trips
        FROM (
            SELECT
                SUBSTRING(start_time, 1, 2) AS hour_key,
                COUNT(*) AS total_trips,
                COALESCE(SUM(CASE WHEN CAST(is_speeding AS UNSIGNED) = 1 THEN 1 ELSE 0 END), 0) AS speeding_trips
            FROM trip_speed_table
            WHERE start_time IS NOT NULL AND start_time <> ''
            GROUP BY SUBSTRING(start_time, 1, 2)
        ) AS time_stats
        ORDER BY speeding_trips / total_trips DESC,
                 speeding_trips DESC,
                 total_trips DESC
        LIMIT 5
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    return [time_speeding_rate_row_to_dict(row) for row in rows]


@app.get("/api/speeding/by-date")
async def get_speeding_by_date():
    query = text("""
        SELECT trip_date, total_trips, speeding_trips
        FROM (
            SELECT
                date AS trip_date,
                COUNT(*) AS total_trips,
                COALESCE(SUM(CASE WHEN CAST(is_speeding AS UNSIGNED) = 1 THEN 1 ELSE 0 END), 0) AS speeding_trips
            FROM trip_speed_table
            WHERE date IS NOT NULL AND date <> ''
            GROUP BY date
        ) AS date_stats
        ORDER BY speeding_trips / total_trips DESC,
                 speeding_trips DESC,
                 total_trips DESC
        LIMIT 5
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    return [speeding_rate_row_to_dict(row, "trip_date") for row in rows]


@app.get("/api/speeding/driver/{devid}")
async def get_driver_speeding(devid: str):
    driver_query = text("""
        SELECT devid, date, avg_speed_kmh, speed_level, speeding_rate, speeding_rule
        FROM driver_speed_table
        WHERE CAST(devid AS CHAR) = :devid
        LIMIT 1
    """)
    trips_query = text("""
        SELECT trip_id, devid, date, start_time, max_speed_kmh, is_speeding
        FROM trip_speed_table
        WHERE CAST(devid AS CHAR) = :devid
        ORDER BY CAST(is_speeding AS UNSIGNED) DESC,
                 CAST(max_speed_kmh AS DECIMAL(10, 3)) DESC,
                 date ASC,
                 start_time ASC
    """)

    with engine.connect() as conn:
        driver = conn.execute(driver_query, {"devid": devid}).first()
        trips = conn.execute(trips_query, {"devid": devid}).fetchall()

    if driver is None and not trips:
        raise HTTPException(status_code=404, detail="Driver ID not found")

    return {
        "driver": driver_row_to_dict(driver) if driver else None,
        "trips": [trip_row_to_dict(row) for row in trips],
    }
