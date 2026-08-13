import fire
import pandas as pd

try:
  from data_collector.base import Normalize
  from data_collector.yahoo import collector as yahoo_collector
except ImportError as e:
  print("============")
  print("ATTENTION: Need to put qlib/scripts directory into PYTHONPATH")
  print("============")
  raise e

class CrowdSourceNormalize(yahoo_collector.YahooNormalizeCN1d):
  # Add vwap so that vwap will be adjusted during normalization
  COLUMNS = ["open", "close", "high", "low", "vwap", "volume"]

  def _manual_adj_data(self, df: pd.DataFrame) -> pd.DataFrame:
    # amount should be kept as original value, so that adjusted volume * adjust vwap = amount
    result_df = super()._manual_adj_data(df)
    result_df["amount"] = df["amount"]
    return result_df

class FixedNormalize(Normalize):
  """Fix qlib's Normalize.format_data, which hardcodes the column name "date"
  and therefore always drops the last row when a custom --date_field_name
  (e.g. tradedate) is used."""

  def format_data(self, df: pd.DataFrame) -> pd.DataFrame:
    if self.interval == "1d":
      try:
        pd.to_datetime(df.iloc[-1][self._date_field_name], format="%Y-%m-%d", errors="raise")
      except Exception:
        df = df.iloc[:-1]
    return df

def normalize_crowd_source_data(source_dir=None, normalize_dir=None, max_workers=1, interval="1d", date_field_name="tradedate", symbol_field_name="symbol"):
    import multiprocessing as mp
    mp.set_start_method("spawn", force=True)
    yc = FixedNormalize(
        source_dir=source_dir,
        target_dir=normalize_dir,
        normalize_class=CrowdSourceNormalize,
        max_workers=max_workers,
        date_field_name=date_field_name,
        symbol_field_name=symbol_field_name,
    )
    yc.normalize()

if __name__ == "__main__":
    fire.Fire(normalize_crowd_source_data)
