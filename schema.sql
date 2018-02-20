DROP SCHEMA IF EXISTS crypto_remind_me;
CREATE SCHEMA crypto_remind_me;
USE crypto_remind_me;

CREATE TABLE `reminder` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `object_name` varchar(400) NOT NULL,
  `message` varchar(11000) DEFAULT NULL,
  `new_price` DECIMAL(18,9),
  `origin_price` DECIMAL(18,9),
  `userID` varchar(50),
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_date` DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `permalink` varchar(400) NOT NULL,
  `ticker` varchar(50) NOT NULL,
  `comment_create_datetime` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
