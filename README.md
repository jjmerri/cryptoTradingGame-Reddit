# Crypto Trading Game

## User Guide

#### What is the Crypto Trading Game

The Crypto Trading Game is simulated cryptocurrency trading using real market prices. Each game has its own Reddit post in /r/CryptoDayTradingGame and is given a duration.

## Technical Stuff

#### Version Requirements

Python = 3.6.4

PRAW = 5.4

#### Configuration

remindmebot.cfg contains all usernames and passwords as well as environment specific configurations needed to run the Python scripts. When the environment is set to DEV some functionality is turned off in order to avoid processing real data. When the environment is set to DEV the .running files will be removed before startup. It is expected that your DEV database is different than your production database.

#### External Dependencies

* [Reddit via PRAW](http://praw.readthedocs.io/en/latest/index.html) - The method of all the interactions with the users

* [CryptoCompare API](https://www.cryptocompare.com/api/) - Used to get price data

#### lastrun files

These files are updated by the Python scripts to persist timestamps of when processes are run. This allows the bots to pick up where they left off chronologically in the event of a restart. The timestamps are used to retrieve price data as well as unprocessed comments. The information in these files will eventually be moved to a table in the database.

#### schema.sql

This file contains the database schema. It is to be run only on database initialization to create the necessary objects. It drops the current database if it exists so it should never be run in production except on database creation.

#### Database

A MySql database with the following objects:

* Tables
