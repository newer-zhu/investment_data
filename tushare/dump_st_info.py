import tushare as ts
import os
import datetime
import pandas
import fire
import time
from typing import Optional

# tushare版本 1.4.24
token = os.environ["TUSHARE"]
pro = ts.pro_api(token, timeout=6000)
pro._DataApi__token = token  # 保证有这个代码，不然不可以获取
pro._DataApi__http_url = 'https://tuaremax.top'  # 保证有这个代码，不然不可以获取
# ST 名单 CSV 输出目录（默认挂载目录 /output，宿主机可直接读取过滤 ST 股票）
ST_INFO_DIR = os.environ.get("ST_INFO_DIR", "/output/st_info")

# stock_st 单次请求最大返回行数（官方文档说明），超过会被截断（实测只返回最近 1000 行）
MAX_ROWS_PER_REQ = 1000


def get_st_info(start_date, end_date):
    for _ in range(3):
        try:
            return pro.stock_st(start_date=start_date, end_date=end_date)
        except Exception as e:
            print(e)
            time.sleep(1)


def save_daily(data, skip_exists):
    """把 stock_st 返回的一批数据按交易日拆分成 st_info/{trade_date}.csv

    列：ts_code, name, tradedate(YYYY-MM-DD), type, type_name, symbol(SH/SZ 前缀 final 格式)
    """
    data = data.copy()
    # stock_st 返回的 trade_date 是 YYYYMMDD，统一成 YYYY-MM-DD 并改名 tradedate，
    # 与仓库 dolt 表列名约定保持一致，方便 dolt table import 直接导入
    data["trade_date"] = pandas.to_datetime(data["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    data = data.rename(columns={"trade_date": "tradedate"})
    # ts_code 600421.SH -> symbol SH600421（final_a_stock_eod_price 的格式）
    data["symbol"] = data["ts_code"].str[7:9] + data["ts_code"].str[0:6]

    for td, day_data in data.groupby("tradedate"):
        filename = f'{ST_INFO_DIR}/{td}.csv'
        if skip_exists and os.path.isfile(filename):
            continue
        day_data.to_csv(filename, index=False)


def dump_st_info(start_date: str = "20000101", end_date: Optional[str] = None, skip_exists: bool = True, chunk_days: int = 4):
    """
    从 tushare stock_st 接口按交易日拉取 ST 股票列表。

    每个交易日的 ST 名单保存为 st_info/{trade_date}.csv。
    不依赖 trade_cal（当前代理上该接口有编码 bug），按小段区间直接查 stock_st，
    若触及 1000 行上限（可能被截断）则退化为逐日查询。

    Parameters
    ----------
    start_date : str
        开始日期 YYYYMMDD，默认 20000101（stock_st 官方数据起点）
    end_date : str
        结束日期 YYYYMMDD，默认今天
    skip_exists : bool
        已存在文件则跳过，默认 True
    chunk_days : int
        区间查询按多少自然日分一段，默认 4（最多 4 个交易日，远低于 1000 行上限）
    """
    # fire 会把纯数字参数（如 --start_date=20250811）转成 int，统一强制转回 str
    start_date = str(start_date)
    end_date = str(end_date) if end_date else datetime.datetime.now().strftime('%Y%m%d')

    if not os.path.exists(ST_INFO_DIR):
        os.makedirs(ST_INFO_DIR)

    start = datetime.datetime.strptime(start_date, '%Y%m%d')
    end = datetime.datetime.strptime(end_date, '%Y%m%d')
    step = datetime.timedelta(days=chunk_days)

    cur = start
    while cur <= end:
        chunk_end = min(cur + step - datetime.timedelta(days=1), end)
        s = cur.strftime('%Y%m%d')
        e = chunk_end.strftime('%Y%m%d')
        print(s, e)

        data = get_st_info(s, e)
        if data is None or data.empty:
            cur = chunk_end + datetime.timedelta(days=1)
            continue

        if len(data) >= MAX_ROWS_PER_REQ:
            # 触及单次请求上限，结果可能被截断，退化为逐日查询保证完整
            print(f"[WARN] chunk {s}-{e} hits {MAX_ROWS_PER_REQ} rows, fallback to per-day query")
            cur2 = cur
            while cur2 <= chunk_end:
                day_data = get_st_info(cur2.strftime('%Y%m%d'), cur2.strftime('%Y%m%d'))
                if day_data is not None and not day_data.empty:
                    save_daily(day_data, skip_exists)
                cur2 += datetime.timedelta(days=1)
        else:
            save_daily(data, skip_exists)

        cur = chunk_end + datetime.timedelta(days=1)


if __name__ == '__main__':
    fire.Fire(dump_st_info)
