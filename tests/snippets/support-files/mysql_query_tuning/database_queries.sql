-- Diagnostic queries for: SELECT user, host FROM user
USE mysql;
EXPLAIN SELECT user, host FROM user\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON SELECT user, host FROM user\G
SHOW WARNINGS \G
