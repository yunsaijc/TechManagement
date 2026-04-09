"""
评审结果存储层

负责评审结果的持久化存储和查询。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.models.evaluation import EvaluationResult


class EvaluationStorage:
    """评审结果存储层
    
    负责：
    1. 保存评审结果
    2. 查询历史记录
    3. 管理评审报告
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """初始化存储层
        
        Args:
            storage_dir: 存储目录，默认为 data/evaluation/
        """
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path("data/evaluation")
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.chat_index_dir = self.storage_dir / "chat_indexes"
        self.chat_index_dir.mkdir(parents=True, exist_ok=True)
    
    async def save(self, result: EvaluationResult) -> str:
        """保存评审结果
        
        Args:
            result: 评审结果
            
        Returns:
            str: 保存的文件路径
        """
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{result.project_id}_{timestamp}.json"
        filepath = self.storage_dir / filename
        
        # 转换为字典
        data = result.model_dump()
        
        # 保存
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        
        return str(filepath)
    
    async def load(self, file_path: str) -> Optional[EvaluationResult]:
        """加载评审结果
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[EvaluationResult]: 评审结果
        """
        filepath = Path(file_path)
        if not filepath.exists():
            return None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return EvaluationResult(**data)

    async def get_by_evaluation_id(self, evaluation_id: str) -> Optional[EvaluationResult]:
        """按评审记录ID查询结果"""
        files = list(self.storage_dir.glob("*.json"))
        for file in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            result = await self.load(str(file))
            if result and result.evaluation_id == evaluation_id:
                return result
        return None

    async def set_chat_ready(self, evaluation_id: str, chat_ready: bool) -> bool:
        """按评审记录ID更新 chat_ready 状态"""
        files = list(self.storage_dir.glob("*.json"))
        for file in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("evaluation_id") != evaluation_id:
                continue
            data["chat_ready"] = chat_ready
            with open(file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            return True
        return False
    
    async def get_latest(self, project_id: str) -> Optional[EvaluationResult]:
        """获取项目最新的评审结果
        
        Args:
            project_id: 项目ID
            
        Returns:
            Optional[EvaluationResult]: 最新评审结果
        """
        # 查找该项目的所有评审文件
        pattern = f"{project_id}_*.json"
        files = list(self.storage_dir.glob(pattern))
        
        if not files:
            return None
        
        # 按修改时间排序，取最新的
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        return await self.load(str(files[0]))
    
    async def list_by_project(self, project_id: str) -> List[EvaluationResult]:
        """获取项目的所有评审记录
        
        Args:
            project_id: 项目ID
            
        Returns:
            List[EvaluationResult]: 评审记录列表
        """
        pattern = f"{project_id}_*.json"
        files = list(self.storage_dir.glob(pattern))
        
        results = []
        for file in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            result = await self.load(str(file))
            if result:
                results.append(result)
        
        return results
    
    async def delete(self, project_id: str) -> int:
        """删除项目的所有评审记录
        
        Args:
            project_id: 项目ID
            
        Returns:
            int: 删除的记录数
        """
        pattern = f"{project_id}_*.json"
        files = list(self.storage_dir.glob(pattern))
        
        count = 0
        for file in files:
            file.unlink()
            count += 1
        
        return count
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取评审统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        files = list(self.storage_dir.glob("*.json"))
        
        grade_count = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
        total_score = 0.0
        
        for file in files:
            result = await self.load(str(file))
            if result:
                grade_count[result.grade] += 1
                total_score += result.overall_score
        
        return {
            "total": len(files),
            "grade_distribution": grade_count,
            "average_score": round(total_score / len(files), 2) if files else 0,
        }

    async def save_chat_index(self, evaluation_id: str, payload: Dict[str, Any]) -> str:
        """保存聊天索引"""
        path = self.chat_index_dir / f"{evaluation_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return str(path)

    async def load_chat_index(self, evaluation_id: str) -> Optional[Dict[str, Any]]:
        """加载聊天索引"""
        path = self.chat_index_dir / f"{evaluation_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
