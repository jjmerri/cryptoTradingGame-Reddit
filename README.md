
# Crypto Trading Game

## User Guide

#### What is the Crypto Trading Game

The Crypto Trading Game is simulated cryptocurrency trading using real market prices. Each game has its own Reddit post in /r/CryptoDayTradingGame and is given a duration.

### Commands

#### Market Order

**!Market {buy_amount} {buy_symbol} {sell_symbol}**

When a market order command is issued, the price at the time the comment was made is used to fill it

This example would buy 1000 XRP with available USD funds at the current market price:

>!Market 1000 XRP USD

This example will use all available BTC funds to buy ETH at the current market price:

>!Market 100% ETH BTC

#### Limit Order

**!Limit {buy_amount} {buy_symbol} {sell_symbol} {limit_price}**"

A limit order functions the same as a market order except you specify the price at which you want the trade executed and therefore it is not executed immediately. If the limit price is met your trade will be executed. When a limit order command is issued the funds required to make the trade at the limit price specified are made unavailable until the trade is filled or canceled.

This example sets a limit order that will buy 1000 XRP with available USD funds when the price of 1 XRP reaches .9 USD. This assumes the current price of 1 XRP is higher than .9 USD:

>!Limit 1000 XRP USD .9

This example sets a limit order that uses all available BTC funds to buy ETH when the price of 1 ETH reaches .075 BTC. This assumes the current price of 1 ETH is higher than .075 BTC:

>!Limit 100% ETH BTC .075

#### Cancel Limit Order

**!CancelLimit {order_id}**

When a cancel limit order command is issued the limit order identified by order_id will be canceled and the funds will become available again.

#### Portfolio Summary

**!Portfolio**

When a portfolio summary command is issued a reply will be made to your comment with a summary of your current portfolio.

## Technical Stuff

### Version Requirements

Python = 3.6.4

PRAW = 5.4

### Configuration

crypto_trading.cfg contains all usernames and passwords as well as environment specific configurations needed to run the Python scripts. When the environment is set to DEV some functionality is turned off in order to avoid processing real data. When the environment is set to DEV the .running files will be removed before startup. It is expected that your DEV database is different than your production database.

### External Dependencies

* [Reddit via PRAW](http://praw.readthedocs.io/en/latest/index.html) - The method of all the interactions with the users

* [CryptoCompare API](https://www.cryptocompare.com/api/) - Used to get price data

### schema.sql

This file contains the database schema. It is to be run only on database initialization to create the necessary objects. It drops the current database if it exists so it should never be run in production except on database creation.

### Database

A MySQL database with the following objects:

* game_submission - Stores info about a game submisson such as submission_id (Reddit ID) and game start/end time
* porfolio - Stores users' available currency amounts
* processed_comment - Stores comments that have been processed
* limit_order - Stores all limit orders and has in indicators to tell whether or not they have been canceled or executed.
* executed_trade - Stores all executed trades for auditability and troubleshooting. Not used for any processing.
* standings - Stores game standings. This is not used in processing and only exists for future functionality such as special flair for winners.

## Running crypto_trading_processor.py

Once you have your config file setup and python packages installed crypto_trading_processor.py should run without issue. Here are the high level steps you need to complete to fill out the config file.

* Create a Reddit account for the bot
* Create a Reddit script app under the bot account to get your app ID and secret
* Install and run a MySQL instance
* run schema.sql to create a database and tables
* Create a MySQL ID and grant SELECT, INSERT, UPDATE, and DELETE permissions to it in the new database
* Create a new subreddit where the bot will interact with users
* Make the Reddit bot ID a mod
* Create submission flair with the text 'In Progress'
* Create a submission flair that is editable
* Make sure your config file is named crypto_trading.cfg
