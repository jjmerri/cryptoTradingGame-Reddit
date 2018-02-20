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
                     user_agent='cryptoRemindMe by /u/BoyAndHisBlob',
                     username=bot_username)

DB_USER = config.get("SQL", "user")
DB_PASS = config.get("SQL", "passwd")

ENVIRONMENT = config.get("REMINDME", "environment")

DEV_USER_NAME = "BoyAndHisBlob"

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('cryptoRemindMeBot')
logger.setLevel(logging.INFO)

#Dictionary to store current crypto prices
current_price = {"XRP": 0.0}

supported_tickers = ["ADA","BCH","BCN","BTC","BTG","DASH","DOGE","ETC","ETH","LSK","LTC","NEO","QASH","QTUM","REQ",
                     "STEEM","XEM","XLM","XMR","XRB","XRP","ZEC"]

# =============================================================================
# CLASSES
# =============================================================================
class ParseMessage(Enum):
    SUCCESS = 1
    SYNTAX_ERROR = 2
    UNSUPPORTED_TICKER = 3

class DbConnection(object):
    """
    DB connection class
    """
    connection = None
    cursor = None

    def __init__(self):
        self.connection = MySQLdb.connect(
            host="localhost", user=DB_USER, passwd=DB_PASS, db="crypto_remind_me"
        )
        self.cursor = self.connection.cursor()

class Search(object):
    def __init__(self, comment):
        self._db_connection = DbConnection()
        self.comment = comment # Reddit comment Object
        self._message_input = '"Hello, I\'m here to remind you to see the parent comment!"'
        self._store_price = None
        self._ticker = None
        self._reply_message = ""
        self._replyDate = None
        self._privateMessage = False
        self._origin_date = datetime.fromtimestamp(comment.created_utc)
        self.endMessage = get_message_footer()

    def run(self, privateMessage=False):
        parsed_command = None
        self._privateMessage = privateMessage
        try:
            parsed_command = self._parse_comment()
        except Exception as err:
            logger.error(err)
            logger.error("Unknown Exception in run while parsing comment")
            parsed_command = None

        if parsed_command == ParseMessage.SUCCESS:
            try:
                self._save_to_db()
                self._build_message()
                self._reply()
            except Exception as err:
                logger.error(err)
                logger.error("Unknown Exception in run after parsed command")
                send_message_generic_error(self.comment)
        elif parsed_command == ParseMessage.SYNTAX_ERROR:
            send_message_syntax(self.comment)
        elif parsed_command == ParseMessage.UNSUPPORTED_TICKER:
            send_message_unsupported_ticker(self.comment, self._ticker)
        elif parsed_command is None:
            send_message_generic_error(self.comment)


        if self._privateMessage == True:
            # Makes sure to marks as read, even if the above doesn't work
            self.comment.mark_read()
            if parsed_command == ParseMessage.SUCCESS:
                self._find_bot_child_comment()

        self._db_connection.connection.close()

    def _parse_comment(self):
        """
        Parse comment looking for the message and price
        :returns True or False based on successful parsing
        """
        response_message = None
        command_regex = r'!?cryptoRemindMe!?[ ]+(?P<ticker>[^ ]+)[ ]+\$?(?P<price>(([\d,]+(\.\d+)?)|(([\d,]+)?\.\d+)))([ ]+)?(?P<message>"[^"]+")?'
        request_id_regex = r'\[(?P<request_id>[a-zA-Z0-9_.-]+)\]'

        if self._privateMessage == True:
            request_id = re.search(request_id_regex, self.comment.body)
            if request_id and is_valid_comment_id(request_id.group("request_id")):
                comment = reddit.comment(request_id.group("request_id"));
                self.comment.target_id = comment.id
                self.comment.permalink = comment.permalink
            else:
                # Defaults when the user doesn't provide a link
                self.comment.target_id = "du0cwqr"
                self.comment.permalink = "http://np.reddit.com/r/testingground4bots/comments/7whejk/crypto_remind_me_default/du0cwqr/"
        else:
            self.comment.target_id = self.comment.id
        # remove cryptoRemindMe! or !cryptoRemindMe (case insenstive)
        match = re.search(command_regex, self.comment.body, re.IGNORECASE)

        if match and match.group("ticker") and match.group("price"):
            self._ticker = match.group("ticker").upper()
            self._store_price = match.group("price").replace(",","")
            self._message_input = match.group("message")

            if self._ticker not in supported_tickers:
                response_message = ParseMessage.UNSUPPORTED_TICKER
            else:
                response_message = ParseMessage.SUCCESS
        else:
            response_message = ParseMessage.SYNTAX_ERROR

        return response_message
    def _save_to_db(self):
        """
        Saves the id of the comment, the current price, and the message to the DB
        """

        cmd = "INSERT INTO reminder (object_name, message, new_price, origin_price, userID, permalink, ticker, comment_create_datetime) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        self._db_connection.cursor.execute(cmd, (
                        self.comment.target_id.encode('utf-8'),
                        self._message_input.encode('utf-8') if self._message_input else None,
                        self._store_price,
                        current_price[self._ticker],
                        self.comment.author,
                        self.comment.permalink.encode('utf-8'),
                        self._ticker.encode('utf-8'),
                        self._origin_date))
        self._db_connection.connection.commit()

    def _build_message(self, is_for_comment = True):
        """
        Buildng message for user
        """
        permalink = self.comment.permalink
        self._reply_message =(
            "I will be messaging you when the price of {ticker} reaches **{price}** from its current price **{current_price}**"
            " to remind you of [**this link.**]({commentPermalink})"
            "{remindMeMessage}")

        if self._privateMessage is False and is_for_comment:
            remindMeMessage = (
                "\n\n[**CLICK THIS LINK**](http://np.reddit.com/message/compose/?to=cryptoRemindMeBot&subject=Reminder&message="
                "[{id}]%0A%0AcryptoRemindMe! {ticker} ${price}) to send a PM to also be reminded and to reduce spam."
                "\n\n^(Parent commenter can ) [^(delete this message to hide from others.)]"
                "(http://np.reddit.com/message/compose/?to=cryptoRemindMeBot&subject=Delete Comment&message=Delete! ____id____)").format(
                    id=self.comment.target_id,
                    price=self._store_price.replace('\n', ''),
                    ticker = self._ticker
                )
        else:
            remindMeMessage = ""

        self._reply_message = self._reply_message.format(
                remindMeMessage = remindMeMessage,
                commentPermalink = permalink,
                price = '${:,.4f}'.format(float(self._store_price)),
                ticker = self._ticker,
                current_price = '${:,.4f}'.format(float(current_price[self._ticker])))
        self._reply_message += self.endMessage

    def _reply(self):
        """
        Messages the user letting as a confirmation
        """

        author = self.comment.author
        def send_message():
            self._build_message(False)
            reddit.redditor(str(author)).message('cryptoRemindMe Confirmation', self._reply_message)

        try:
            if self._privateMessage == False:
                newcomment = self.comment.reply(self._reply_message)
                # grabbing comment just made
                reddit.comment((newcomment.id)
                    ).edit(self._reply_message.replace('____id____', str(newcomment.id)))
            else:
                send_message()
        except APIException as err: # Catch any less specific API errors
            logger.error(err)
            logger.error("APIException in _reply")
            if err.error_type == "RATELIMIT":
                send_message()

        except PRAWException as err:
            logger.error(err)
            logger.error("PRAWException in _reply")
            send_message()
        except Exception as err:
            logger.error(err)
            logger.error("Unknown Exception in _reply")

    def _find_bot_child_comment(self):
        """
        Finds the cryptoRemindMeBot comment in the child
        """
        try:
            # Grabbing all child comments
            replies = reddit.comment(self.comment.target_id).refresh().replies.list()
            # Look for bot's reply
            if replies:
                for comment in replies:
                    if str(comment.author) == "cryptoRemindMeBot" or str(comment.author) == "cryptoRemindMeBotTst":
                        self.comment_count(comment)
                        break;
        except Exception as err:
            logger.error(err)
            logger.error("Unknown Exception in _find_bot_child_comment")
            
    def comment_count(self, found_comment):
        """
        Posts edits the count if found
        """
        query = "SELECT count(DISTINCT userid) FROM reminder WHERE object_name = %s"
        self._db_connection.cursor.execute(query, [self.comment.target_id])
        data = self._db_connection.cursor.fetchall()
        # Grabs the tuple within the tuple, a number/the dbcount
        dbcount = count = str(data[0][0])
        body = found_comment.body

        pattern = r'(\d+ OTHERS |)CLICK(ED|) THIS LINK'
        # Compares to see if current number is bigger
        # Useful for after some of the reminders are sent, 
        # a smaller number doesnt overwrite bigger
        try:
            currentcount = int(re.search(r'\d+', re.search(pattern, body).group(0)).group())
        # for when there is no number
        except AttributeError as err:
            currentcount = 0
        if currentcount > int(dbcount):
            count = str(currentcount + 1)
        # Adds the count to the post
        body = re.sub(
            pattern, 
            count + " OTHERS CLICKED THIS LINK", 
            body)
        found_comment.edit(body)

def is_valid_comment_id(comment_id):
    is_valid = False
    try:
        reddit.comment(comment_id).submission
        is_valid = True
    except PRAWException as err:
        logger.error(err)
        logger.error("Not a valid ID")
        is_valid = False
    except Exception as err:
        logger.error(err)
        logger.error("Unknown Exception in is_valid_comment_id")
        is_valid = False

    return is_valid

def get_disclaimer():
    return ("^^^^.\n\n"
           "^^^^**DISCLAIMER:** ^^^^The ^^^^developer ^^^^that ^^^^maintains ^^^^this ^^^^bot ^^^^does ^^^^not ^^^^guarantee ^^^^the ^^^^accuracy ^^^^of ^^^^the ^^^^data ^^^^it ^^^^provides ^^^^nor ^^^^does ^^^^he ^^^^gurantee ^^^^the ^^^^reliability ^^^^of ^^^^its ^^^^notification ^^^^system. ^^^^Do ^^^^not ^^^^rely ^^^^on ^^^^this ^^^^bot ^^^^for ^^^^information ^^^^that ^^^^will ^^^^affect ^^^^your ^^^^financial ^^^^decisions. ^^^^Double ^^^^check ^^^^all ^^^^prices ^^^^before ^^^^acting ^^^^on ^^^^any ^^^^information ^^^^provided ^^^^by ^^^^this ^^^^bot. ^^^^Do ^^^^not ^^^^rely ^^^^solely ^^^^on ^^^^this ^^^^bot ^^^^to ^^^^notify ^^^^you ^^^^of ^^^^price ^^^^updates ^^^^as ^^^^it ^^^^doesn't ^^^^have ^^^^failsafes ^^^^in ^^^^place ^^^^to ^^^^be ^^^^100% ^^^^reliable."
            )
def get_message_footer():
    return (
        "\n\n_____\n\n"
        "|[^(README)](https://github.com/jjmerri/cryptoRemindMe-Reddit/blob/master/README.md)"
        "|[^(Your Reminders)](http://np.reddit.com/message/compose/?to=cryptoRemindMeBot&subject=List Of Reminders&message=MyReminders!)"
        "|[^(Feedback)](http://np.reddit.com/message/compose/?to=" + DEV_USER_NAME + "&subject=cryptoRemindMe Feedback)"
        "|[^(Code)](https://github.com/jjmerri/cryptoRemindMe-Reddit)"
        "\n|-|-|-|-|-|-|\n\n" + get_disclaimer()
    )
def send_message_syntax(comment):
    """
    PMs the user with the correct syntax to use.
    """
    message_subject = "cryptoRemindMe Syntax Error"
    message_body = ("Hello {author},\n\n"
                   "[Your request]({permalink}) could not be processed because [you used the incorrect syntax.]({fail_link})\n\n"
                   "Please try again using the following syntax:\n\n"
                    "cryptoRemindMe! {{ticker}} {{price}} {{optional_message}}\n\n"
                    "Example:\n\n"
                    'cryptoRemindMe! xrp $1.25 "Some reason I wanted this reminder"\n\n'
                    '{footer}')

    reddit.redditor(str(comment.author)).message(message_subject, message_body.format(
        author = str(comment.author),
        permalink = str(comment.permalink),
        fail_link = "https://media.giphy.com/media/87I8pKmdcAKw8/giphy.gif",
        footer = get_message_footer()
    ))

def send_message_unsupported_ticker(comment, ticker):
    """
    PMs the user with a generic error
    """
    message_subject = "cryptoRemindMe Unsupported Cryptocurrency"
    message_body = ("Hello {author},\n\n"
                    "[Sorry]({sorry_link}) but {ticker} is not currently supported "
                    "so [your request]({permalink}) couldn't be processed.\n\n"
                    "Currently, the supported cryptocurrencies are:\n\n"
                    "{supported_tickers}\n\n"
                    "{footer}")

    reddit.redditor(str(comment.author)).message(message_subject, message_body.format(
        author=str(comment.author),
        permalink=str(comment.permalink),
        sorry_link="https://media.giphy.com/media/sS8YbjrTzu4KI/giphy.gif",
        ticker = ticker,
        supported_tickers = ", ".join(supported_tickers),
        footer = get_message_footer()
    ))

def send_message_generic_error(comment):
    """
    PMs the user with a generic error
    """
    message_subject = "cryptoRemindMe Error"
    message_body = ("Hello {author},\n\n"
                   "[Sorry]({sorry_link}) but there was an unknown error processing [your request]({permalink})\n\n"
                   "Please try again later.\n\n"
                    "{footer}")

    reddit.redditor(str(comment.author)).message(message_subject, message_body.format(
        author = str(comment.author),
        permalink = str(comment.permalink),
        sorry_link = "https://media.giphy.com/media/sS8YbjrTzu4KI/giphy.gif",
        footer = get_message_footer()
    ))

def grab_list_of_reminders(username):
    """
    Grabs all the reminders of the user
    """
    database = DbConnection()
    query = "SELECT permalink, message, new_price, origin_price, ticker, id FROM reminder WHERE userid = %s ORDER BY comment_create_datetime"
    database.cursor.execute(query, [username])
    data = database.cursor.fetchall()
    table = (
            "[**Click here to delete all your reminders at once quickly.**]"
            "(http://np.reddit.com/message/compose/?to=cryptoRemindMeBot&subject=Reminder&message=RemoveAll!)\n\n"
            "|Permalink|Message|Reminder Price|Price at Time of Request|ticker|Remove|\n"
            "|-|-|-|-|-|:-:|")
    for row in data:
        table += (
            "\n|" + str(row[0]) + "|" + str(row[1]) + "|" + '${:,.4f}'.format(row[2]) + "|" + '${:,.4f}'.format(row[3]) + "|" + str(row[4]) + "|" +
            "[[X]](https://np.reddit.com/message/compose/?to=cryptoRemindMeBot&subject=Remove&message=Remove!%20"+ str(row[5]) + ")|"
            )
    if len(data) == 0: 
        table = "You currently have no reminders."
    elif len(table) > 9000:
        table = "The table has been truncated due to message length:\n\n" + table[0:8999]
    table += get_message_footer()
    return table

def remove_reminder(username, idnum):
    """
    Deletes the reminder from the database
    """
    database = DbConnection()

    cmd = "DELETE FROM reminder WHERE id = %s AND userid = %s"
    database.cursor.execute(cmd, [idnum, username])
    deleted_row_count = database.cursor.rowcount
    deleteFlag = deleted_row_count == 1
    
    database.connection.commit()
    return deleteFlag

def remove_all(username):
    """
    Deletes all reminders at once
    """
    database = DbConnection()

    cmd = "DELETE FROM reminder WHERE userid = %s"
    database.cursor.execute(cmd, [username])
    deleted_row_count = database.cursor.rowcount

    database.connection.commit()

    return deleted_row_count

def read_pm():
    try:
        for message in reddit.inbox.unread(limit = 100):
            # checks to see as some comments might be replys and non PMs
            prawobject = isinstance(message, praw.models.Message)

            if (prawobject and
                message.author is not None and
                message.author.name != "AutoModerator" and
                not message.was_comment and
                (ENVIRONMENT != "DEV" or (message.author is not None and message.author.name == DEV_USER_NAME))):

                if ("cryptoremindme" in message.body.lower() or
                    "cryptoremindme!" in message.body.lower() or
                    "!cryptoremindme" in message.body.lower()):
                    redditPM = Search(message)
                    redditPM.run(privateMessage=True)
                    message.mark_read()
                elif ("delete!" in message.body.lower() or "!delete" in message.body.lower()):
                    try:
                        givenid = re.findall(r'delete!\s(.*?)$', message.body.lower())[0]
                        comment = reddit.comment(givenid)
                        parentcomment = comment.parent()
                        if message.author.name == parentcomment.author.name:
                            comment.delete()
                    except ValueError as err:
                        # comment wasn't inside the list
                        logger.error(err)
                        logger.error("ValueError in read_pm in delete!")
                    except AttributeError as err:
                        # comment might be deleted already
                        logger.error(err)
                        logger.error("AttributeError in read_pm in delete!")
                    except Exception as err:
                        logger.error(err)
                        logger.error("Unknown Exception in read_pm in delete!")

                    message.mark_read()
                elif ("myreminders!" in message.body.lower() or "!myreminders" in message.body.lower()):
                    reminders_reply = grab_list_of_reminders(message.author.name)
                    message.reply(reminders_reply)
                    message.mark_read()
                elif ("remove!" in message.body.lower() or "!remove" in message.body.lower()):
                    givenid = re.findall(r'remove!\s(.*?)$', message.body.lower())[0]
                    deletedFlag = remove_reminder(message.author.name, givenid)
                    listOfReminders = grab_list_of_reminders(message.author.name)
                    # This means the user did own that reminder
                    if deletedFlag == True:
                        message.reply("Reminder deleted. Your current Reminders:\n\n" + listOfReminders)
                    else:
                        message.reply("Try again with the current IDs that belong to you below. Your current Reminders:\n\n" + listOfReminders)
                    message.mark_read()
                elif ("removeall!" in message.body.lower() or "!removeall" in message.body.lower()):
                    count = str(remove_all(message.author.name))
                    listOfReminders = grab_list_of_reminders(message.author.name)
                    message.reply("I have deleted all **" + count + "** reminders for you.\n\n" + listOfReminders)
                    message.mark_read()
                else: #unknown pm
                    #mark_read first in case unexpected error
                    message.mark_read()
                    message.reply("[Sorry](https://media.giphy.com/media/sS8YbjrTzu4KI/giphy.gif), I was unable to process your comment.\n\n"
                                  "Check out the [README](https://github.com/jjmerri/cryptoRemindMe-Reddit/blob/master/README.md) for a list of supported commands.")
                    permalink = None
                    if message.was_comment:
                        permalink = reddit.comment(message.id).parent().permalink

                    reddit.redditor(DEV_USER_NAME).message('cryptoRemindMe Unknown PM FWD',
                                    "From: " + (message.author.name if message.author is not None else message.subreddit_name_prefixed) + "\n\n" +
                                    "Subject: " + message.subject + "\n\n" +
                                    "Parent Permalink: " + (permalink if permalink is not None else "NONE") + "\n\n" +
                                    message.body)
            elif ENVIRONMENT != "DEV" and not message.was_comment:
                logger.info("Could not process PM from {author}".format(
                    author = (message.author.name if message.author is not None else "NONE")
                ))
                reddit.redditor(DEV_USER_NAME).message('cryptoRemindMe Unknown Message Received',
                                                       "Unknown PM received, check out the bot's inbox")
    except Exception as err:
        logger.error(traceback.format_exc())
        logger.error(err)
        logger.error("Unknown Exception in read_pm")

def check_comment(comment):
    """
    Checks the body of the comment, looking for the command
    """
    reddit_call = Search(comment)
    if (("cryptoremindme!" in comment.body.lower() or
        "!cryptoremindme" in comment.body.lower()) and
        'cryptoRemindMeBot' != str(comment.author) and
        'cryptoRemindMeBotTst' != str(comment.author)):
            logger.info("Running Thread")
            t = Thread(target=reddit_call.run())
            t.start()

def check_own_comments():
    for comment in reddit.redditor('cryptoRemindMeBot').comments.new(limit=None):
        if comment.score <= -5:
            logger.info(comment)
            comment.delete()
            logger.info("COMMENT DELETED")

def update_crypto_prices():
    """
    updates supported crypto prices with current exchange price
    """

    r = requests.get("https://min-api.cryptocompare.com/data/pricemulti?fsyms={supported_ticket_list}&tsyms=USD&e=CCCAGG"
                    .format(
                        supported_ticket_list = ','.join(map(str, supported_tickers))
                    ))
    response = r.json()

    for price in response:
        current_price[price] = response[price]["USD"]

#returns the time saved in lastrunsearch.txt
#returns 10000 if 0 is in the file because it will break the http call with 0
def get_last_run_time():
    lastrun_file = open("lastrunsearch.txt", "r")
    last_run_time = int(lastrun_file.read())
    lastrun_file.close()

    if last_run_time:
        return last_run_time
    else:
        return 10000

def create_lastrun():
    if not os.path.isfile("lastrunsearch.txt"):
        lastrun_file = open("lastrunsearch.txt", "w")
        lastrun_file.write("0")
        lastrun_file.close()

def create_running():
    running_file = open("search_bot.running", "w")
    running_file.write(str(os.getpid()))
    running_file.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    checkcycle = 0
    start_process = False
    logger.info("start")
    create_lastrun()

    if ENVIRONMENT == "DEV":
        os.remove("search_bot.running")
        logger.info("running file removed")

    if not os.path.isfile("search_bot.running"):
        create_running()
        start_process = True
    else:
        start_process = False
        logger.error("Search already running! Will not start.")

    last_processed_time = get_last_run_time()
    while start_process and os.path.isfile("search_bot.running"):
        logger.info("Start Main Loop")
        try:
            update_crypto_prices()
            # grab the request
            request = requests.get('https://api.pushshift.io/reddit/search/comment/?q=%22cryptoRemindMe%22&limit=100&after=' + str(last_processed_time),
                headers = {'User-Agent': 'cryptoRemindMeBot-Agent'})
            json = request.json()
            comments =  json["data"]
            read_pm()
            for rawcomment in comments:
                if last_processed_time < rawcomment["created_utc"]:
                    last_processed_time = rawcomment["created_utc"]

                # object constructor requires empty attribute
                rawcomment['_replies'] = ''
                comment = praw.models.Comment(reddit, id = rawcomment["id"])

                #Only process my own comments in dev
                if ENVIRONMENT != "DEV" or rawcomment["author"] == DEV_USER_NAME:
                    check_comment(comment)

            # Only check periodically
            if checkcycle >= 5:
                check_own_comments()
                checkcycle = 0
            else:
                checkcycle += 1

            lastrun_file = open("lastrunsearch.txt", "w")
            lastrun_file.write(str(last_processed_time))
            lastrun_file.close()

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
