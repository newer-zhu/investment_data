from sqlalchemy import create_engine
import pandas as pd
import fire
import os


DB_URI = "mysql+pymysql://root:@127.0.0.1/investment_data"


def get_engine():
    return create_engine(DB_URI, pool_recycle=3600)


def get_all_symbols(engine):
    return pd.read_sql(
        """
        SELECT DISTINCT symbol
        FROM final_a_stock_eod_price
        ORDER BY symbol
        """,
        engine
    )["symbol"].tolist()


def get_last_date(csv_path):
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, usecols=["tradedate"])
        return df["tradedate"].max()
    except Exception:
        return None


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


def dump_symbol_full(engine, output_dir, symbol, sql):
    """全量重写某 symbol 的 csv（用于旧 csv 缺 is_st 列的过渡补齐）"""
    df = pd.read_sql(sql, engine, params=(symbol,))
    df.to_csv(os.path.join(output_dir, f"{symbol}.csv"), index=False)


def dump_full(engine, output_dir):
    has_st = ts_st_info_exists(engine)
    print(f"ts_st_info available: {has_st}")

    symbols = get_all_symbols(engine)
    print(f"[FULL] Total symbols: {len(symbols)}")

    sql = build_sql(has_st)

    for symbol in symbols:
        print("[FULL] Dumping:", symbol)
        csv_path = os.path.join(output_dir, f"{symbol}.csv")

        df = pd.read_sql(sql, engine, params=(symbol,))
        df.to_csv(csv_path, index=False)


def dump_incremental(engine, output_dir, start_date=None):
    has_st = ts_st_info_exists(engine)
    print(f"ts_st_info available: {has_st}")

    symbols = get_all_symbols(engine)
    print(f"[INCREMENTAL] Total symbols: {len(symbols)}")

    sql_full = build_sql(has_st, with_date=False)
    sql_delta = build_sql(has_st, with_date=True)

    for symbol in symbols:
        csv_path = os.path.join(output_dir, f"{symbol}.csv")

        # 决定起始日期
        if start_date:
            effective_start_date = start_date
        else:
            effective_start_date = get_last_date(csv_path)

        if effective_start_date:
            sql = sql_delta
            params = (symbol, effective_start_date)
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
            mode="a" if os.path.exists(csv_path) else "w",
            header=not os.path.exists(csv_path),
            index=False
        )

        print(f"[OK] {symbol}: +{len(df)} rows")


def main(
    mode="incremental",
    start_date=None,
    output_dir=None,
):
    """
    Parameters
    ----------
    mode : str
        full | incremental
    start_date : str
        手动指定增量起始日期，例如 20200101
    output_dir : str
        输出目录，默认 ./qlib_source
    """

    engine = get_engine()

    if output_dir is None:
        script_path = os.path.dirname(os.path.realpath(__file__))
        output_dir = os.path.join(script_path, "qlib_source")

    os.makedirs(output_dir, exist_ok=True)

    if mode == "full":
        dump_full(engine, output_dir)
    elif mode == "incremental":
        dump_incremental(engine, output_dir, start_date=start_date)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    engine.dispose()


if __name__ == "__main__":
    fire.Fire(main)

