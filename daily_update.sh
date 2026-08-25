set -e
set -x

[ ! -d "/dolt/investment_data" ] && echo "initializing dolt repo" && cd /dolt && dolt clone chenditc/investment_data
cd /dolt/investment_data
# 主流程始终在 master 分支（ST 功能在 feature/is_st 分支，不影响 master）
dolt checkout master
dolt fetch origin master
dolt reset origin/master
dolt checkout .

# ============ ST 信息（is_st）更新 —— 失败安全，不影响既有流程 ============
# update_st_info.sh 内部会切到 dolt feature/is_st 分支，失败或成功后都回到 master。
# 即便这里失败，也不影响下面的 index weight / price / stock price 等既有更新。
echo "Updating ST info (is_st)"
if ! bash /investment_data/update_st_info.sh; then
    echo "[WARN] ST info (is_st) update failed, continuing with existing flow"
fi
# ========================================================================

echo "Updating index weight"
startdate=$(dolt sql -q "select * from max_index_date" -r csv | tail -1)
python3 /investment_data/tushare/dump_index_weight.py --start_date=$startdate
for file in $(ls /investment_data/tushare/index_weight/); 
do  
  dolt table import -u ts_index_weight /investment_data/tushare/index_weight/$file; 
done

echo "Updating index price"
python3 /investment_data/tushare/dump_index_eod_price.py 
for file in $(ls /investment_data/tushare/index/); 
do   
  dolt table import -u ts_a_stock_eod_price /investment_data/tushare/index/$file; 
done

echo "Updating stock price"
dolt sql-server &
sleep 5 && python3 /investment_data/tushare/update_a_stock_eod_price_to_latest.py
killall dolt

dolt sql --file /investment_data/tushare/regular_update.sql

dolt add -A

status_output=$(dolt status)

# Check if the status output contains the "nothing to commit, working tree clean" message
if [[ $status_output == *"nothing to commit, working tree clean"* ]]; then
    echo "No changes to commit. Working tree is clean."
else
    echo "Changes found. Committing and pushing..."
    # Run the necessary commands
    #dolt commit -m "Daily update"
    #dolt push --force origin master
    echo "Changes committed and pushed."
fi

