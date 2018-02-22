DROP SCHEMA IF EXISTS crypto_trading_game;
CREATE SCHEMA crypto_trading_game;
USE crypto_trading_game;

CREATE TABLE `game_submission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `subreddit` varchar(400) NOT NULL,
  `submission_id` varchar(10) NOT NULL,
  `author` varchar(50) NOT NULL,
  `game_begin_datetime` DATETIME NOT NULL,
  `game_end_datetime` DATETIME NOT NULL,
  `create_timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_timestamp` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
);
