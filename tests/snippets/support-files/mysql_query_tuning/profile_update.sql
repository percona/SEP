-- Diagnostic queries for: UPDATE mysql.user SET user='foo' WHERE host='bar'
EXPLAIN UPDATE mysql.user SET user='foo' WHERE host='bar'\G
SHOW WARNINGS \G
EXPLAIN FORMAT=JSON UPDATE mysql.user SET user='foo' WHERE host='bar'\G
SHOW WARNINGS \G
