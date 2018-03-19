#!/usr/bin/env python3.6

# =============================================================================
# IMPORTS
# =============================================================================
import traceback
import praw
import operator
import re
import MySQLdb
import calendar
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
SUPPORTED_COMMANDS = ("!Market {buy_amount} {buy_symbol} {sell_symbol}\n\n"
                      "!Limit {buy_amount} {buy_symbol} {sell_symbol} {limit_price}\n\n"
                      "!CancelLimit {order_id}\n\n"
                      "!Portfolio\n\n"
                      "See the [README](https://github.com/jjmerri/cryptoTradingGame-Reddit) for more info on commands.")

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('cryptoTradingGameBot')
logger.setLevel(logging.INFO)

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
    PORTFOLIO = 5
    CANCEL_LIMIT_ORDER = 6

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
    _errored_requests = []

    def __init__(self, message):
        self.message = message # Reddit message to process

    def process(self):
        try:
            if self.message.author is None: #could be deleted comment
                add_to_processed(self.message.parent().id, self.message.id, self.message.body)
                return

            processed = False
            command = self._get_command()

            if command == CommandType.NEW_GAME and self.message.author.name == DEV_USER_NAME:
                create_new_game(self.message)
                processed = True
            elif command == CommandType.MARKET_ORDER:
                initialize_portfolio(self.message.parent().id, self.message.author.name)
                processed = process_market_order_command(self.message)
            elif command == CommandType.LIMIT_ORDER:
                initialize_portfolio(self.message.parent().id, self.message.author.name)
                processed = process_limit_order_command(self.message)
            elif command == CommandType.CANCEL_LIMIT_ORDER:
                initialize_portfolio(self.message.parent().id, self.message.author.name)
                processed = process_cancel_limit_order_command(self.message)
            elif command == CommandType.PORTFOLIO:
                initialize_portfolio(self.message.parent().id, self.message.author.name)
                portfolio_summary = get_portfolio_summary(self.message.parent().id, self.message.author.name)
                self.message.reply("Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))
                processed = True
            else: #Unknown command
                self.message.reply("I could not process your message because there were no valid commands found.")
                processed = True

            if processed:
                if self.message.parent_id is not None:
                    add_to_processed(self.message.parent().id, self.message.id, self.message.body)
            else:
                #Prevent sending the dev more than 1 PM for the same message
                if self.message.id not in MessageRequest._errored_requests:
                    MessageRequest._errored_requests.append(self.message.id)
                    send_dev_pm("Crypto Trading Game: Could Not Process Message",
                                "Could not   process message: {message}".format(message = str(self.message)))
        except Exception as err:
            #Prevent sending the dev more than 1 PM for the same message
            if self.message.id not in MessageRequest._errored_requests:
                logger.exception("Error in process for {message}".format(message = str(self.message)))
                send_dev_pm("Crypto Trading Game: Could Not Process Message",
                            "Unknown exception occured while processing message: {message}".format(message = str(self.message)))
                MessageRequest._errored_requests.append(self.message.id)

    def _get_command(self):
        message_lower = self.message.body.lower()
        if "!newgame" in message_lower:
            return CommandType.NEW_GAME
        elif "!market" in message_lower:
            return CommandType.MARKET_ORDER
        elif "!limit" in message_lower:
            return CommandType.LIMIT_ORDER
        elif "!cancellimit" in message_lower:
            return CommandType.CANCEL_LIMIT_ORDER
        elif "!portfolio" in message_lower:
            return CommandType.PORTFOLIO
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
        begin_datetime = datetime.utcnow()
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
        "All price data is gathered from the CryptoCompare API using the CryptoCompare Current Aggregate (CCCAG). "
        "The below commands are available to initiate trades and check on your portfolio.\n\n"
        "**Commands**\n\n{supported_commands}".format(
            end_datetime = end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            supported_commands = SUPPORTED_COMMANDS
        ))

        cmd = ("INSERT INTO game_submission (subreddit, submission_id, author, game_begin_datetime, game_end_datetime, complete) " 
               "VALUES (%s, %s, %s, %s, %s, %s)")
        db_connection.cursor.execute(cmd, (submission.subreddit.display_name,
                                           submission.id,
                                           submission.author.name,
                                           str(begin_datetime),
                                           str(end_datetime),
                                           False))
        db_connection.connection.commit()
        db_connection.connection.close()

        return True
    else:
        message.reply("Could not parse new game command. The correct syntax is:\n\n"
                      "!NewGame {game_length_integer} {day | days | month | months}")
        return False

def process_market_order_command(message):
    """
    :param message: the message containing the market order command
    :return: True if success False if not
    """
    command_regex = r'^!market[ ]+\$?(?P<quantity>(([\d]+)?(\.\d+)?%?))[ ]+(?P<buy_currency>[0-9a-zA-Z]+)[ ]+(?P<sell_currency>[0-9a-zA-Z]+)$'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("quantity") and match.group("buy_currency") and match.group("sell_currency")):
        args_invalid = False
        quantity_is_percent = False
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
        elif trading_price <= 0:
            message.reply("Error processesing your request: The provided currency pair may be unsupported or the CryptoCompare API could be down. "
                          "If it is not listed [here](https://www.cryptocompare.com/api/data/coinlist/) then it is not supported. "
                          "If it is listed please try again later.\n\n"
                          "Please see the [README](https://github.com/jjmerri/cryptoTradingGame-Reddit) for more info.")
        elif available_funds < trade_cost or available_funds == 0:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Error processesing your request: You have insufficient funds to make that trade. "
                          "Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))
        else:
            trade_executed = execute_trade(message.id, message.author.name, quantity_bought, buy_currency, trade_cost, sell_currency, False, submission_id = message.parent().id)
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)

            if trade_executed:
                message.reply("Trade Executed! Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))
            else:
                logger.error("Error executing market order for comment_id: {message_id}".format(message_id = message.id))

        return True
    else:
        message.reply("Could not parse market order command. The correct syntax is:\n\n"
                      "!Market {quantity_to_buy | percentage_of_sell_currency} {symbol_to_buy} {symbol_to_sell}\n\n"
                      "Examples:\n\n"
                      "To buy 1000 XRP with USD:\n\n"
                      "!Market 1000 XRP USD\n\n"
                      "To spend 50% of your available USD on XRP\n\n"
                      "!Market 50% XRP USD")
        return True


def process_limit_order_command(message):
    """
    :param message: the message containing the limit order command
    :return: True if success False if not
    """
    command_regex = r'^!limit[ ]+\$?(?P<quantity>(([\d]+)?(\.\d+)?%?))[ ]+(?P<buy_currency>[0-9a-zA-Z]+)[ ]+(?P<sell_currency>[0-9a-zA-Z]+)[ ]+(?P<limit_price>(([\d]+)?(\.\d+)?))$'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("quantity") and match.group("buy_currency") and match.group("sell_currency") and match.group("limit_price")):
        args_invalid = False
        quantity_is_percent = False
        quantity_str = match.group("quantity")
        buy_currency = match.group("buy_currency").upper()
        sell_currency = match.group("sell_currency").upper()
        limit_price = float(match.group("limit_price"))

        if "%" in quantity_str:
            quantity_str = quantity_str.replace("%","")
            quantity_is_percent = True

        quantity_float = float(quantity_str)

        if (quantity_float <= 0 or (quantity_float > 100 and quantity_is_percent)):
            args_invalid = True

        portfolio_sell_currency = get_portfolio(message.parent().id, message.author.name, sell_currency)

        available_funds = 0
        trade_cost = 0
        quantity_bought = 0

        current_price = get_trading_price(buy_currency, sell_currency, message.created_utc)

        if portfolio_sell_currency:
            available_funds = float(portfolio_sell_currency[0]["amount"])

        if quantity_is_percent:
            trade_cost = (quantity_float / 100) * available_funds
            quantity_bought = trade_cost / limit_price
        else:
            trade_cost = quantity_float * limit_price
            quantity_bought = quantity_float

        if args_invalid:
            message.reply("Error processesing your request: Quantities must be greater than 0 and percentages cannot exceed 100%")
        elif current_price < limit_price:
            message.reply(
                "**Error:** Limit order not created! "
                "The price you specified for the limit order is higher than the current price of {current_price}. "
                "It would have been cheaper to make a market order.\n\n"
                "You tried to issue a command to buy {buy_currency} with {sell_currency} when 1 {buy_currency} became worth {limit_price} {sell_currency}. "
                "If you meant to issue a command to buy {buy_currency} with {sell_currency} "
                "when 1 {sell_currency} became worth {limit_price} {buy_currency} you can use the following command:\n\n"
                "**!limit {quantity_str} {buy_currency} {sell_currency} {inverted_ratio}**\n\n"
                "If you want to make a purchase at the market price use the !Market command.".format(
                    current_price = str(current_price),
                    buy_currency = buy_currency,
                    sell_currency = sell_currency,
                    limit_price = str(limit_price),
                    quantity_str = quantity_str + ("%" if quantity_is_percent else ""),
                    inverted_ratio = '{:,.6g}'.format(1/limit_price)
                ))
        elif available_funds < trade_cost or available_funds == 0:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Error processesing your request: You have insufficient funds to create that limit order! "
                          "Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))
        else:
            create_limit_order(message.parent().id, message.id, message.author.name, quantity_bought, buy_currency, available_funds, trade_cost, sell_currency, limit_price)
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Limit order created! Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary = portfolio_summary
                            ))

        return True
    else:
        message.reply("Could not parse limit order command. The correct syntax is:\n\n"
                      "!Limit {quantity_to_buy | percentage_of_sell_currency} {symbol_to_buy} {symbol_to_sell} {limit_price}\n\n"
                      "Examples:\n\n"
                      "To buy 1000 XRP with USD when the price of 1 XRP reaches .9 USD:\n\n"
                      "!Limit 1000 XRP USD .9\n\n"
                      "To spend 50% of your available USD on XRP when the price of 1 XRP reaches .9 USD\n\n"
                      "!Limit 50% XRP USD .9")
        return True

def process_cancel_limit_order_command(message):
    """
    :param message: the message containing the cancel limit order command
    :return: True if success False if not
    """
    command_regex = r'^!cancellimit[ ]+(?P<limit_order_id>[\d]+)$'
    match = re.search(command_regex, message.body, re.IGNORECASE)

    if (match and match.group("limit_order_id")):
        args_invalid = False
        limit_order_id = int(match.group("limit_order_id"))

        limit_order_cancelled = cancel_limit_order(limit_order_id, message.author.name)

        if limit_order_cancelled:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply(
                "Limit order canceled! Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                    portfolio_summary=portfolio_summary
                ))
        else:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Could not cancel the limit order specified. "
                          "If you are sure you are the owner of that limit order and it hasnt already been executed or canceled please try again later. "
                          "Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                            portfolio_summary=portfolio_summary
                            ))
        return True


    else:
        message.reply("Could not parse cancel limit order command. The correct syntax is:\n\n"
                      "!CancelLimit {limit_order_id}\n\n"
                      "Example:\n\n"
                      "To cancel the limit order with ID 77:\n\n"
                      "!CancelLimit 77")
        return True

def get_trading_price(from_symbol, to_symbol, price_time):
    """
    :param from_symbol: symbol we want the price of
    :param to_symbol: symbol we want the price in
    :param price_time: point in time to get the price. If elapsed time is < 60 seconds the current price is returned
    :return:
    """
    try:
        api_url = "https://min-api.cryptocompare.com/data/pricemulti?fsyms={from_symbol}&tsyms={to_symbol}".format(
            from_symbol = from_symbol,
            to_symbol = to_symbol
        )

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
                (not use_history_api and from_symbol not in response)):
                api_error_count += 1
                logger.error("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                         error_count=api_error_count))
                time.sleep(1)
                if api_error_count >= 10 or (not use_history_api and response.get("Message", "Error") in "There is no data for any of the toSymbols"):
                    send_dev_pm("API Error Getting Price", "Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                                   error_count=api_error_count))
                    return -1
            else:
                break

        if use_history_api and "Data" in response and response["Data"]:
            for minute_data in response["Data"]:
                if price_time - minute_data["time"] < 60:
                    return minute_data["close"]
        elif not use_history_api and from_symbol in response:
            return response[from_symbol][to_symbol]
        else:
            return -2

        return -3

    except Exception as err:
        trading_price = -4
        logger.exception("Unknown Exception getting the trading price")

def get_game_id(submission_id):
    """
    Returns the game_id associated with submission_id
    :param submission_id: the submission_id of the game
    :return: Returns the game_id associated with submission_id
    """
    db_connection = DbConnection()
    query = "SELECT game_id FROM game_submission WHERE game_submission.submission_id = %s"
    db_connection.cursor.execute(query, [submission_id])
    game_id = db_connection.cursor.fetchall()[0]["game_id"]
    db_connection.connection.close()

    return game_id

def get_submission_id(game_id):
    """
    Returns the game_id associated with submission_id
    :param submission_id: the submission_id of the game
    :return: Returns the game_id associated with submission_id
    """
    db_connection = DbConnection()
    query = "SELECT submission_id FROM game_submission WHERE game_submission.game_id = %s"
    db_connection.cursor.execute(query, [game_id])
    submission_id = db_connection.cursor.fetchall()[0]["submission_id"]
    db_connection.connection.close()

    return submission_id

def execute_trade(comment_id, username, buy_quantity, buy_currency, trade_cost, sell_currency, is_limit_order, submission_id = None, game_id = None):
    """
    Executes the trade as an atomic function by updating the portfolio and adding the trade to the executed_trade table
    :param submission_id: id of the game the request is for
    :param comment_id: id of the comment that contains the request
    :param username: user that requested the trade
    :param buy_quantity: amount of buy_currency bought
    :param buy_currency: the currency that was bought
    :param trade_cost: amount of sell_currency it cost to buy the amount of buy_currency
    :param sell_currency: the currency that was sold
    :return: success or failure
    """
    if submission_id is None and game_id is None:
        logger.error("execute_trade did not provide submission_id or game_id! Cannot execute trade.")
        return False
    elif game_id is None:
        game_id = get_game_id(submission_id)
    elif submission_id is None:
        submission_id = get_submission_id(game_id)

    available_funds = 0
    portfolio_sell_currency = get_portfolio(submission_id, username, sell_currency)
    if portfolio_sell_currency:
        available_funds = float(portfolio_sell_currency[0]["amount"])
    else:
        return False

    #If it is a limit order the funds were already subtracted from the portfolio so add the funds back to make the trade
    if is_limit_order:
        available_funds += float(trade_cost)

    if available_funds < trade_cost:
        logger.error("Insufficient funds to complete trade with comment_id: {comment_id)".format(comment_id=comment_id))
        return False

    db_connection = DbConnection()

    #Update sell currency portfolio
    query = ("UPDATE portfolio "
             "SET amount = %s "
             "WHERE game_id = %s AND owner = %s AND currency = %s")
    db_connection.cursor.execute(query, [(available_funds - float(trade_cost)), game_id, username, sell_currency])

    #Update buy currency portolfio or add it if it doesnt exist
    query = ("SELECT portfolio_id FROM portfolio "
             "WHERE game_id = %s AND owner = %s AND currency = %s")
    db_connection.cursor.execute(query, [game_id, username, buy_currency])
    portfolio_id_result_set = db_connection.cursor.fetchall()

    if portfolio_id_result_set:
        portfolio_id = portfolio_id_result_set[0]["portfolio_id"]
        query = ("UPDATE portfolio "
                 "SET amount = amount + %s "
                 "WHERE portfolio_id = %s")
        db_connection.cursor.execute(query, [buy_quantity, portfolio_id])
    else:
        query = "INSERT INTO portfolio (game_id, owner, currency, amount) VALUES (%s, %s, %s, %s)"
        db_connection.cursor.execute(query, [game_id, username, buy_currency, buy_quantity])

    query = ("INSERT INTO executed_trade (game_id, comment_id, buy_currency, buy_amount, sell_currency, sell_amount) "
            "VALUES (%s, %s, %s, %s, %s, %s)")
    db_connection.cursor.execute(query, [game_id, comment_id, buy_currency, buy_quantity, sell_currency, trade_cost])

    db_connection.connection.commit()
    db_connection.connection.close()

    return True

def create_limit_order(submission_id, comment_id, username, buy_quantity, buy_currency, available_funds, trade_cost, sell_currency, limit_price):
    """
    creates a limit order as an atomic function by moving currency from the portfolio to the limit_order table
    :param submission_id: id of the game the request is for
    :param comment_id: id of the comment that contains the request
    :param username: user that requested the trade
    :param buy_quantity: amount of buy_currency bought
    :param buy_currency: the currency that was bought
    :param available_funds: amount of sell_currency available for sale
    :param trade_cost: amount of sell_currency it cost to buy the amount of buy_currency
    :param sell_currency: the currency that was sold
    :return: success or failure
    """

    db_connection = DbConnection()
    query = "SELECT game_id FROM game_submission WHERE game_submission.submission_id = %s"
    db_connection.cursor.execute(query, [submission_id])
    game_id = db_connection.cursor.fetchall()[0]["game_id"]

    #Update sell currency portfolio
    query = ("UPDATE portfolio "
             "SET amount = %s "
             "WHERE game_id = %s AND owner = %s AND currency = %s")
    db_connection.cursor.execute(query, [(available_funds - trade_cost), game_id, username, sell_currency])

    #create limit order by inserting into table
    query = ("INSERT INTO limit_order (game_id, comment_id, owner, buy_currency, buy_amount, sell_currency, sell_amount, limit_price, executed, canceled) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    db_connection.cursor.execute(query, [game_id, comment_id, username, buy_currency, buy_quantity, sell_currency, trade_cost, limit_price, False, False])

    db_connection.connection.commit()
    db_connection.connection.close()

def cancel_limit_order(limit_order_id, username):
    """
    :param limit_order_id: id of limit order to cancel
    :param username: username of requestor
    :return: True if successful False otherwise
    """

    db_connection = DbConnection()
    query = "SELECT * FROM limit_order WHERE limit_order_id = %s AND owner = %s AND executed = false AND canceled = false"
    db_connection.cursor.execute(query, [limit_order_id, username])
    limit_orders = db_connection.cursor.fetchall()

    if limit_orders:
        limit_order = limit_orders[0]
        sell_currency = limit_order["sell_currency"]
        sell_amount = limit_order["sell_amount"]
        game_id = limit_order["game_id"]

        # Update sell currency portfolio
        query = ("UPDATE portfolio "
                 "SET amount = amount + %s "
                 "WHERE game_id = %s AND owner = %s AND currency = %s")
        db_connection.cursor.execute(query, [sell_amount, game_id, username, sell_currency])

        #cancel order in table
        query = "UPDATE limit_order SET canceled = true WHERE limit_order_id = %s AND owner = %s"
        db_connection.cursor.execute(query, [limit_order_id, username])

        db_connection.connection.commit()
        db_connection.connection.close()
        return True
    else:
        return False

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

def get_users_open_limit_orders(submission_id, username):
    """
    :param submission_id: The game the portfolio belongs to
    :param username: username the portfolio belongs to
    :param currency: None if you want everything or specify the currency you want info for
    :return: If currency is None return the entire portfolio otherwise get only the currency specified
    """

    db_connection = DbConnection()
    query = ("SELECT * FROM limit_order "
             "JOIN game_submission ON game_submission.game_id = limit_order.game_id "
             "WHERE game_submission.submission_id = %s AND limit_order.owner = %s AND "
             "executed = false AND canceled = false "
             "ORDER BY buy_currency ASC")
    db_connection.cursor.execute(query, [submission_id, username])
    limit_orders = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return limit_orders

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

def get_all_portfolios(submission_id):
    """
    :param submission_id: The game the portfolio belongs to
    :return: return portfolios for everyone playing the game with submission_id
    """

    db_connection = DbConnection()
    query = ("SELECT * FROM portfolio "
             "JOIN game_submission ON game_submission.game_id = portfolio.game_id "
             "WHERE game_submission.submission_id = %s")
    db_connection.cursor.execute(query, [submission_id])
    portfolios = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return portfolios

def get_all_open_limit_orders(submission_id):
    """
    :param submission_id: The game the limit orders belongs to
    :return: return open limit orders for everyone playing the game with submission_id
    """

    db_connection = DbConnection()
    query = ("SELECT * FROM limit_order "
             "JOIN game_submission ON game_submission.game_id = limit_order.game_id "
             "WHERE game_submission.submission_id = %s AND limit_order.executed = false AND limit_order.canceled = false")
    db_connection.cursor.execute(query, [submission_id])
    limit_orders = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return limit_orders


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
    limit_orders = get_users_open_limit_orders(submission_id, username)

    portfolio_summary = ""

    currencies = get_currencies(submission_id, username)
    usd_value = get_currencies_current_usd_value(currencies)
    total_usd_value = 0

    if portfolio:
        portfolio_header = ("**Available Funds:**\n\n"
                            "Currency | Amount | Value (USD)\n"
                  "---|---|----\n")
        portfolio_body = ""

        total_portfolio_usd_value = 0

        for portfolio_currency in portfolio:
            currency = portfolio_currency["currency"]
            amount = float(portfolio_currency["amount"])
            if currency in usd_value:
                currency_value = amount * usd_value[currency]
                total_portfolio_usd_value += currency_value
                portfolio_body += currency + "|" + '{:,.6g}'.format(amount) + "|" + '${:,.2f}'.format(currency_value) + "\n"
        portfolio_footer = "**TOTAL**|**-----**|**" + '${:,.2f}'.format(total_portfolio_usd_value) + "**\n"

        portfolio_summary += portfolio_header + portfolio_body + portfolio_footer
        total_usd_value += total_portfolio_usd_value
    else:
        logger.error("Something might be wrong with {username}'s portfolio for game {submission_id}. "
                     "They have no portfolio for the given game!".format(username = username,
                                                                         submission_id = submission_id))
        return ""

    if limit_orders:
        limit_order_header = ("**Limit Orders:**\n\n"
                              "Order ID | Buy Currency | Buy Quantity | Sell Currency | Sell Quantity | Limit Price | Value (USD)\n"
                            "---|---|---|---|---|---|----\n")
        limit_order_body = ""

        total_limit_order_usd_value = 0

        for limit_order_currency in limit_orders:
            buy_currency = limit_order_currency["buy_currency"]
            buy_quantity = limit_order_currency["buy_amount"]
            limit_price = limit_order_currency["limit_price"]
            currency = limit_order_currency["sell_currency"]
            amount = float(limit_order_currency["sell_amount"])
            order_id = limit_order_currency["limit_order_id"]
            if currency in usd_value:
                currency_value = amount * usd_value[currency]
                total_limit_order_usd_value += currency_value
                limit_order_body += (str(order_id) + "|" + buy_currency + "|" + '{:,.6g}'.format(buy_quantity) + "|" +
                                     currency + "|" + '{:,.6g}'.format(amount) + "|" + '{:,.6g}'.format(limit_price) + "|" + '${:,.2f}'.format(
                    currency_value) + "\n")
                limit_order_footer = "**TOTAL**|**-----**|**-----**|**-----**|**-----**|**-----**|**" + '${:,.2f}'.format(total_limit_order_usd_value) + "**\n"

        portfolio_summary += "\n\n^^^^.\n\n " + limit_order_header + limit_order_body + limit_order_footer
        total_usd_value += total_limit_order_usd_value

        portfolio_summary += "\n\n^^^^.\n\n The total combined value of your portfolio and limit orders is: " \
                             "**{total}**".format(total = '{:,.2f}'.format(total_usd_value))

    return portfolio_summary

def get_currencies_current_usd_value(currencies):
    """
    :param currencies: the currencies to get the USD value for
    :return: dictionary containing currency USD values
    """
    try:
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

        prices = {}
        for price in response:
            prices[price] = response[price]["USD"]
        return prices
    except Exception as err:
        logger.exception("Error getting usd values")
        return {}

def get_currencies_historical_usd_value(currencies, price_time):
    """
    :param currencies: the currencies to get the USD value for
    :param price_time: the point in time to get the price for
    :return: dictionary containing currency USD values
    """
    try:
        price_threads = []
        historical_prices = {}

        for currency in currencies:
            if currency == "USD":
                historical_prices["USD"] = 1
            else:
                # Thread api calls because they take a while in succession
                t = Thread(target=get_currency_historical_usd_value, args=[currency, price_time, historical_prices])
                price_threads.append(t)
                t.start()

        # Wait for all checks
        for price_thread in price_threads:
            price_thread.join()

        return historical_prices

    except Exception as err:
        logger.exception("Error getting usd values")
        return {}

def get_currency_historical_usd_value(currency, price_time, historical_prices):
    """
    get the historical price for currency at price_time
    :param currency: the currency to get the price for
    :param price_time: the point in time to get the price for
    :param historical_prices: the dictipnary to add prices to
    """
    api_url = ("https://min-api.cryptocompare.com/data/histominute?"
               "fsym={from_symbol}&"
               "tsym=USD&"
               "toTs={price_time}&"
               "e=CCCAGG&"
               "limit=1&"
               "extraParams=reddit_trading_game".format(
        from_symbol = currency,
        price_time = price_time
    ))

    response = {}
    api_error_count = 0

    # Loop to retry getting API data. Will break on success or 10 consecutive errors
    while True:
        r = requests.get(api_url)
        response = r.json()

        # If not success then retry up to 10 times after 1 sec wait
        if response.get("Response", "Error") != "Success":
            api_error_count += 1
            logger.error("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                            error_count=api_error_count))
            time.sleep(1)
            if api_error_count >= 10:
                send_dev_pm("Retry number {error_count} call {api_url}".format(api_url=api_url,
                                                                               error_count=api_error_count))
                break
        else:
            for minute_data in response["Data"]:
                if (price_time - minute_data['time']) < 60:
                    historical_prices[currency] = minute_data['close']
            break

def update_leader_board(submission_record):
    """
    Updates the leaderboard for the game with submission_id
    :param submission_record: the reddit submission of the game to update
    :param leader_board_time: the as of time to use for the price
    :param game_over: True if the game is over and this is the final update
    :return:
    """
    submission_id = submission_record["submission_id"]
    submission = reddit.submission(id=submission_id)
    current_datetime = time.time()
    game_end_datetime = calendar.timegm(submission_record["game_end_datetime"].utctimetuple())
    game_over = False
    leader_board_time = current_datetime

    if current_datetime >= game_end_datetime:
        game_over = True
        leader_board_time = game_end_datetime

    leader_board_text = get_leader_board_text(submission_id, leader_board_time, game_over)
    leader_board_text = "<leader_board>\n\n" + leader_board_text + "<\leader_board>"
    regex = re.compile(r"<leader_board>.*<\\leader_board>", re.DOTALL)

    updated_body = ""
    if regex.search(submission.selftext):
        updated_body = regex.sub(leader_board_text, submission.selftext)
    else:
        updated_body = submission.selftext + "\n\n" + leader_board_text

    submission.edit(updated_body)

def close_game(submission_id):
    """
    closes out the game with the submission_id
    :param submission_id: the id of the game to close
    """

    db_connection = DbConnection()
    query = "UPDATE game_submission SET complete = true WHERE submission_id = %s"
    db_connection.cursor.execute(query,[submission_id])
    db_connection.connection.commit()
    db_connection.connection.close()

def get_leader_board(submission_id, leader_board_time):
    """
    Gets the leader board for the submission with submission_id at the point in time specified by leader_board_time
    :param submission_id: the id of the game to get the leader board for
    :param leader_board_time: the point in time to get the leader board
    :return: a dicttionary where the key is a username and the value is the value of the users portfolio
    """
    portfolio_values = {}

    currencies = get_currencies(submission_id)
    if currencies:
        now_timestamp = time.time()

        if (now_timestamp - leader_board_time) > 60:
            currencies_usd_value = get_currencies_historical_usd_value(currencies, int(leader_board_time))
        else:
            currencies_usd_value = get_currencies_current_usd_value(currencies)

        portfolios = get_all_portfolios(submission_id)
        limit_orders = get_all_open_limit_orders(submission_id)

        for portfolio in portfolios:
            owner = portfolio["owner"]
            currency = portfolio["currency"]
            amount = portfolio["amount"]
            portfolio_values[owner] = portfolio_values.get(owner, 0.0) + (currencies_usd_value[currency] * float(amount))

        for limit_order in limit_orders:
            owner = limit_order["owner"]
            currency = limit_order["sell_currency"]
            amount = limit_order["sell_amount"]
            portfolio_values[owner] = portfolio_values.get(owner, 0.0) + (currencies_usd_value[currency] * float(amount))

    return sorted(portfolio_values.items(), key=operator.itemgetter(0), reverse=True)

def get_leader_board_text(submission_id, leader_board_time, game_over):
    """
    Gets the text for the leaderboard to be used in the games post
    :param submission_id: the game to get the leader board for
    :param currencies_usd_value: the values of all the cryptos being used in the game
    :param game_over: true if the game has ended
    :return: the text for the leaderboard to be used in the games post
    """
    leader_board = get_leader_board(submission_id, leader_board_time)

    update_leader_board_table(submission_id, leader_board)

    game_end_header = ""
    if leader_board and game_over:
        winner = leader_board[0][0]
        game_end_header = "### GAME END FINAL STANDINGS: Congrats to the winner {winner}!!!\n\n".format(winner = winner)

    leader_board_header = (game_end_header +
                           "**Leader Board Updated at "
                           "[{update_datetime} UTC](http://www.wolframalpha.com/input/?i={update_datetime} UTC To Local Time):**\n\n".format(
                            update_datetime = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")) +
                          "User | Value (USD)\n"
                          "---|---\n")
    leader_board_body = ""

    num_bold_leaders = 3
    num_leaders = 0
    for portfolio_value in leader_board:
        num_leaders += 1
        if num_leaders <= num_bold_leaders:
            username = "**" + portfolio_value[0] + "**"
        else:
            username = portfolio_value[0]

        value = portfolio_value[1]
        leader_board_body += username + "|" + '{:,.2f}'.format(value) + "\n"

    return leader_board_header + leader_board_body

def update_leader_board_table(submission_id, leader_board):
    """
    Updates the leader board for the game
    :param submission_id: id fot the game to update the leader board for
    :param leader_board: the leader board to save
    """
    if leader_board:
        db_connection = DbConnection()
        query = "SELECT game_id FROM game_submission WHERE game_submission.submission_id = %s"
        db_connection.cursor.execute(query, [submission_id])
        game_id = db_connection.cursor.fetchall()[0]["game_id"]

        query = ("DELETE standings FROM standings "
                "WHERE game_id = %s")
        db_connection.cursor.execute(query, [game_id])

        values_sql = ""
        sql_args = []

        for leader in leader_board:
            values_sql += "(%s, %s, %s),"
            sql_args.append(game_id)
            sql_args.append(leader[0])
            sql_args.append(leader[1])

        values_sql = values_sql[:-1]

        query = ("INSERT INTO standings (game_id, owner, portfolio_value) VALUES {values}".format(values=values_sql))
        db_connection.cursor.execute(query, sql_args)

        db_connection.connection.commit()
        db_connection.connection.close()

def get_submission_record(submission_id):
    """
    Retreive game from the DB
    :return: returns record from game_submission table
    """
    db_connection = DbConnection()
    query = "SELECT * FROM game_submission WHERE submission_id = %s"
    db_connection.cursor.execute(query,[submission_id])
    submission_record = db_connection.cursor.fetchall()
    db_connection.connection.close()

    return submission_record
def get_current_games():
    """
    Retreive all active games from the DB
    :return: returns tuple of submission_ids for all active games
    """
    db_connection = DbConnection()
    query = "SELECT * FROM game_submission WHERE complete = false"
    db_connection.cursor.execute(query,[])
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

def update_leader_boards():
    try:
        current_games = get_current_games()
        for current_game in current_games:
            update_leader_board(current_game)
    except Exception as err:
        logger.exception("Unknown Exception in update_leader_boards")

def process_limit_order(limit_order):
    """
    Checks if the limit_order needs to be processed and does so if needed
    :param limit_order: the limit_order to process
    """
    limit_order_id = limit_order["limit_order_id"]
    buy_currency = limit_order["buy_currency"]
    sell_currency = limit_order["sell_currency"]
    limit_price = limit_order["limit_price"]
    comment_id = limit_order["comment_id"]
    current_time =  time.time()

    current_price = get_trading_price(buy_currency, sell_currency, current_time)

    if current_price <= limit_price:
        message = reddit.comment(comment_id)
        limit_order_executed = execute_limit_order(limit_order)

        if limit_order_executed:
            portfolio_summary = get_portfolio_summary(message.parent().id, message.author.name)
            message.reply("Limit order executed! "
                          "Here is the current state of your portfolio:\n\n{portfolio_summary}".format(
                portfolio_summary=portfolio_summary
            ))
        else:
            send_dev_pm("Error Executing Limit Order", "Could not execute limit_order with id: {limit_order_id}".format(
                limit_order_id=limit_order_id
            ))

def execute_limit_orders():
    """
    checks if limit orders should be processed and processes them if so
    """
    try:
        current_games = get_current_games()
        limit_order_threads = []
        for current_game in current_games:
            current_game_id = current_game["submission_id"]
            limit_orders = get_all_open_limit_orders(current_game_id)
            for limit_order in limit_orders:
                # Thread api calls because they take a while in succession
                t = Thread(target=process_limit_order,
                           args=[limit_order])
                limit_order_threads.append(t)
                t.start()

        # Wait for all limit_orders
        for price_thread in limit_order_threads:
            price_thread.join()

    except Exception as err:
        logger.exception("Unknown Exception in execute_limit_orders")



def close_games():
    """
    closes games if they are past the end date
    """
    try:
        current_games = get_current_games()
        for current_game in current_games:
            current_datetime = time.time()
            game_end_datetime = calendar.timegm(current_game["game_end_datetime"].utctimetuple())

            if current_datetime >= game_end_datetime:
                close_game(current_game["submission_id"])


    except Exception as err:
        logger.exception("Unknown Exception in close_games")

def execute_limit_order(limit_order):
    """
    Executes the limit order by making closing the limit order and adding the appropriate funds to the owners portfolio
    :param limit_order: The limit order table row to execute
    :return:
    """
    limit_order_id = limit_order["limit_order_id"]
    game_id = limit_order["game_id"]
    owner = limit_order["owner"]
    buy_amount = limit_order["buy_amount"]
    sell_amount = limit_order["sell_amount"]
    buy_currency = limit_order["buy_currency"]
    sell_currency = limit_order["sell_currency"]
    comment_id = limit_order["comment_id"]


    db_connection = DbConnection()
    query = "UPDATE limit_order SET executed = true WHERE limit_order_id = %s"
    db_connection.cursor.execute(query, [limit_order_id])

    trade_executed = execute_trade(comment_id, owner, buy_amount, buy_currency,
                  sell_amount, sell_currency, True, game_id = game_id)
    if trade_executed:
        db_connection.connection.commit()
    else:
        logger.error("Could not execute trade")
        db_connection.connection.rollback()

    db_connection.connection.close()

    return trade_executed

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
            update_leader_boards()
            execute_limit_orders()
            close_games()

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
