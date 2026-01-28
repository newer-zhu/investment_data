from sqlalchemy import create_engine
import pandas as pd
import fire
import os

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

    print(f"Total symbols: {len(symbols)}")

    # 4. 按 symbol 逐个导出，避免 OOM
    for symbol in symbols:
        filename = os.path.join(output_dir, f"{symbol}.csv")

        if skip_exists and os.path.isfile(filename):
            continue

        print("Dumping:", symbol)

        try:
            df = pd.read_sql(
                """
                SELECT *,
                       CASE
                           WHEN volume = 0 OR volume IS NULL THEN NULL
                           ELSE amount / volume * 10
                       END AS vwap
                FROM final_a_stock_eod_price
                WHERE symbol = %s
                ORDER BY tradedate
                """,
                engine,
                params=(symbol,)   # SQLAlchemy 2.x 必须是 tuple
            )

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


def dump_incremental(engine, output_dir):
    symbols = pd.read_sql(
        """
        SELECT DISTINCT symbol
        FROM final_a_stock_eod_price
        ORDER BY symbol
        """,
        engine
    )["symbol"].tolist()

    print(f"[INCREMENTAL] Total symbols: {len(symbols)}")

    for symbol in symbols:
        csv_path = os.path.join(output_dir, f"{symbol}.csv")
        last_date = get_last_date(csv_path)

        if last_date:
            sql = """
            SELECT *,
                   CASE
                       WHEN volume = 0 OR volume IS NULL THEN NULL
                       ELSE amount / volume * 10
                   END AS vwap
            FROM final_a_stock_eod_price
            WHERE symbol = %s AND tradedate > %s
            ORDER BY tradedate
            """
            params = (symbol, last_date)
        else:
            sql = """
            SELECT *,
                   CASE
                       WHEN volume = 0 OR volume IS NULL THEN NULL
                       ELSE amount / volume * 10
                   END AS vwap
            FROM final_a_stock_eod_price
            WHERE symbol = %s
            ORDER BY tradedate
            """
            params = (symbol,)

        df = pd.read_sql(sql, engine, params=params)

        if df.empty:
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

    if mode == "full":
        dump_full(engine, output_dir)
    elif mode == "incremental":
        dump_incremental(engine, output_dir)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    engine.dispose()
  
if __name__ == "__main__":
    fire.Fire(main)
