#!/bin/bash
# 清理端口占用
fuser -k 8000/tcp 2>/dev/null || true
sleep 1
# 等待 PostgreSQL 就绪
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    docker exec postgres pg_isready -U postgres >/dev/null 2>&1 && exit 0
    pg_isready -h localhost -p 5432 >/dev/null 2>&1 && exit 0
    sleep 1
done
echo "WARNING: PostgreSQL readiness check timed out, proceeding anyway"
exit 0
