"""
专家数据访问层
"""
from typing import List, Optional
from src.common.database.connection import get_reward_connection
from src.common.database.models.reward import Expert, WorkUnit, RecommendUnit, Subject


class ExpertRepository:
    """专家数据访问"""
    
    def list_by_subject(self, subject_code: str) -> List[Expert]:
        """按学科查询专家"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM t_zjxx 
                    WHERE SXXK1 = %s AND del_flag = '0'
                """, (subject_code,))
                rows = cursor.fetchall()
                return [Expert(**dict(row)) for row in rows]
        finally:
            conn.close()
    
    def get_by_zjno(self, zjno: str) -> Optional[Expert]:
        """根据专家号查询"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM t_zjxx WHERE ZJNO = %s
                """, (zjno,))
                row = cursor.fetchone()
                if row:
                    return Expert(**dict(row))
                return None
        finally:
            conn.close()
    
    def list_all(self, limit: int = 100) -> List[Expert]:
        """查询所有专家（带分页）"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM t_zjxx 
                    WHERE del_flag = '0'
                    LIMIT %s
                """, (limit,))
                rows = cursor.fetchall()
                return [Expert(**dict(row)) for row in rows]
        finally:
            conn.close()


class WorkUnitRepository:
    """工作单位数据访问"""
    
    def get_by_id(self, gzdwid: str) -> Optional[WorkUnit]:
        """根据ID查询工作单位"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM t_gzdwxx WHERE GZDWID = %s
                """, (gzdwid,))
                row = cursor.fetchone()
                if row:
                    return WorkUnit(**dict(row))
                return None
        finally:
            conn.close()
    
    def list_all(self) -> List[WorkUnit]:
        """查询所有工作单位"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM t_gzdwxx")
                rows = cursor.fetchall()
                return [WorkUnit(**dict(row)) for row in rows]
        finally:
            conn.close()


class RecommendUnitRepository:
    """推荐单位数据访问"""
    
    def list_all(self) -> List[RecommendUnit]:
        """查询所有推荐单位"""
        conn = get_reward_connection("zjknew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM t_tjdwxx")
                rows = cursor.fetchall()
                return [RecommendUnit(**dict(row)) for row in rows]
        finally:
            conn.close()


class SubjectRepository:
    """学科数据访问"""
    
    def list_all(self) -> List[Subject]:
        """查询所有学科"""
        conn = get_reward_connection("hbstanew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM sys_subject WHERE del_flag = 0")
                rows = cursor.fetchall()
                return [Subject(**dict(row)) for row in rows]
        finally:
            conn.close()
    
    def get_by_code(self, code: str) -> Optional[Subject]:
        """根据代码查询学科"""
        conn = get_reward_connection("hbstanew")
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM sys_subject WHERE code = %s
                """, (code,))
                row = cursor.fetchone()
                if row:
                    return Subject(**dict(row))
                return None
        finally:
            conn.close()
