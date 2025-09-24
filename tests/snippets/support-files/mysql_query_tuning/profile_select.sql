-- Diagnostic queries for: SELECT user, host FROM mysql.user
EXPLAIN SELECT user, host FROM mysql.user\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON SELECT user, host FROM mysql.user\G
SHOW WARNINGS \G
FLUSH STATUS;
SET optimizer_trace='enabled=on';
SET optimizer_trace_max_mem_size=1024*1024*16;
SET profiling_history_size=0;
SET profiling=1;
SET profiling_history_size=5;
PAGER md5sum;
SELECT user, host FROM mysql.user;
NOPAGER;
SHOW STATUS LIKE 'Handler%';
SELECT * FROM INFORMATION_SCHEMA.OPTIMIZER_TRACE\G
SET optimizer_trace='enabled=off';
SHOW PROFILES;
SHOW PROFILE FOR QUERY 2;
