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

# ============ ST 名单（is_st）更新 —— 失败安全，绝不影响量价 bin ============
# ST 名单来自 tushare stock_st，增量写入 /output/st_info 供宿主机读取过滤 ST。
# 放在 bin 生成之后：接口/token 到期或不可达时最多 30 分钟即放弃，只影响 is_st，不阻塞 bin。
# 注意：token 暂写死兜底（env TUSHARE 优先）；到期失效时此块仅 WARN，不影响量价 bin。
echo "Updating ST info -> /output/st_info"
TUSHARE=${TUSHARE:-5c3e03a90607d36bd6371659d57b337cb549cf2a76f590100373559a0ce3}
LAST=$(ls /output/st_info/ 2>/dev/null | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.csv$' | sort | tail -1 | sed 's/\.csv$//; s/-//g')
START=${LAST:-20160801}
echo "[INFO] fetch ST info from $START"
if ! timeout 1800 python3 "$WORKING_DIR/investment_data/tushare/dump_st_info.py" --start_date="$START"; then
    echo "[WARN] ST info update failed/skipped (is_st), continuing"
fi
# ========================================================================

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
