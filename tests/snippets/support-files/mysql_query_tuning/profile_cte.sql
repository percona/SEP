-- Diagnostic queries for: with cte as (select user, host from mysql.user) select user, host from cte
EXPLAIN with cte as (select user, host from mysql.user) select user, host from cte\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON with cte as (select user, host from mysql.user) select user, host from cte\G
SHOW WARNINGS \G
