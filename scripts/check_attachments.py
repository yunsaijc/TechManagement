"""
查找项目中附件的存储方式
"""
import os
import pymysql
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_REWARD_HOST", "your_host"),
    "port": int(os.getenv("DB_REWARD_PORT", 3306)),
    "user": os.getenv("DB_REWARD_USER", "your_user"),
    "password": os.getenv("DB_REWARD_PASSWORD", "your_password_here"),
    "database": os.getenv("DB_REWARD_DATABASE", "your_database"),
}


def find_attachment_stored_files():
    """查找可能存储项目附件的表"""
    print("=== 查找存储附件的表（可能包含路径） ===")
    db_name = os.getenv("DB_REWARD_DATABASE", "your_database")
    conn = pymysql.connect(**DB_CONFIG, database=db_name, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        # 查找包含 attachment、file、upload 等的表
        cursor.execute(f"""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = '{db_name}' 
            AND table_name NOT LIKE 'act_%'
            AND table_name NOT LIKE 'flw_%'
            AND (table_name LIKE '%attach%' OR table_name LIKE '%upload%' OR table_name LIKE '%file%')
        """)
        tables = cursor.fetchall()
        for t in tables:
            print(f"  - {t['table_name']}")
    conn.close()


def check_sys_file_project_related():
    """检查sys_file中与项目相关的文件"""
    print("\n=== sys_file 中可能的附件文件 ===")
    db_name = os.getenv("DB_REWARD_DATABASE", "hbkjjl")
    conn = pymysql.connect(**DB_CONFIG, database=db_name, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT name, path, type 
            FROM sys_file 
            WHERE name LIKE '%.pdf' OR name LIKE '%.doc%' OR name LIKE '%.jpg'
            LIMIT 10
        """)
        rows = cursor.fetchall()
        for r in rows:
            print(f"  name: {r['name']}, path: {r['path']}")
    conn.close()


def check_file_relations():
    """查看文件与业务的关联"""
    print("\n=== sys_file 表结构 ===")
    db_name = os.getenv("DB_REWARD_DATABASE", "hbkjjl")
    conn = pymysql.connect(**DB_CONFIG, database=db_name, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        cursor.execute("DESCRIBE sys_file")
        rows = cursor.fetchall()
        for r in rows:
            print(f"  {r['Field']}: {r['Type']}")
    conn.close()


def find_t_xm_cl_attachment_field():
    """查看t_xm_cl表是否有附件路径字段"""
    print("\n=== t_xm_cl 表所有字段 ===")
    db_name = os.getenv("DB_PROJECT_DATABASE", "xmsbnew")
    conn = pymysql.connect(**DB_CONFIG, database=db_name, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        cursor.execute("DESCRIBE t_xm_cl")
        rows = cursor.fetchall()
        for r in rows:
            if 'file' in r['Field'].lower() or 'path' in r['Field'].lower() or 'url' in r['Field'].lower() or 'pdf' in r['Field'].lower():
                print(f"  *** {r['Field']}: {r['Type']} ***")
            else:
                print(f"  {r['Field']}: {r['Type']}")
    conn.close()


if __name__ == "__main__":
    find_attachment_stored_files()
    check_sys_file_project_related()
    check_file_relations()
    find_t_xm_cl_attachment_field()
