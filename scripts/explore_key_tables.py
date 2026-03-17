"""
详细探查关键业务表结构
"""
import os
import pymysql
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_REWARD_HOST", "your_host"),
    "port": int(os.getenv("DB_REWARD_PORT", 3306)),
    "user": os.getenv("DB_REWARD_USER", "your_user"),
    "password": os.getenv("DB_REWARD_PASSWORD", "your_password_here"),
}


def get_columns(cursor, db_name, table_name):
    cursor.execute(f"""
        SELECT 
            column_name,
            column_type,
            column_comment,
            column_key,
            is_nullable
        FROM information_schema.columns 
        WHERE table_schema = '{db_name}' AND table_name = '{table_name}'
        ORDER BY ordinal_position
    """)
    return cursor.fetchall()


def show_table(db_name, table_name):
    conn = pymysql.connect(**DB_CONFIG, database=db_name, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        cols = get_columns(cursor, db_name, table_name)
        print(f"\n📄 {db_name}.{table_name}")
        print("-" * 80)
        for c in cols:
            key = "🔑" if c["column_key"] == "PRI" else "  "
            null = "NULL" if c["is_nullable"] == "YES" else "NOT NULL"
            comment = ""
            if c["column_comment"]:
                comment = " -- " + str(c["column_comment"])
            print(f"{key} {c['column_name']:<30} {c['column_type']:<20} {null:<8}{comment}")
    conn.close()


def main():
    # === hbstanew 关键表 ===
    print("\n" + "="*60)
    print("📦 hbstanew - 学科、评审组")
    print("="*60)
    
    show_table("hbstanew", "sys_subject")           # 学科代码
    show_table("hbstanew", "sys_subject_wzb")      # 学科代码完整版
    show_table("hbstanew", "t_pszglqx")            # 评审组管理权限
    
    # === xmsbnew 关键表 ===
    print("\n" + "="*60)
    print("📦 xmsbnew - 业务信息")
    print("="*60)
    
    show_table("xmsbnew", "t_xm_ggjbxx")           # 项目基本信息
    show_table("xmsbnew", "t_xm_zywcr")           # 主要完成人
    show_table("xmsbnew", "t_xm_xmwcdwqk")         # 完成单位情况
    show_table("xmsbnew", "t_xm_cl")               # 项目材料
    show_table("xmsbnew", "t_xm_xsjg")             # 形式审查结果
    show_table("xmsbnew", "ps_xmpsxx")             # 项目评审信息
    
    # === zjknew 关键表 ===
    print("\n" + "="*60)
    print("📦 zjknew - 专家信息")
    print("="*60)
    
    show_table("zjknew", "t_zjxx")                 # 专家基本信息
    show_table("zjknew", "t_gzdwxx")               # 工作单位
    show_table("zjknew", "t_tjdwxx")               # 推荐单位
    show_table("zjknew", "t_jsly")                 # 技术领域
    
    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
