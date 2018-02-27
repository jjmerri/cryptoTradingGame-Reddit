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
    MARKET_ORDER = 2
    LIMIT_ORDER = 3
    UNKNOWN = 4

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
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)


class MessageRequest(object):
    def __init__(self, message):
        self.message = message # Reddit message to process

    def process(self):
        if self.message.author is None: #could be deleted comment
            add_to_processed(self.message.parent().id, self.message.id, self.message.body)
            return

        processed = False;
        command = self._get_command()

        if command == CommandType.NEW_GAME and self.message.author.name == DEV_USER_NAME:
            create_new_game(self.message)
        elif command == CommandType.MARKET_ORDER:
            initialize_portfolio(self.message.parent().id, self.message.author.name)
            processed = process_market_order(self.message)
        elif command == CommandType.LIMIT_ORDER:
            initialize_portfolio(self.message.parent().id, self.message.author.name)
            processed = process_limit_order(self.message)
        else: #Unknown command
            self.message.reply("I could not process your message because there were no valid commands found.")

        if processed:
            add_to_processed(self.message.parent().id, self.message.id, self.message.body)
        else:
            send_dev_pm("Crypto Trading Game: Could Not Process Message",
                        "Could not process message: {message}".format(message = str(self.message)))

    def _get_command(self):
        message_lower = self.message.body.lower()
        if "!newgame" in message_lower:
            return CommandType.NEW_GAME
        elif "!market" in message_lower:
            return CommandType.MARKET_ORDER
        elif "!limit" in message_lower:
            return CommandType.LIMIT_ORDER
        else:
            return CommandType.UNKNOWN

def add_to_processed(submission_id, comment_id, body):
    """
    Adds the comment_id to the list of submitted comments
    :param submission_id: the id of the game
    :param comment_id: the id of the comment
    :param body: the body of the comment
    :return:
    """
    db_connection = DbConnection()
    query = "SELECT game_id FROM game_submission WHERE game_submission.submission_id = %s"
    db_connection.cursor.execute(query, [submission_id])
    game_id = db_connection.cursor.fetchall()[0]["game_id"]

    query = "INSERT INTO processed_comment (game_id, comment_id, comment_body) VALUES (%s, %s, %s)"
    db_connection.cursor.execute(query, [game_id, comment_id, body])

    db_connection.connection.commit()
    db_connection.connection.close()

def send_dev_pm(subject, body):
    """
    Sends Reddit PM to DEV_USER_NAME
    :param subject: subject of PM
    :param body: body of PM
    """
    reddit.redditor(DEV_USER_NAME).message(subject, body)

def create_new_game(message):
    """
    :param message: the message containing the new_game command
    :return: True if success False if not
    """
    game_length_modes = ["DAY","DAYS","MONTH","MONTHS"]
    command_regex = r'!newgame[ ]+(?P<game_length>[\d]+)[ ]+(?P<game_length_mode>[a-zA-Z]+)'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("game_length") and match.group("game_length_mode")
        and match.group("game_length_mode").upper()in game_length_modes):
        db_connection = DbConnection()
        game_length = int(match.group("game_length"))
        game_length_mode = match.group("game_length_mode").upper()
        begin_datetime = datetime.today()
        if "DAY" in game_length_mode:
            end_datetime = begin_datetime + relativedelta(days=+game_length)
        else:
            end_datetime = begin_datetime + relativedelta(months=+game_length)

        submission = reddit.subreddit(CRYPTO_GAME_SUBREDDIT).submit("Crypto Trading Game: {start_datetime} - {end_datetime}".format(
            start_datetime = begin_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            end_datetime = end_datetime.strftime("%Y-%m-%d %H:%M:%S")
        ),
        "Welcome to The Crypto Day Trading Game! "
        "The object of the game is to have the highest value portfolio before the game's end time "
        "[{end_datetime} UTC](http://www.wolframalpha.com/input/?i={end_datetime} UTC To Local Time). "
        "Everyone starts the game with $10,000 USD to trade as they wish. Current prices and standings will be updated here.\n\n"
        "All price data is gathered from the CryptoCompare API using the CryptoCompare Current Aggregate (CCCAG)."
        "The below commands are available to initiate trades and check on your portfolio.\n\n"
        "**Commands**\n\n{supported_commands}".format(
            end_datetime = end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            supported_commands = SUPPORTED_COMMANDS
        ))

        cmd = "INSERT INTO game_submission (subreddit, submission_id, author, game_begin_datetime, game_end_datetime) VALUES (%s, %s, %s, %s, %s)"
        db_connection.cursor.execute(cmd, (submission.subreddit.display_name,
                                           submission.id,
                                           submission.author.name,
                                           str(begin_datetime),
                                           str(end_datetime)))
        db_connection.connection.commit()
        db_connection.connection.close()

        return True
    else:
        message.reply("Could not parse new game command. The correct syntax is:\n\n"
                      "!NewGame {game_length_integer} {day | days | month | months}")
        return False

def process_market_order(message):
    """
    :param message: the message containing the market order command
    :return: True if success False if not
    """
    command_regex = r'^!market[ ]+\$?(?P<quantity>([\d]+(\.\d+)?%?))[ ]+(?P<buy_currency>[0-9a-zA-Z]+)[ ]+(?P<sell_currency>[0-9a-zA-Z]+)$'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("quantity") and match.group("buy_currency") and match.group("sell_currency")):
        args_invalid = False
        quantity_is_percent = False
        db_connection = DbConnection()
        quantity_str = match.group("quantity")
        buy_currency = match.group("buy_currency").upper()
        sell_currency = match.group("sell_currency").upper()

        if "%" in quantity_str:
            quantity_str = quantity_str.replace("%","")
            quantity_is_percent = True

        quantity_float = float(quantity_str)

        if (quantity_float <= 0 or (quantity_float > 100 and quantity_is_percent)):
            args_invalid = True

        trading_price = get_trading_price(buy_currency, sell_currency, message.created_utc)

        portfolio_sell_currency = get_portfolio(message.parent().id, message.author.name, sell_currency)

        available_funds = 0
        trade_cost = 0
        quantity_bought = 0

        if portfolio_sell_currency:
            available_funds = float(portfolio_sell_currency[0]["amount"])

        if quantity_is_percent:
            trade_cost = (quantity_float / 100) * available_funds
            quantity_bought = trade_cost / trading_price
        else:
            trade_cost = quantity_float * trading_price
            quantity_bought = quantity_float

        if args_invalid:
            message.reply("Error processesing your request: Quantities must be greater than 0 and percentages cannot exceed 100%")
            return False
        elif trading_price <= 0:
            message.reply("Error processesing your request: The provided currency pair may be unsupported or the CryptoCompare API could be down. "
                          "If it is not listed [here](https://www.cryptocompare.com/api/data/coinlist/) then it is not supported.\n\n"
                          "Please see the [README](https://github.com/jjmerri/cryptoTradingGame-Reddit) for more info.")
            return False
        elif available_funds < trade_cost:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Error processesing your request: You have insufficient funds to make that trade. "
                          "Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))
            return False
        else:
            execute_trade(quantity_bought, buy_currency, available_funds - trade_cost, sell_currency)
            message.reply("Trade Executed")

            return True
    else:
        message.reply("Could not parse market order command. The correct syntax is:\n\n"
                      "!Market {quantity_to_buy | percentage_of_sell_currency} {symbol_to_buy} {symbol_to_sell}\n\n"
                      "Examples:\n\n"
                      "To buy 1000 XRP with USD - !Market 1000 XRP USD"
                      "To spend 50% of your available USD on XRP - !Market 50% XRP USD")
        return False


def process_limit_order(message):
    """
    :param message: the message containing the limit order command
    :return: True if success False if not
    """
    pass

def get_trading_price(from_symbol, to_symbol, price_time):
    """

    :param from_symbol: symbol we want the price of
    :param to_symbol: symbol we want the price in
    :param price_time: point in time to get the price. If elapsed time is < 60 seconds the current price is returned
    :return:
    """
    api_url = ("https://min-api.cryptocompare.com/data/price?"
               "fsym={from_symbol}&"
               "tsyms={to_symbol}&"
               "extraParams=reddit_trading_game".format(
        from_symbol = from_symbol,
        to_symbol = to_symbol
    ))

    use_history_api = False

    elapsed_time_sec = time.time() - price_time
    if elapsed_time_sec > 60:
        use_history_api = True

    if use_history_api:
        api_url = ("https://min-api.cryptocompare.com/data/histominute?"
                   "fsym={from_symbol}&"
                   "tsym={to_symbol}&"
                   "toTs={price_time}&"
                   "e=CCCAGG&"
                   "limit=1&"
                   "extraParams=reddit_trading_game".format(
            from_symbol=from_symbol,
            to_symbol=to_symbol,
            price_time = price_time
        ))

    response = {}
    api_error_count = 0

    # Loop to retry getting API data. Will break on success or 10 consecutive errors
    while True:
        r = requests.get(api_url)
        response = r.json()

        # If not success then retry up to 10 times after 1 sec wait
        if ((use_history_api and response.get("Response", "Error") != "Success") or
            (not use_history_api and to_symbol not in response)):
            api_error_count += 1
            logger.error("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                     error_count=api_error_count))
            time.sleep(1)
            if api_error_count >= 10 or (not use_history_api and response.get("Message", "Error") in "There is no data for any of the toSymbols"):
                send_dev_pm("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                               error_count=api_error_count))
                return -1
        else:
            break

    if use_history_api and "Data" in response and response["Data"]:
        for minute_data in response["Data"]:
            if price_time - minute_data["time"] < 60:
                return minute_data["close"]
    elif not use_history_api and to_symbol in response:
        return response[to_symbol]
    else:
        return -2

    return -3


def execute_trade(buy_quantity, buy_currency, sell_quantity, sell_currency):
    """
    Executes the trade as an atomic function
    :param buy_quantity: amount of buy_currency bought
    :param buy_currency: the currency that was bought
    :param sell_quantity: amount of sell_currency sold
    :param sell_currency: the currency that was sold
    :return: success or failure
    """
    pass

def initialize_portfolio(submission_id, username):
    """
    If the portfolio is empty for the user in the given game then give them USD to start the game
    :param game_id: The game the portfolio belongs to
    :param username: username the portfolio belongs to
    """

    portfolio = get_portfolio(submission_id, username)

    if not portfolio:
        db_connection = DbConnection()
        query = "SELECT game_id FROM game_submission WHERE game_submission.submission_id = %s"
        db_connection.cursor.execute(query, [submission_id])
        game_id = db_connection.cursor.fetchall()[0]["game_id"]

        query = "INSERT INTO portfolio (game_id, owner, currency, amount) VALUES (%s, %s, %s, %s)"
        db_connection.cursor.execute(query, [game_id, username, "USD", 10000])

        db_connection.connection.commit()
        db_connection.connection.close()

def get_portfolio(submission_id, username, currency = None):
    """
    :param submission_id: The game the portfolio belongs to
    :param username: username the portfolio belongs to
    :param currency: None if you want everything or specify the currency you want info for
    :return: If currency is None return the entire portfolio otherwise get only the currency specified
    """
    currency_clause = ""
    query_args = [submission_id, username]
    if currency is not None:
        currency_clause = " AND portfolio.currency = %s"
        query_args.append(currency)

    db_connection = DbConnection()
    query = ("SELECT * FROM portfolio "
             "JOIN game_submission ON game_submission.game_id = portfolio.game_id "
             "WHERE game_submission.submission_id = %s AND portfolio.owner = %s{currency_clause} "
             "ORDER BY currency ASC".format(
        currency_clause = currency_clause
    ))
    db_connection.cursor.execute(query, query_args)
    portfolio = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return portfolio

def get_currencies(submission_id, username = None):
    """
    :param submission_id: The game the portfolio belongs to
    :param username: username the portfolio belongs to
    :return: If username is None return all the currencies being used
    """
    username_clause = ""
    query_args = [submission_id]
    if username is not None:
        username_clause = " AND portfolio.owner = %s"
        query_args.append(username)

    db_connection = DbConnection()
    query = ("SELECT DISTINCT currency FROM portfolio "
             "JOIN game_submission ON game_submission.game_id = portfolio.game_id "
             "WHERE game_submission.submission_id = %s{username_clause} "
             "ORDER BY currency ASC".format(
            username_clause=username_clause
    ))
    db_connection.cursor.execute(query, query_args)
    currencies = db_connection.cursor.fetchall()
    db_connection.connection.close()

    currency_list = []
    for currency in currencies:
        currency_list.append(currency["currency"])

    return currency_list

def get_portfolio_summary(submission_id, username):
    portfolio = get_portfolio(submission_id, username)

    if portfolio:
        header = ("Currency | Amount | Value (USD)\n"
                  "---|---|----\n")
        body = ""

        currencies = get_currencies(submission_id, username)
        usd_value = get_currencies_usd_value(currencies)

        for portfolio_currency in portfolio:
            currency = portfolio_currency["currency"]
            amount = portfolio_currency["amount"]
            if currency in usd_value:
                currency_value = amount * usd_value[currency]["USD"]
                body = currency + "|" + str(amount) + "|" + '${:,.2f}'.format(currency_value)

        return header + body
    else:
        logger.error("Something might be wrong with {username}'s portfolio for game {submission_id}. "
                     "They have no portfolio for the given game!".format(username = username,
                                                                         submission_id = submission_id))
        return ""

def get_currencies_usd_value(currencies):
    """
    :param currencies: the currencies to get the USD value for
    :return: dictionary containing currency USD values
    """
    api_url = "https://min-api.cryptocompare.com/data/pricemulti?fsyms={currencies}&tsyms=USD".format(
        currencies = ",".join(currencies)
    )


    response = {}
    api_error_count = 0

    # Loop to retry getting API data. Will break on success or 10 consecutive errors
    while True:
        r = requests.get(api_url)
        response = r.json()

        # If not success then retry up to 10 times after 1 sec wait
        if (currencies[0] not in response):
            api_error_count += 1
            logger.error("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                     error_count=api_error_count))
            time.sleep(1)
            if api_error_count >= 10:
                send_dev_pm("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                               error_count=api_error_count))
                return {}
        else:
            break

    return response

def get_current_games():
    """
    Retreive all active games from the DB
    :return: returns tuple of submission_ids for all active games
    """
    current_datetime = datetime.today()
    db_connection = DbConnection()
    query = "SELECT submission_id FROM game_submission WHERE game_begin_datetime <= %s AND game_end_datetime >= %s ORDER BY game_begin_datetime"
    db_connection.cursor.execute(query,[current_datetime,current_datetime])
    current_games = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return current_games


def get_processed_comments(game_id):
    """
    Retreive all comments that have been already processed for the given game_id
    :param game_id: submission id for the game you want to retreive processed comments for
    :return: returns a tuple of comment ids that have been processed for the given game_id
    """
    db_connection = DbConnection()
    query = ("SELECT comment_id FROM processed_comment "
             "JOIN game_submission ON game_submission.game_id = processed_comment.game_id "
             "WHERE game_submission.submission_id = %s")
    db_connection.cursor.execute(query,[game_id])
    processed_comments = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return processed_comments

def process_game_messages():
    try:
        current_games = get_current_games()
        for current_game in current_games:
            current_game_id = current_game["submission_id"]
            unprocessed_comments = get_unprocessed_comments(current_game_id)
            for unprocessed_comment in unprocessed_comments:
                message_request = MessageRequest(unprocessed_comment)
                message_request.process()
    except Exception as err:
        logger.exception("Unknown Exception in process_game_messages")

def get_unprocessed_comments(game_id):
    submission = reddit.submission(id = game_id)
    submission.comment_sort = 'old'
    top_level_comments = list(submission.comments)

    processed_comments = get_processed_comments(game_id)
    unprocessed_comments = []

    for top_level_comment in top_level_comments:
        comment_processed = False
        for processed_comment in processed_comments:
            if top_level_comment.id == processed_comment["comment_id"]:
                comment_processed = True
                break
        if not comment_processed:
            unprocessed_comments.append(top_level_comment)

    return unprocessed_comments


def process_pms():
    try:
        for message in reddit.inbox.unread(limit = 100):
            message.mark_read()
            if not message.was_comment:
                message_request = MessageRequest(message)
                message_request.process()
    except Exception as err:
        logger.exception("Unknown Exception in process_pms")

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
        logger.error("crypto processor already running! Will not start.")

    while start_process and os.path.isfile(RUNNING_FILE):
        logger.info("Start Main Loop")
        try:
            process_pms()
            process_game_messages()

            logger.info("End Main Loop")
        except Exception as err:
            logger.exception("Unknown Exception in Main Loop")

        time.sleep(30)

    sys.exit()
# =============================================================================
# RUNNER
# =============================================================================

if __name__ == '__main__':
    main()
