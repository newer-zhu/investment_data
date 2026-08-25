from sqlalchemy import create_engine
import pandas as pd
import fire
import os


def ts_st_info_exists(engine):
    """ts_st_info 表是否存在（ST 数据是否可用）。不存在则不加 is_st，保证失败安全。"""
    try:
        df = pd.read_sql(
            """
            SELECT COUNT(*) AS n
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'ts_st_info'
            """,
            engine
        )
        return int(df["n"].iloc[0]) > 0
    except Exception:
        return False


def build_sql(has_st, with_date=False):
    """构造 dump SQL；has_st 时附带 ts_st_info LEFT JOIN 计算 is_st。

    is_st 语义：1=ST；0=该交易日 ST 数据集已覆盖但不在 ST 名单（确认非 ST）；
    NULL=该交易日无 ST 数据（未知）。
    """
    select_parts = [
        "p.*",
        """CASE
               WHEN p.volume = 0 OR p.volume IS NULL THEN NULL
               ELSE p.amount / p.volume * 10
           END AS vwap""",
    ]
    join_part = ""
    if has_st:
        select_parts.append("""CASE
               WHEN st.ts_code IS NOT NULL THEN 1
               WHEN p.tradedate IN (SELECT DISTINCT tradedate FROM ts_st_info) THEN 0
               ELSE NULL
           END AS is_st""")
        join_part = "LEFT JOIN ts_st_info st ON st.symbol = p.symbol AND st.tradedate = p.tradedate"

    date_filter = "\nAND p.tradedate > %s" if with_date else ""
    sep = ",\n       "
    return f"""
SELECT {sep.join(select_parts)}
FROM final_a_stock_eod_price p
{join_part}
WHERE p.symbol = %s{date_filter}
ORDER BY p.tradedate
"""


def dump_all_to_qlib_source(skip_exists=False):
    # 1. 创建数据库连接（Dolt SQL Server）
    engine = create_engine(
        "mysql+pymysql://root:@127.0.0.1/investment_data",
        pool_recycle=3600
    )

    # 2. 输出目录
    script_path = os.path.dirname(os.path.realpath(__file__))
    output_dir = os.path.join(script_path, "qlib_source")
    os.makedirs(output_dir, exist_ok=True)

    # 3. 先获取 symbol 列表（轻量）
    symbols = pd.read_sql(
        """
        SELECT DISTINCT symbol
        FROM final_a_stock_eod_price
        ORDER BY symbol
        """,
        engine
    )["symbol"].tolist()

    has_st = ts_st_info_exists(engine)
    print(f"ts_st_info available: {has_st}")

    print(f"Total symbols: {len(symbols)}")

    sql = build_sql(has_st)

    # 4. 按 symbol 逐个导出，避免 OOM
    for symbol in symbols:
        filename = os.path.join(output_dir, f"{symbol}.csv")

        if skip_exists and os.path.isfile(filename):
            continue

        print("Dumping:", symbol)

        try:
            df = pd.read_sql(sql, engine, params=(symbol,))
            df.to_csv(filename, index=False)

        except Exception as e:
            print(f"[ERROR] symbol={symbol}, error={e}")

    # 5. 释放连接
    engine.dispose()

def get_last_date(csv_path):
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, usecols=["tradedate"])
        return df["tradedate"].max()
    except Exception:
        return None


def dump_symbol_full(engine, output_dir, symbol, sql):
    """全量重写某 symbol 的 csv（用于旧 csv 缺 is_st 列的过渡补齐）"""
    df = pd.read_sql(sql, engine, params=(symbol,))
    df.to_csv(os.path.join(output_dir, f"{symbol}.csv"), index=False)


def dump_incremental(engine, output_dir):
    has_st = ts_st_info_exists(engine)
    print(f"ts_st_info available: {has_st}")

    symbols = pd.read_sql(
        """
        SELECT DISTINCT symbol
        FROM final_a_stock_eod_price
        ORDER BY symbol
        """,
        engine
    )["symbol"].tolist()

    print(f"[INCREMENTAL] Total symbols: {len(symbols)}")

    sql_full = build_sql(has_st, with_date=False)
    sql_delta = build_sql(has_st, with_date=True)

    for symbol in symbols:
        csv_path = os.path.join(output_dir, f"{symbol}.csv")
        last_date = get_last_date(csv_path)

        if last_date:
            sql = sql_delta
            params = (symbol, last_date)
        else:
            sql = sql_full
            params = (symbol,)

        df = pd.read_sql(sql, engine, params=params)

        if df.empty:
            continue

        # 旧 csv 缺少 is_st 列时，整文件重写补齐，避免追加造成列错位
        if os.path.exists(csv_path):
            try:
                old_cols = pd.read_csv(csv_path, nrows=0).columns
            except Exception:
                old_cols = []
            if "is_st" in df.columns and "is_st" not in old_cols:
                dump_symbol_full(engine, output_dir, symbol, sql_full)
                print(f"[MIGRATE] {symbol}: rewrote csv with is_st")
                continue

        df.to_csv(
            csv_path,
            mode="a" if last_date else "w",
            header=not os.path.exists(csv_path),
            index=False
        )

        print(f"[OK] {symbol}: +{len(df)} rows")


def main(mode="incremental"):
    engine = create_engine(
        "mysql+pymysql://root:@127.0.0.1/investment_data",
        pool_recycle=3600
    )

    script_path = os.path.dirname(os.path.realpath(__file__))
    output_dir = os.path.join(script_path, "qlib_source")
    os.makedirs(output_dir, exist_ok=True)

    if mode == "incremental":
        dump_incremental(engine, output_dir)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    engine.dispose()
  
if __name__ == "__main__":
    fire.Fire(main)
