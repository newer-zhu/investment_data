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


def dump_full(engine, output_dir):
    symbols = get_all_symbols(engine)
    print(f"[FULL] Total symbols: {len(symbols)}")

    for symbol in symbols:
        print("[FULL] Dumping:", symbol)
        csv_path = os.path.join(output_dir, f"{symbol}.csv")

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
            params=(symbol,)
        )

        df.to_csv(csv_path, index=False)


def dump_incremental(engine, output_dir, start_date=None):
    symbols = get_all_symbols(engine)
    print(f"[INCREMENTAL] Total symbols: {len(symbols)}")

    for symbol in symbols:
        csv_path = os.path.join(output_dir, f"{symbol}.csv")

        # 决定起始日期
        if start_date:
            effective_start_date = start_date
        else:
            effective_start_date = get_last_date(csv_path)

        if effective_start_date:
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
            params = (symbol, effective_start_date)
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

