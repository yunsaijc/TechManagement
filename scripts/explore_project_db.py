"""
详细探查核心表结构
"""
import os
import pyodbc
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

DB_CONFIG = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={os.getenv('DB_PROJECT_HOST', 'your_host')},1433;"
    f"DATABASE={os.getenv('DB_PROJECT_NAME', 'your_database')};"
    f"UID={os.getenv('DB_PROJECT_USER', 'your_user')};"
    f"PWD={os.getenv('DB_PROJECT_PASSWORD', 'your_password_here')};"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)


def get_columns(cursor, table_name):
    cursor.execute(f"""
        SELECT 
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            ep.value as COMMENT
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN sys.extended_properties ep 
            ON ep.major_id = OBJECT_ID(c.TABLE_NAME) 
            AND ep.minor_id = c.ORDINAL_POSITION
        WHERE c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
    """)
    return cursor.fetchall()


def show_table(cursor, table_name):
    print(f"\n{'='*60}")
    print(f"📄 {table_name}")
    print('='*60)
    columns = get_columns(cursor, table_name)
    for col in columns:
        col_name, data_type, max_len, comment = col
        type_str = data_type
        if max_len:
            type_str = f"{data_type}({max_len})"
        comment_str = f" -- {comment}" if comment else ""
        print(f"  {col_name:<30} {type_str:<20}{comment_str}")


def main():
    conn = pyodbc.connect(DB_CONFIG)
    cursor = conn.cursor()

    # 核心表
    tables = [
        # 项目
        "Ht_Xmxx",         # 项目信息
        "Sb_Jbxx",         # 申报书基本信息
        "PGPS_XMPSXX",     # 项目评审信息
        # 专家
        "zjk_jbxx",       # 专家基本信息
        "ZJK_DRPWQK",     # 专家担任评委情况
        # 评审
        "PS_WLPS_ZJDL",   # 网评专家登录
        "PS_ZHPS_ZJDF",   # 综合评审打分
    ]

    for t in tables:
        try:
            show_table(cursor, t)
        except Exception as e:
            print(f"\n❌ {t}: {e}")

    conn.close()
    print(f"\n\n✅ 完成!")


if __name__ == "__main__":
    main()
