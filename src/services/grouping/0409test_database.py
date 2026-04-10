from src.common.database import get_reward_connection

conn = get_reward_connection("zjknew")
try:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, ZJNO, XM FROM t_zjxx LIMIT 5")
        rows = cursor.fetchall()
        for row in rows:
            print(row)
finally:
    conn.close()

# from src.common.database import get_project_connection

# conn = get_project_connection()
# try:
#     with conn.cursor() as cursor:
#         cursor.execute("SELECT TOP 5 id, xmmc FROM Sb_Jbxx")
#         rows = cursor.fetchall()
#         for row in rows:
#             print(row)
# finally:
#     conn.close()
