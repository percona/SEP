-- Diagnostic queries for: with cte as (select user, host from mysql.user) select user, host from cte
EXPLAIN with cte as (select user, host from mysql.user) select user, host from cte\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON with cte as (select user, host from mysql.user) select user, host from cte\G
SHOW WARNINGS \G
FLUSH STATUS;
SET optimizer_trace='enabled=on';
SET optimizer_trace_max_mem_size=1024*1024*16;
SET profiling_history_size=0;
SET profiling=1;
SET profiling_history_size=5;
PAGER md5sum;
with cte as (select user, host from mysql.user) select user, host from cte;
NOPAGER;
SHOW STATUS LIKE 'Handler%';
SELECT * FROM INFORMATION_SCHEMA.OPTIMIZER_TRACE\G
SET optimizer_trace='enabled=off';
SHOW PROFILES;
SHOW PROFILE FOR QUERY 2;
