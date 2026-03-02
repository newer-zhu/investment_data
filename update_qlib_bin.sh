set -e
set -x
WORKING_DIR=${1}

QLIB_REPO=${2:-https://github.com/microsoft/qlib.git} 


MODE=${3:-incremental} 

START_DATE=${4:-$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)}

OUTPUT_QLIB=${5:-"./qlib_source"}
echo "[INFO] mode       = ${MODE}"
echo "[INFO] start_date = ${START_DATE}"
echo "[INFO] output_dir = ${OUTPUT_DIR}"

FINANCE=false

for arg in "$@"; do
    case "$arg" in
        --finance)
            FINANCE=true
            ;;
    esac
done

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
python3 ./qlib/dump_all_to_qlib_source_new.py --mode=${MODE} --start_date="${START_DATE}" --output_dir="${OUTPUT_QLIB}"

export PYTHONPATH=$PYTHONPATH:$WORKING_DIR/qlib/scripts
cd ./qlib
python3 ./normalize.py normalize_data --source_dir ${OUTPUT_QLIB} --normalize_dir ./qlib_normalize --max_workers=16 --date_field_name="tradedate" 
OUTPUT_DIR=${OUTPUT_DIR:-/output}
python3 $WORKING_DIR/qlib/scripts/dump_bin.py dump_update --data_path ./qlib_normalize/ --qlib_dir ${OUTPUT_DIR}/qlib_bin --date_field_name=tradedate --exclude_fields=tradedate,symbol
if $FINANCE; then
	python3 $WORKING_DIR/qlib/scripts/dump_bin.py dump_update \
    	--data_path $WORKING_DIR/fundamental \
    	--qlib_dir  /output/finance \
    	--date_field_name=date \
    	--exclude_fields=date,symbol,end_date
fi
    
mkdir -p ./qlib_index/
python3 ./dump_index_weight.py 

cd $WORKING_DIR/investment_data
python3 ./tushare/dump_day_calendar.py ${OUTPUT_DIR}/qlib_bin/
killall dolt

cp qlib/qlib_index/csi* ${OUTPUT_DIR}/qlib_bin/instruments/
#cp -r $WORKING_DIR/qlib_bin "${OUTPUT}/"
#cp -r $WORKING_DIR/qlib_fundmental "${OUTPUT}/finance" 
#tar -czvf ./qlib_bin.tar.gzbash update_qlib_bin.sh n/
#tar -czvf ./qlib_fundamental.tar.gz $WORKING_DIR/qlib_fundamental
#ls -lh ./qlib_bin.tar.gz
if [ -d "${OUTPUT_DIR}" ]; then
    #mv ./qlib_bin.tar.gz "${OUTPUT_DIR}/"
    #mv ./qlib_fundamental.tar.gz "${OUTPUT_DIR}/"
    ls -a "${OUTPUT_DIR}"
else
    echo "Generated tarball at $(pwd)/qlib_bin.tar.gz"
fi
