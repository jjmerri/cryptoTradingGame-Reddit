DROP SCHEMA IF EXISTS crypto_trading_game;
CREATE SCHEMA crypto_trading_game;
USE crypto_trading_game;

CREATE TABLE `game_submission` (
  `game_id` int(11) NOT NULL AUTO_INCREMENT,
  `subreddit` varchar(400) NOT NULL,
  `submission_id` varchar(10) NOT NULL,
  `author` varchar(50) NOT NULL,
  `game_begin_datetime` DATETIME NOT NULL,
  `game_end_datetime` DATETIME NOT NULL,
  `create_timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_timestamp` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`game_id`)
);

CREATE TABLE `portfolio` (
  `portfolio_id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL,
  `owner` varchar(50) NOT NULL,
  `currency` varchar(50) NOT NULL,
  `amount` DECIMAL(18,9) NOT NULL,
  `create_timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_timestamp` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`portfolio_id`)
);

CREATE UNIQUE INDEX unique_portfolio_index
    ON portfolio (game_id, owner, currency);


CREATE TABLE `processed_comment` (
  `processed_comment_id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL,
  `comment_id` varchar(50) NOT NULL,
  `comment_body` varchar(10000) NOT NULL,
  `create_timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_timestamp` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`processed_comment_id`)
);

CREATE INDEX processed_comment_game_id_index
    ON processed_comment (game_id);

CREATE TABLE `executed_trade` (
  `executed_trade_id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL,
  `comment_id` varchar(50) NOT NULL,
  `buy_currency` varchar(50) NOT NULL,
  `buy_amount` DECIMAL(18,9) NOT NULL,
  `sell_currency` varchar(50) NOT NULL,
  `sell_amount` DECIMAL(18,9) NOT NULL,
  `create_timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_timestamp` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`executed_trade_id`)
);
