-- Diagnostic queries for: SELECT user, host FROM mysql.user
EXPLAIN SELECT user, host FROM mysql.user\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON SELECT user, host FROM mysql.user\G
SHOW WARNINGS \G
