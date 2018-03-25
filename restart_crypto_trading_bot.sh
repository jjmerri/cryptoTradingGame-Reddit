#!/bin/bash
script_dir="/root/apps/cryptoTradingGame-Reddit/"
logs_dir="logs/"
running_file="crypto_trading_processor.running"

log_file="crypto_trading_processor.log"

cd $script_dir


pid=`cat $running_file`

rm $running_file

kill -0 $pid
kill_ret=$?

while [ $kill_ret -eq 0 ]
do
    echo "PIDs $pid still running. Sleep for 60 secs"
    sleep 60

    kill -0 $pid
    kill_ret=$?
done

echo "renaming logs"
mv $log_file $logs_dir$log_file.$(date +%F-%T)

echo "PIDs stopped. Starting scripts."

python3 -u "crypto_trading_processor.py" > $log_file 2>&1 &
pid=$!

echo "disowning $pid"
disown $pid

echo "complete"