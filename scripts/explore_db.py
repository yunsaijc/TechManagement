"""
数据库表结构探查脚本 - 精简版
只输出表名列表，便于快速了解数据库内容
"""
import os
import pymysql
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置 - 从环境变量读取
DB_CONFIG = {
    "host": os.getenv("DB_REWARD_HOST", "your_host"),
    "port": int(os.getenv("DB_REWARD_PORT", 3306)),
    "user": os.getenv("DB_REWARD_USER", "your_user"),
    "password": os.getenv("DB_REWARD_PASSWORD", "your_password_here"),
}

DATABASES = {
    os.getenv("DB_REWARD_DATABASE", "your_database"): "系统框架配置（用户、角色、菜单、权限、字典等）",
    "hbstanew": "学科、评审组",
    "xmsbnew": "业务信息",
    "zjknew": "专家信息",
}


def get_tables(cursor, db_name):
    """获取数据库所有表"""
    cursor.execute(f"""
        SELECT table_name, table_comment 
        FROM information_schema.tables 
        WHERE table_schema = '{db_name}'
    """)
    return cursor.fetchall()


def main():
    """主函数"""
    print(f"\n🔍 数据库表结构探查\n{'='*60}\n")
    
    for db_name, description in DATABASES.items():
        try:
            conn = pymysql.connect(
                **DB_CONFIG,
                database=db_name,
                cursorclass=pymysql.cursors.DictCursor
            )
            with conn.cursor() as cursor:
                tables = get_tables(cursor, db_name)
                print(f"📦 {db_name} - {description}")
                print(f"   表数量: {len(tables)}")
                for t in tables:
                    comment = f" ({t['table_comment']})" if t['table_comment'] else ""
                    print(f"   - {t['table_name']}{comment}")
                print()
            conn.close()
        except Exception as e:
            print(f"❌ {db_name}: {e}\n")
    
    print(f"{'='*60}\n✅ 完成!")


if __name__ == "__main__":
    main()
