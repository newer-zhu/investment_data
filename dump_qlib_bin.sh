set -e
set -x
FINANCE=false
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --finance)
            FINANCE=true
            shift
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                POSITIONAL+=("$1")
                shift
            done
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

set -- "${POSITIONAL[@]}"
WORKING_DIR=${1:?"Usage: $0 WORKING_DIR [MODE] [QLIB_REPO] [--finance]"}
MODE=${2:-incremental}
QLIB_REPO=${3:-https://github.com/microsoft/qlib.git}

if ! command -v dolt &> /dev/null
then
    curl -L https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash
fi

mkdir -p $WORKING_DIR/dolt

[ ! -d "$WORKING_DIR/dolt/investment_data" ] && cd $WORKING_DIR/dolt && dolt clone chenditc/investment_data
[ ! -d "$WORKING_DIR/qlib" ] && git clone $QLIB_REPO "$WORKING_DIR/qlib"

cd $WORKING_DIR/dolt/investment_data
dolt pull origin master

# ============ ST 信息（is_st）—— 失败安全，不影响既有流程 ============
# ts_st_info 在 feature/is_st dolt 分支上；dump 走 master。
# 这里从本地 tushare/st_info CSV 重建 ts_st_info（无 CSV 则建空表，is_st 全为未知）。
# 任何一步失败都只影响 is_st，不影响量价 dump。
echo "Importing ST info (ts_st_info) from local st_info csv"
dolt sql -q "create table if not exists ts_st_info (
    ts_code varchar(16),
    name varchar(64),
    tradedate date,
    type varchar(16),
    type_name varchar(32),
    symbol varchar(16),
    primary key(symbol, tradedate)
)" >/dev/null 2>&1 || echo "[WARN] create ts_st_info failed"
ST_DIR="$WORKING_DIR/investment_data/tushare/st_info"
if [ -d "$ST_DIR" ]; then
    # 增量导入（默认）：只导入比 master 表内已有最大交易日更新的 CSV，避免每天全量重导。
    #   首次/空表自动全量；需要强制全量重建时设 ST_FULL_IMPORT=1。
    # 合并成一个文件一次性 import，避免 2400+ 个逐文件 import（单次约 40 分钟）。
    MAX_DATE=0000-00-00
    if [ -z "${ST_FULL_IMPORT:-}" ]; then
        MAX_DATE=$(dolt sql -q "select ifnull(max(tradedate), '0000-00-00') from ts_st_info" -r csv | tail -1 | tr -d '\r')
    fi
    MERGED="$WORKING_DIR/investment_data/tushare/st_info_merged.csv"
    : > "$MERGED"
    header_done=0
    for f in "$ST_DIR"/*.csv; do
        [ -f "$f" ] || continue
        d=$(basename "$f" .csv)
        if [[ "$d" > "$MAX_DATE" ]]; then
            if [ "$header_done" -eq 0 ]; then
                cat "$f" > "$MERGED"
                header_done=1
            else
                tail -n +2 "$f" >> "$MERGED"
            fi
        fi
    done
    if [ "$header_done" -eq 1 ]; then
        dolt table import -u ts_st_info "$MERGED" >/dev/null 2>&1 || echo "[WARN] import failed: $MERGED"
        echo "[INFO] imported ST info newer than $MAX_DATE into ts_st_info"
    else
        echo "[INFO] no new ST info to import (table already has up to $MAX_DATE)"
    fi
    rm -f "$MERGED"
else
    echo "[WARN] $ST_DIR not found, is_st will be unknown"
fi
# ========================================================================

dolt sql-server &

# wait for sql server start
sleep 5s

cd $WORKING_DIR/investment_data
mkdir -p ./qlib/qlib_source
python3 ./qlib/dump_all_to_qlib_source.py --mode=${MODE}
OUTPUT_DIR=${OUTPUT_DIR:-/output}
export PYTHONPATH=$PYTHONPATH:$WORKING_DIR/qlib/scripts
cd ./qlib
python3 ./normalize.py normalize_data --source_dir ./qlib_source/ --normalize_dir ./qlib_normalize --max_workers=16 --date_field_name="tradedate" 

find ./qlib_normalize -type f -name '*-fi.csv' -delete

if [ "$FINANCE" = true ]; then
    cp -r /dolt/fundamental/* ./qlib_normalize
    echo "[INFO] Fundamental data copied to ./qlib_normalize and ready for dump_bin"
fi
python3 $WORKING_DIR/qlib/scripts/dump_bin.py dump_all --data_path ./qlib_normalize/ --qlib_dir ${OUTPUT_DIR}/qlib_bin --date_field_name=tradedate --exclude_fields=tradedate,symbol,end_date
    
mkdir -p ./qlib_index/
python3 ./dump_index_weight.py 

cd $WORKING_DIR/investment_data
python3 ./tushare/dump_day_calendar.py ${OUTPUT_DIR}/qlib_bin/
killall dolt

cp qlib/qlib_index/csi* ${OUTPUT_DIR}/qlib_bin/instruments/
#mv $WORKING_DIR/qlib_bin /output/
#mv $WORKING_DIR/qlib_fundamental /output/
#tar -czvf ./qlib_bin.tar.gz $WORKING_DIR/qlib_bin/
#tar -czvf ./qlib_fundamental.tar.gz $WORKING_DIR/qlib_fundamental
ls -lh ./qlib_bin.tar.gz
OUTPUT_DIR=${OUTPUT_DIR:-/output}
if [ -d "${OUTPUT_DIR}" ]; then
   # mv ./qlib_bin.tar.gz "${OUTPUT_DIR}/"
   # mv ./qlib_fundamental.tar.gz "${OUTPUT_DIR}/"
    ls -a "${OUTPUT_DIR}"
else
    echo "Generated tarball at $(pwd)/qlib_bin.tar.gz"
fi
