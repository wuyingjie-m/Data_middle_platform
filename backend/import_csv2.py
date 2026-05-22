import pandas as pd
from sqlalchemy import create_engine

# 1. 读取 CSV
csv_path = "./tdm_output/tdm_tag_driver_speed.csv"

df = pd.read_csv(csv_path, encoding="utf-8")

# 2. 连接数据库
engine = create_engine(
    "mysql+pymysql://dqw:dongqiwen2024@127.0.0.1:3306/Data_middle_platform?charset=utf8mb4"
)
# 3. 导入 MySQL
df.to_sql(
    name="driver_speed_table",   # 改成你想导入的表名
    con=engine,
    if_exists="replace",      # replace 表示如果表存在就删除重建
    index=False
)

print("CSV 导入成功")