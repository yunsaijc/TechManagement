# 📊 数据模型

## 概述

本章节定义了智能分组与专家匹配服务使用的数据模型，包括项目模型、专家模型、学科模型和结果模型。

---

## 项目模型

### Project

项目基础信息

```python
class Project(BaseModel):
    """项目基础信息"""
    id: str                              # 项目ID (对应 Sb_Jbxx.id)
    xmmc: str                            # 项目名称
    gjc: Optional[str] = None            # 关键词
    ssxk1: Optional[str] = None         # 学科代码1 (如 0101)
    ssxk2: Optional[str] = None         # 学科代码2
    xmjj: Optional[str] = None          # 项目简介 (来自 Sb_Jj.xmjj)
    lxbj: Optional[str] = None          # 类型编辑 (来自 Sb_Jj.lxbj)
    cddw_mc: Optional[str] = None       # 承担单位名称
    year: Optional[str] = None           # 年度
    
    class Config:
        from_attributes = True
```

### ProjectQuality

项目质量评估结果

```python
class ProjectQuality(BaseModel):
    """项目质量评估结果"""
    project_id: str                      # 项目ID
    
    # 各维度得分 (0-100)
    innovation_score: float              # 创新性得分
    difficulty_score: float              # 技术难度得分
    value_score: float                  # 应用价值得分
    
    # 综合得分
    total_score: float                  # 综合得分 = (inno + diff + value) / 3
    comment: Optional[str] = None        # 简要评语
    
    class Config:
        from_attributes = True
```

---

## 学科模型

### Subject

学科代码信息（来自 kjjhxm_wlps.sys_xkfl）

```python
class Subject(BaseModel):
    """学科代码"""
    id: str                              # 主键
    parent_id: Optional[str] = None       # 父级ID (一级学科为空或"0")
    code: Optional[str] = None           # 学科代码 (如 01, 0101, 010101)
    name: Optional[str] = None           # 学科名称
    sort: Optional[float] = None         # 排序
    
    class Config:
        from_attributes = True
```

### SubjectLevel

学科层级枚举

```python
class SubjectLevel(int, Enum):
    """学科层级"""
    UNKNOWN = 0    # 未知
    LEVEL_1 = 1    # 一级学科 (代码长度2，如 01, 02)
    LEVEL_2 = 2    # 二级学科 (代码长度3，如 010, 011)
    LEVEL_3 = 3    # 三级学科 (代码长度≥4，如 0101, 0102)
```

---

## 专家模型

### Expert

专家基础信息

```python
class Expert(BaseModel):
    """专家基础信息"""
    id: str                              # 专家ID (对应 ZJK_ZJXX.ZJNO)
    xm: str                              # 姓名
    sxxk1: Optional[str] = None          # 熟悉学科1
    sxxk2: Optional[str] = None          # 熟悉学科2
    sxxk3: Optional[str] = None          # 熟悉学科3
    sxxk4: Optional[str] = None          # 熟悉学科4
    sxxk5: Optional[str] = None          # 熟悉学科5
    sxzy: Optional[str] = None           # 擅长专业
    yjly: Optional[str] = None           # 研究领域 (8000字符)
    lwlz: Optional[str] = None           # 论文论著 (5000字符)
    gzdw: Optional[str] = None          # 工作单位
    
    class Config:
        from_attributes = True
```

### ExpertProfile

专家画像

```python
class ExpertProfile(BaseModel):
    """专家画像"""
    expert_id: str                       # 专家ID
    
    # LLM 分析结果
    main_research_area: Optional[str] = None   # 主要研究方向
    sub_research_fields: List[str] = []       # 细分领域
    tech_expertise: List[str] = []            # 技术专长
    keywords: List[str] = []                   # 关键词
    
    # 向量表示
    vector: Optional[List[float]] = None        # 向量表示
    
    class Config:
        from_attributes = True
```

---

## 分组结果模型

### ProjectGroup

分组

```python
class ProjectGroup(BaseModel):
    """项目分组"""
    group_id: int                        # 分组ID (从1开始)
    
    # 学科信息
    subject_code: Optional[str] = None    # 学科代码 (如 0101)
    subject_name: Optional[str] = None    # 学科名称
    
    projects: List[ProjectInGroup] = []  # 分组内项目列表
    
    # 统计信息
    count: int                            # 项目数量
    avg_quality: float                    # 平均质量得分
    max_quality: float                    # 最高质量得分
    min_quality: float                    # 最低质量得分
    
    class Config:
        from_attributes = True


class ProjectInGroup(BaseModel):
    """分组内的项目"""
    project_id: str                       # 项目ID
    xmmc: str                             # 项目名称
    quality_score: float                  # 质量评分
    reason: Optional[str] = None          # 分配理由
    
    class Config:
        from_attributes = True
```

### GroupingResult

分组结果

```python
class GroupingResult(BaseModel):
    """分组结果"""
    id: str                               # 结果ID
    year: str                             # 年度
    
    groups: List[ProjectGroup] = []      # 分组列表
    
    # 统计信息
    statistics: GroupingStatistics         # 统计信息
    
    created_at: datetime                  # 创建时间
    
    class Config:
        from_attributes = True


class GroupingStatistics(BaseModel):
    """分组统计信息"""
    total_projects: int                   # 项目总数
    group_count: int                      # 分组数量
    avg_projects_per_group: float         # 平均每组项目数
    avg_quality_per_group: float          # 平均质量得分
    balance_score: float                  # 均衡度得分 (0-1)
    
    class Config:
        from_attributes = True
```

---

## 匹配结果模型

### ExpertAssignment

专家分配

```python
class ExpertAssignment(BaseModel):
    """专家分配"""
    project_id: str                       # 项目ID
    experts: List[AssignedExpert] = []    # 分配的专家列表
    
    class Config:
        from_attributes = True


class AssignedExpert(BaseModel):
    """已分配的专家"""
    expert_id: str                        # 专家ID
    xm: str                               # 姓名
    match_score: float                    # 匹配度
    reason: Optional[str] = None          # 匹配原因
    avoidance: Optional[AvoidanceInfo] = None  # 回避信息
    
    class Config:
        from_attributes = True


class AvoidanceInfo(BaseModel):
    """回避信息"""
    avoided: bool                         # 是否回避
    reason: Optional[str] = None          # 回避原因
    severity: str = "none"               # 严重程度: low/medium/high
    
    class Config:
        from_attributes = True
```

### MatchingResult

匹配结果

```python
class MatchingResult(BaseModel):
    """匹配结果"""
    id: str                               # 结果ID
    group_id: int                         # 分组ID
    
    matches: List[ExpertAssignment] = [] # 匹配列表
    
    # 统计信息
    statistics: MatchingStatistics        # 统计信息
    warnings: List[str] = []              # 警告信息
    
    created_at: datetime                  # 创建时间
    
    class Config:
        from_attributes = True


class MatchingStatistics(BaseModel):
    """匹配统计信息"""
    total_projects: int                   # 项目总数
    total_experts: int                    # 涉及专家总数
    avg_match_score: float                # 平均匹配度
    avoidance_detected: int               # 检测到的回避关系数
    experts_per_project: int              # 每项目专家数
    coverage_rate: float                  # 专家覆盖率
    
    class Config:
        from_attributes = True
```

---

## 完整结果模型

### FullGroupingResult

完整分组与匹配结果

```python
class FullGroupingResult(BaseModel):
    """完整分组与匹配结果"""
    id: str                               # 结果ID
    year: str                             # 年度
    category: Optional[str] = None         # 类别
    
    # 分组结果
    groups: List[ProjectGroup] = []        # 分组列表
    
    # 匹配结果 (按分组)
    matches: Dict[int, MatchingResult] = {}  # group_id -> 匹配结果
    
    # 统计信息
    statistics: FullStatistics             # 总体统计
    
    # 报告
    report: str                            # 可读报告
    
    created_at: datetime                  # 创建时间
    
    class Config:
        from_attributes = True


class FullStatistics(BaseModel):
    """完整统计信息"""
    total_projects: int                   # 项目总数
    total_groups: int                      # 分组数
    total_experts: int                    # 涉及专家总数
    avg_match_score: float                # 平均匹配度
    balance_score: float                  # 分组均衡度
    
    class Config:
        from_attributes = True
```

---

## 请求模型

### GroupingRequest

分组请求

```python
class GroupingRequest(BaseModel):
    """分组请求"""
    year: str                             # 年度 (必填)
    category: Optional[str] = None         # 奖种类别
    max_per_group: int = 15              # 每组目标项目数 (默认15)
    split_threshold: int = 30            # 超过此数量则拆分 (默认30)
    strategy: str = "balanced"           # 策略: balanced/quality
    
    # 质量权重 (创新性:技术难度:应用价值)
    quality_weights: List[float] = [1.0, 1.0, 1.0]
    
    class Config:
        from_attributes = True
```

### MatchingRequest

匹配请求

```python
class MatchingRequest(BaseModel):
    """匹配请求"""
    group_id: int                         # 分组ID (必填)
    experts_per_project: int = 5          # 每个项目分配专家数
    min_experts_per_group: int = 10      # 每组最少懂行专家
    avoid_relations: bool = True         # 是否回避关系
    max_reviews_per_expert: int = 5      # 每位专家最大评审数
    
    class Config:
        from_attributes = True
```

### FullGroupingRequest

完整分组与匹配请求

```python
class FullGroupingRequest(BaseModel):
    """完整分组与匹配请求"""
    year: str                             # 年度 (必填)
    category: Optional[str] = None         # 奖种类别
    max_per_group: int = 15              # 每组目标项目数
    split_threshold: int = 30            # 超过此数量则拆分
    experts_per_project: int = 5          # 每个项目分配专家数
    min_experts_per_group: int = 10       # 每组最少懂行专家
    avoid_relations: bool = True          # 是否回避关系
    max_reviews_per_expert: int = 5       # 每位专家最大评审数
    
    class Config:
        from_attributes = True
```

---

## 相关文档

- [服务概述 →](01-overview.md)
- [分组子服务 →](02-grouping.md)
- [专家匹配子服务 →](03-matching.md)
- [API 接口 →](05-api.md)
