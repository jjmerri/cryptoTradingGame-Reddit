#!/usr/bin/env python3.6

# =============================================================================
# IMPORTS
# =============================================================================
import traceback
import praw
import re
import MySQLdb
import configparser
import logging
import time
import os
import sys
import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
from praw.exceptions import APIException, PRAWException
from threading import Thread
from enum import Enum

# =============================================================================
# GLOBALS
# =============================================================================

# Reads the config file
config = configparser.ConfigParser()
config.read("crypto_trading.cfg")

bot_username = config.get("Reddit", "username")
bot_password = config.get("Reddit", "password")
client_id = config.get("Reddit", "client_id")
client_secret = config.get("Reddit", "client_secret")

#Reddit info
reddit = praw.Reddit(client_id=client_id,
                     client_secret=client_secret,
                     password=bot_password,
                     user_agent='cryptoTradingGame by /u/BoyAndHisBlob',
                     username=bot_username)

DB_USER = config.get("SQL", "user")
DB_PASS = config.get("SQL", "passwd")

ENVIRONMENT = config.get("CRYPTOTRADING", "environment")

DEV_USER_NAME = config.get("CRYPTOTRADING", "dev_user")

RUNNING_FILE = "crypto_trading_processor.running"
CRYPTO_GAME_SUBREDDIT = "CryptoDayTradingGame"
SUPPORTED_COMMANDS = "!Market {{stuff}}"

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('cryptoTradingGameBot')
logger.setLevel(logging.INFO)

#Dictionary to store current crypto prices
current_price = {"XRP": 0.0}

supported_tickers = ["ADA","BCH","BCN","BTC","BTG","DASH","DOGE","ETC","ETH","LSK","LTC","NEO","QASH","QTUM","REQ",
                     "STEEM","XEM","XLM","XMR","XRB","XRP","ZEC"]

# =============================================================================
# CLASSES
# =============================================================================
class ParseMessageStatus(Enum):
    SUCCESS = 1
    SYNTAX_ERROR = 2
    UNSUPPORTED_TICKER = 3

class CommandType(Enum):
    NEW_GAME = 1
    UNKNOWN = 2

class DbConnection(object):
    """
    DB connection class
    """
    connection = None
    cursor = None

    def __init__(self):
        self.connection = MySQLdb.connect(
            host="localhost", user=DB_USER, passwd=DB_PASS, db="crypto_trading_game"
        )
        self.cursor = self.connection.cursor()

class MessageRequest(object):
    def __init__(self, message):
        self.message = message # Reddit message to process

    def process(self):
        command = self._get_command()

        if not self.message.was_comment:
            if command == CommandType.NEW_GAME:
                create_new_game(self.message)
            else: #Unknown command
                self.message.reply("I could not process your message because there were no valid commands found.")
        else:
            pass

    def _get_command(self):
        message_lower = self.message.body.lower()
        if "!newgame" in message_lower:
            return CommandType.NEW_GAME
        else:
            return CommandType.UNKNOWN
def create_new_game(message):
    """
    :param message: the message containing the new_game command
    :return: True if success False if not
    """
    game_length_modes = ["DAY","DAYS","MONTH","MONTHS"]
    command_regex = r'!newgame[ ]+(?P<game_length>[\d]+)[ ]+(?P<game_length_mode>[a-zA-Z]+)'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("game_length") and match.group("game_length_mode") in game_length_modes):
        game_length = int(match.group("game_length"))
        game_length_mode = match.group("game_length_mode").upper()
        start_datetime = datetime.today()
        if "DAY" in game_length_mode:
            end_datetime = start_datetime + relativedelta(days=+game_length)
        else:
            end_datetime = start_datetime + relativedelta(months=+game_length)

        reddit.subreddit(CRYPTO_GAME_SUBREDDIT).submit("Crypto Trading Game: {start_datetime} - {end_datetime}".format(
            start_datetime = start_datetime,
            end_datetime = end_datetime
        ),
        "Welcome to The Crypto Day Trading Game! "
        "The object of the game is to have the highest value portfolio before the game's end time {end_datetime}.\n\n"
        "The below commands are available to initiate trades and check on your portfolio. "
        "All price data is gathered from the CryptoCompare API using Bincance as the exchange.\n\n"
        "**Commands**\n\n{supported_commands}".format(
            end_datetime = end_datetime,
            supported_commands = SUPPORTED_COMMANDS
        ))
    else:
        message.reply("Could not parse new game command. The correct syntax is:\n\n"
                      "!NewGame {game_length_integer} {day | days | month | months}")
        return False



def process_pms():
    try:
        for message in reddit.inbox.unread(limit = 100):
            if not message.was_comment:
                message.mark_read()
                message_request = MessageRequest(message)
                message_request.process()
    except Exception as err:
        logger.error(traceback.format_exc())
        logger.error(err)
        logger.error("Unknown Exception in process_pms")

def create_running_file():
    running_file = open(RUNNING_FILE, "w")
    running_file.write(str(os.getpid()))
    running_file.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    start_process = False
    logger.info("start")

    if ENVIRONMENT == "DEV" and os.path.isfile(RUNNING_FILE):
        os.remove(RUNNING_FILE)
        logger.info("running file removed")

    if not os.path.isfile(RUNNING_FILE):
        create_running_file()
        start_process = True
    else:
        start_process = False
        logger.error("Search already running! Will not start.")

    while start_process and os.path.isfile(RUNNING_FILE):
        logger.info("Start Main Loop")
        try:
            process_pms()

            logger.info("End Main Loop")
        except Exception as err:
            logger.error(err)
            logger.error(traceback.format_exc())
            logger.error("Unknown Exception in Main Loop")

        time.sleep(30)

    sys.exit()
# =============================================================================
# RUNNER
# =============================================================================

if __name__ == '__main__':
    main()
