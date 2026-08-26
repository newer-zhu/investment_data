#!/bin/bash
# ============================================================
# update_st_info.sh — 更新 ST 信息（is_st）到 dolt feature/is_st 分支
#
# 设计要点：
#   - 独立脚本，由 daily_update.sh 失败安全调用：
#         if ! bash update_st_info.sh; then echo "[WARN] ST 更新失败，继续既有流程"; fi
#   - 任何一步失败只影响 is_st，绝不触碰 master 上的既有表与既有流程
#   - 在 dolt feature/is_st 分支上操作；结束时（无论成败）通过 trap 回到进入时分支
#   - ST 历史以 tushare/st_info/*.csv 为累积来源（dolt table import -u 幂等 upsert）
#   - 依赖环境变量 TUSHARE（dump_st_info.py 使用）
# ============================================================
set -e
set -x

DOLT_DIR=/dolt/investment_data
# ST 名单 CSV 目录（默认挂载目录 /output/st_info，宿主机可直接读取；dump_st_info.py 读同一环境变量）
export ST_INFO_DIR=${ST_INFO_DIR:-/output/st_info}
BRANCH=feature/is_st
# 首次建表时的回填起点（YYYY-MM-DD，仅当表为空且未指定 ST_FORCE_START 时使用）。
# 官方 stock_st 数据从 20000101 起；当前代理仅确认 2016-08 起有零散数据、2025 前后才连续，
# 若代理可提供更早数据，可设 ST_BACKFILL_START=2000-01-01。
ST_BACKFILL_START=${ST_BACKFILL_START:-2016-08-01}

cd "$DOLT_DIR"

START_BRANCH=$(dolt branch --show-current)
# 无论成功失败都回到进入时的分支，避免影响调用方（daily_update.sh）流程
trap 'dolt checkout "$START_BRANCH" >/dev/null 2>&1 || true' EXIT

if [ -z "${TUSHARE:-}" ]; then
    echo "[WARN] TUSHARE not set, skip ST info update (is_st)"
    exit 0
fi

# 1. 确保 feature/is_st 分支存在并切换
if ! dolt branch --list | grep -q "$BRANCH"; then
    dolt fetch origin master >/dev/null 2>&1 || true
    dolt branch "$BRANCH" origin/master 2>/dev/null || dolt branch "$BRANCH"
fi
dolt checkout "$BRANCH"

# 2. 刷新 origin/master 引用（基础数据由 daily_update.sh 在主分支同步）
dolt fetch origin master >/dev/null 2>&1 || echo "[WARN] dolt fetch origin master failed"

# 3. 确保 ts_st_info 表存在
dolt sql -q "create table if not exists ts_st_info (
    ts_code varchar(16),
    name varchar(64),
    tradedate date,
    type varchar(16),
    type_name varchar(32),
    symbol varchar(16),
    primary key(symbol, tradedate)
)"

# 4. 确定采集起点
#    - 指定 ST_FORCE_START 时：强制从该日期回填（用于补历史，可早于表内已有数据）
#    - 否则：从表内最大交易日增量采集；空表用 ST_BACKFILL_START
if [ -n "${ST_FORCE_START:-}" ]; then
    START_DATE="$ST_FORCE_START"
else
    START_DATE=$(dolt sql -q "select ifnull(max(tradedate), '$ST_BACKFILL_START') from ts_st_info" -r csv | tail -1 | tr -d '\r')
fi
START_INT=$(date -d "$START_DATE" +%Y%m%d)
echo "[INFO] fetch ST info from $START_INT"
python3 /investment_data/tushare/dump_st_info.py --start_date="$START_INT"

# 5. 导入日期 >= 采集起点的文件（upsert 幂等；同时覆盖回填与增量两种场景）
for f in "$ST_INFO_DIR"/*.csv; do
    [ -f "$f" ] || continue
    d=$(basename "$f" .csv)                 # 2025-08-15
    d_int=$(date -d "$d" +%Y%m%d)
    if [ "$d_int" -ge "$START_INT" ]; then
        dolt table import -u ts_st_info "$f" || echo "[WARN] import failed: $f"
    fi
done

# 6. 提交并推送 feature/is_st（无改动则跳过）
dolt add -A
if dolt commit -m "Update ST info (is_st)"; then
    dolt push --force origin "$BRANCH" || echo "[WARN] push feature/is_st failed"
else
    echo "[INFO] nothing to commit on $BRANCH"
fi
