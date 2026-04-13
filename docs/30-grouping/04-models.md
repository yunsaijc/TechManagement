# 📊 数据模型

## 概述

本章节定义智能分组与专家匹配服务使用的数据模型。当前分组模型以项目语义为核心，不再依赖质量评价。

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
    ssxk1: Optional[str] = None          # 学科代码1
    ssxk2: Optional[str] = None          # 学科代码2
    xmjj: Optional[str] = None           # 项目简介 (可选)
    lxbj: Optional[str] = None           # 类型编辑
    cddw_mc: Optional[str] = None        # 承担单位名称
    year: Optional[str] = None           # 年度

    class Config:
        from_attributes = True
```

### ProjectSemantic

项目语义分析结果

```python
class ProjectSemantic(BaseModel):
    """项目语义分析结果"""
    project_id: str                      # 项目ID
    theme: Optional[str] = None          # 主题概括
    research_object: Optional[str] = None  # 研究对象
    method: Optional[str] = None         # 方法/技术路线
    scenario: Optional[str] = None       # 应用场景/目标
    keywords: List[str] = []             # 关键词
    confidence: float = 0.0              # 语义置信度
    needs_review: bool = False           # 是否需人工复核

    class Config:
        from_attributes = True
```

---

## 学科模型

### Subject

学科代码信息（仅作辅助兼容）

```python
class Subject(BaseModel):
    """学科代码"""
    id: str                              # 主键
    parent_id: Optional[str] = None      # 父级ID
    code: Optional[str] = None           # 学科代码
    name: Optional[str] = None           # 学科名称
    sort: Optional[float] = None         # 排序

    class Config:
        from_attributes = True
```

### SubjectLevel

代码体系枚举

```python
class SubjectLevel(int, Enum):
    """代码体系"""
    UNKNOWN = 0      # 未知
    LETTER_CODE = 1  # 字母开头代码体系
    NUMBER_CODE = 2  # 7位数字代码体系
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
    yjly: Optional[str] = None           # 研究领域
    lwlz: Optional[str] = None           # 论文论著
    gzdw: Optional[str] = None           # 工作单位

    class Config:
        from_attributes = True
```

### ExpertProfile

专家画像

```python
class ExpertProfile(BaseModel):
    """专家画像"""
    expert_id: str                       # 专家ID
    main_research_area: Optional[str] = None   # 主要研究方向
    sub_research_fields: List[str] = []       # 细分领域
    tech_expertise: List[str] = []            # 技术专长
    keywords: List[str] = []                 # 关键词
    vector: Optional[List[float]] = None      # 向量表示

    class Config:
        from_attributes = True
```

---

## 分组结果模型

### ProjectGroup

```python
class ProjectGroup(BaseModel):
    """项目分组"""
    group_id: int                        # 分组ID
    group_name: str                      # 组名（主题名）
    group_reason: Optional[str] = None   # 组形成原因
    projects: List[ProjectInGroup] = []  # 分组内项目列表
    count: int                           # 项目数量
    needs_review: bool = False           # 是否建议人工复核

    class Config:
        from_attributes = True


class ProjectInGroup(BaseModel):
    """分组内的项目"""
    project_id: str                       # 项目ID
    xmmc: str                             # 项目名称
    project_reason: Optional[str] = None  # 项目归组理由
    confidence: float = 0.0               # 归组置信度

    class Config:
        from_attributes = True
```

### GroupingResult

```python
class GroupingResult(BaseModel):
    """分组结果"""
    id: str                               # 结果ID
    year: str                             # 年度
    groups: List[ProjectGroup] = []       # 分组列表
    statistics: GroupingStatistics        # 统计信息
    created_at: datetime                  # 创建时间

    class Config:
        from_attributes = True


class GroupingStatistics(BaseModel):
    """分组统计信息"""
    total_projects: int                   # 项目总数
    group_count: int                      # 分组数量
    avg_projects_per_group: float         # 平均每组项目数
    small_group_count: int                # 小组数量
    review_count: int                     # 建议复核数量

    class Config:
        from_attributes = True
```

---

## 匹配结果模型

### ExpertAssignment

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
    severity: str = "none"               # 严重程度

    class Config:
        from_attributes = True
```

### MatchingResult

```python
class MatchingResult(BaseModel):
    """匹配结果"""
    id: str                               # 结果ID
    group_id: int                         # 分组ID
    matches: List[ExpertAssignment] = []   # 匹配列表

    class Config:
        from_attributes = True
```
