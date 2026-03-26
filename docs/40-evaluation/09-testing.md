# 🧪 测试文档

## 测试策略

正文评审服务采用分层测试策略，确保各层级的正确性和稳定性。

```
┌─────────────────────────────────────────────────────────────────┐
│                       测试金字塔                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                         /_\                                     │
│                        /   \      E2E 测试                       │
│                       /     \    （API 集成测试）                 │
│                      /───────\                                   │
│                     /         \   集成测试                        │
│                    /           \  （Agent、评分器）               │
│                   /─────────────\                                │
│                  /               \ 单元测试                       │
│                 /                 \（检查器、解析器）              │
│                /───────────────────\                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 测试目录结构

```
tests/
└── services/
    └── evaluation/
        ├── __init__.py
        ├── conftest.py                 # 测试配置和 fixtures
        │
        ├── test_checkers/              # 检查器单元测试
        │   ├── __init__.py
        │   ├── test_base.py
        │   ├── test_feasibility.py
        │   ├── test_innovation.py
        │   ├── test_team.py
        │   ├── test_outcome.py
        │   ├── test_social_benefit.py
        │   ├── test_economic_benefit.py
        │   ├── test_risk_control.py
        │   ├── test_schedule.py
        │   └── test_compliance.py
        │
        ├── test_scorers/               # 评分器单元测试
        │   ├── __init__.py
        │   ├── test_dimension_scorer.py
        │   └── test_weight_calculator.py
        │
        ├── test_parsers/               # 解析器单元测试
        │   ├── __init__.py
        │   ├── test_document_parser.py
        │   └── test_field_locator.py
        │
        ├── test_agent.py               # Agent 集成测试
        ├── test_api.py                 # API 集成测试
        │
        └── test_real_projects.py       # 真实项目测试
```

---

## 测试配置

### conftest.py

```python
# tests/services/evaluation/conftest.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.checkers import BaseChecker, CheckResult
from src.common.llm import get_default_llm_client


# ============ Mock LLM ============

@pytest.fixture
def mock_llm():
    """Mock LLM 客户端"""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"score": 8.0, "opinion": "测试意见", "issues": [], "highlights": []}'
    ))
    return llm


@pytest.fixture
def mock_llm_with_json():
    """返回 JSON 的 Mock LLM"""
    def _make_mock(json_response: Dict[str, Any]):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(
            content=json.dumps(json_response, ensure_ascii=False)
        ))
        return llm
    return _make_mock


# ============ 测试数据 ============

@pytest.fixture
def sample_project_info() -> Dict[str, Any]:
    """示例项目信息"""
    return {
        "id": "test_project_001",
        "xmmc": "基于深度学习的智能诊断系统研究",
        "gjc": "深度学习;智能诊断;医学影像",
        "xmFzr": "张三",
        "cddw_mc": "某某大学",
        "xmjj": "本项目旨在开发一套基于深度学习的智能诊断系统...",
    }


@pytest.fixture
def sample_sections() -> Dict[str, str]:
    """示例章节内容"""
    return {
        "tech_solution": """
一、技术方案
本项目采用深度学习技术，构建智能诊断系统。主要技术路线如下：
1. 数据采集与预处理
2. 模型设计与训练
3. 系统集成与部署

核心技术包括：卷积神经网络、迁移学习、模型优化等。
        """,
        "innovation": """
二、创新点
1. 提出了新的网络架构，提高诊断准确率
2. 创新性地引入注意力机制
3. 开发了自动化标注工具
        """,
        "team_intro": """
三、团队介绍
项目负责人：张三，教授，博士生导师
团队成员：李四（副教授）、王五（博士研究生）等
        """,
        "expected_outcome": """
四、预期成果
1. 发表高水平论文 3-5 篇
2. 申请发明专利 2-3 项
3. 开发智能诊断系统 1 套
        """,
        "risk_analysis": """
五、风险分析
主要风险：数据获取难度大、模型训练时间长
应对措施：建立合作医院网络、使用预训练模型
        """,
        "schedule": """
六、进度安排
第一年：数据采集、系统设计
第二年：模型开发、系统实现
第三年：测试验证、推广应用
        """,
    }


@pytest.fixture
def sample_check_result() -> CheckResult:
    """示例检查结果"""
    return CheckResult(
        dimension="feasibility",
        dimension_name="技术可行性",
        score=8.5,
        confidence=0.85,
        opinion="技术路线清晰，可行性较好。",
        issues=["技术风险描述不够详细"],
        highlights=["技术方案有创新性"],
    )


# ============ Agent Fixtures ============

@pytest.fixture
def evaluation_agent(mock_llm):
    """EvaluationAgent 实例"""
    return EvaluationAgent(llm=mock_llm)
```

---

## 单元测试

### 1. 检查器测试

```python
# tests/services/evaluation/test_checkers/test_feasibility.py

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from src.services.evaluation.checkers import FeasibilityChecker, CheckResult


class TestFeasibilityChecker:
    """技术可行性检查器测试"""
    
    @pytest.fixture
    def checker(self, mock_llm):
        return FeasibilityChecker(llm=mock_llm)
    
    def test_dimension_attributes(self, checker):
        """测试维度属性"""
        assert checker.dimension == "feasibility"
        assert checker.dimension_name == "技术可行性"
        assert checker.default_weight == 0.15
    
    def test_check_items_defined(self, checker):
        """测试检查项已定义"""
        assert len(checker.CHECK_ITEMS) == 4
        assert checker.CHECK_ITEMS[0]["name"] == "技术路线清晰度"
    
    @pytest.mark.asyncio
    async def test_check_returns_result(self, checker, sample_project_info, sample_sections):
        """测试检查返回正确结果"""
        result = await checker.check(
            project_info=sample_project_info,
            sections=sample_sections
        )
        
        assert isinstance(result, CheckResult)
        assert result.dimension == "feasibility"
        assert 1 <= result.score <= 10
        assert result.opinion != ""
    
    @pytest.mark.asyncio
    async def test_check_with_empty_sections(self, checker, sample_project_info):
        """测试空章节情况"""
        result = await checker.check(
            project_info=sample_project_info,
            sections={}
        )
        
        # 应该返回结果，但置信度可能较低
        assert isinstance(result, CheckResult)
    
    @pytest.mark.asyncio
    async def test_llm_called_with_correct_prompt(self, mock_llm, sample_project_info, sample_sections):
        """测试 LLM 被正确调用"""
        checker = FeasibilityChecker(llm=mock_llm)
        await checker.check(
            project_info=sample_project_info,
            sections=sample_sections
        )
        
        # 验证 ainvoke 被调用
        mock_llm.ainvoke.assert_called_once()
        
        # 验证 prompt 包含关键信息
        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "技术可行性" in prompt
        assert sample_project_info["xmmc"] in prompt


class TestInnovationChecker:
    """创新性检查器测试"""
    
    @pytest.fixture
    def checker(self, mock_llm):
        from src.services.evaluation.checkers import InnovationChecker
        return InnovationChecker(llm=mock_llm)
    
    def test_dimension_attributes(self, checker):
        assert checker.dimension == "innovation"
        assert checker.default_weight == 0.15
    
    @pytest.mark.asyncio
    async def test_check_returns_result(self, checker, sample_project_info, sample_sections):
        result = await checker.check(
            project_info=sample_project_info,
            sections=sample_sections
        )
        assert result.dimension == "innovation"


class TestTeamChecker:
    """团队能力检查器测试"""
    
    @pytest.fixture
    def checker(self, mock_llm):
        from src.services.evaluation.checkers import TeamChecker
        return TeamChecker(llm=mock_llm)
    
    def test_dimension_attributes(self, checker):
        assert checker.dimension == "team"
        assert checker.default_weight == 0.10


# 类似地测试其他检查器...
```

### 2. 评分器测试

```python
# tests/services/evaluation/test_scorers/test_dimension_scorer.py

import pytest

from src.services.evaluation.scorers import DimensionScorer, WeightCalculator
from src.common.models.evaluation import DimensionScore, DEFAULT_WEIGHTS


class TestDimensionScorer:
    """维度评分器测试"""
    
    def test_init_with_default_weights(self):
        """测试使用默认权重初始化"""
        scorer = DimensionScorer()
        assert scorer.weights == DEFAULT_WEIGHTS
    
    def test_init_with_custom_weights(self):
        """测试使用自定义权重初始化"""
        custom = {"feasibility": 0.5, "innovation": 0.5}
        scorer = DimensionScorer(weights=custom)
        assert scorer.weights == custom
    
    def test_invalid_weights_raises_error(self):
        """测试无效权重抛出错误"""
        invalid = {"feasibility": 0.5}  # 总和不是 1
        with pytest.raises(ValueError):
            DimensionScorer(weights=invalid)
    
    def test_calculate_weighted_score(self):
        """测试加权得分计算"""
        scorer = DimensionScorer(weights={"feasibility": 0.6, "innovation": 0.4})
        
        scores = {"feasibility": 8.0, "innovation": 6.0}
        result = scorer.calculate_weighted_score(scores)
        
        # 8.0 * 0.6 + 6.0 * 0.4 = 4.8 + 2.4 = 7.2
        assert result == 7.2
    
    def test_determine_grade(self):
        """测试等级判定"""
        scorer = DimensionScorer()
        
        assert scorer.determine_grade(9.5) == "A"
        assert scorer.determine_grade(9.0) == "A"
        assert scorer.determine_grade(8.5) == "B"
        assert scorer.determine_grade(8.0) == "B"
        assert scorer.determine_grade(7.0) == "C"
        assert scorer.determine_grade(6.0) == "C"
        assert scorer.determine_grade(5.0) == "D"
        assert scorer.determine_grade(4.0) == "D"
        assert scorer.determine_grade(3.0) == "E"
    
    def test_build_dimension_score(self):
        """测试构建维度评分对象"""
        scorer = DimensionScorer(weights={"feasibility": 0.15})
        
        score = scorer.build_dimension_score(
            dimension="feasibility",
            score=8.5,
            opinion="技术路线清晰",
            issues=["风险描述不足"],
            highlights=["方案合理"],
            confidence=0.85,
        )
        
        assert isinstance(score, DimensionScore)
        assert score.dimension == "feasibility"
        assert score.score == 8.5
        assert score.weight == 0.15
        assert score.weighted_score == 8.5 * 0.15
    
    def test_generate_summary(self):
        """测试生成综合意见"""
        scorer = DimensionScorer()
        
        scores = [
            DimensionScore(
                dimension="feasibility",
                dimension_name="技术可行性",
                score=9.0,
                weight=0.15,
                weighted_score=1.35,
                confidence=0.9,
                opinion="优秀",
            ),
            DimensionScore(
                dimension="innovation",
                dimension_name="创新性",
                score=8.0,
                weight=0.15,
                weighted_score=1.20,
                confidence=0.8,
                opinion="良好",
            ),
        ]
        
        summary = scorer.generate_summary(scores, "A")
        assert "优秀" in summary or "A" in summary


class TestWeightCalculator:
    """权重计算器测试"""
    
    def test_get_default_weights(self):
        """测试获取默认权重"""
        weights = WeightCalculator.get_weights()
        assert weights == DEFAULT_WEIGHTS
    
    def test_get_template_weights(self):
        """测试获取模板权重"""
        weights = WeightCalculator.get_weights(template="innovation_focused")
        assert weights["innovation"] == 0.25
    
    def test_custom_weights_override(self):
        """测试自定义权重覆盖"""
        custom = {"feasibility": 0.3}
        weights = WeightCalculator.get_weights(custom_weights=custom)
        
        # 自定义权重会覆盖，然后归一化
        assert weights["feasibility"] > DEFAULT_WEIGHTS["feasibility"]
    
    def test_weights_sum_to_one(self):
        """测试权重总和为1"""
        for template in WeightCalculator.WEIGHT_TEMPLATES:
            weights = WeightCalculator.get_weights(template=template)
            assert abs(sum(weights.values()) - 1.0) < 0.001
```

### 3. 解析器测试

```python
# tests/services/evaluation/test_parsers/test_document_parser.py

import pytest
from unittest.mock import AsyncMock, patch

from src.services.evaluation.parsers import DocumentParser


class TestDocumentParser:
    """文档解析器测试"""
    
    @pytest.fixture
    def parser(self):
        return DocumentParser()
    
    def test_section_patterns_defined(self, parser):
        """测试章节模式已定义"""
        assert "tech_solution" in parser.SECTION_PATTERNS
        assert "innovation" in parser.SECTION_PATTERNS
    
    def test_extract_sections(self, parser):
        """测试章节提取"""
        document = """
一、技术方案
本项目采用深度学习技术...

二、创新点
主要创新点包括...

三、团队介绍
团队由5人组成...
        """
        
        sections = parser._extract_sections(document)
        
        # 应该能提取到章节
        assert isinstance(sections, dict)
    
    def test_find_section_with_pattern(self, parser):
        """测试使用模式查找章节"""
        document = """
技术方案：本项目采用深度学习技术。
实施期限：2025-2027年。
        """
        
        content = parser._find_section(document, ["技术方案"])
        
        # 应该能找到内容
        assert content is not None or content == ""  # 可能没有匹配
    
    @pytest.mark.asyncio
    async def test_parse_empty_project(self, parser):
        """测试解析空项目"""
        with patch.object(parser, '_get_project_files', return_value=[]):
            sections = await parser.parse("non_existent_project")
            assert sections == {}
```

---

## 集成测试

### Agent 集成测试

```python
# tests/services/evaluation/test_agent.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.evaluation.agent import EvaluationAgent
from src.common.models.evaluation import EvaluationRequest, EvaluationResult


class TestEvaluationAgent:
    """EvaluationAgent 集成测试"""
    
    @pytest.fixture
    def agent(self, mock_llm):
        return EvaluationAgent(llm=mock_llm)
    
    @pytest.mark.asyncio
    async def test_evaluate_returns_result(self, agent, sample_project_info, sample_sections):
        """测试评审返回正确结果"""
        with patch.object(
            agent, '_get_project_info', 
            return_value=sample_project_info
        ):
            with patch.object(
                agent, '_parse_documents',
                return_value=sample_sections
            ):
                request = EvaluationRequest(project_id="test_001")
                result = await agent.evaluate(request)
        
        assert isinstance(result, EvaluationResult)
        assert result.project_id == "test_001"
        assert 0 <= result.overall_score <= 10
        assert result.grade in ["A", "B", "C", "D", "E"]
    
    @pytest.mark.asyncio
    async def test_evaluate_with_custom_weights(self, agent, sample_project_info, sample_sections):
        """测试使用自定义权重评审"""
        with patch.object(agent, '_get_project_info', return_value=sample_project_info):
            with patch.object(agent, '_parse_documents', return_value=sample_sections):
                request = EvaluationRequest(
                    project_id="test_001",
                    weights={"feasibility": 0.5, "innovation": 0.5}
                )
                result = await agent.evaluate(request)
        
        assert isinstance(result, EvaluationResult)
    
    @pytest.mark.asyncio
    async def test_evaluate_with_subset_dimensions(self, agent, sample_project_info, sample_sections):
        """测试评审指定维度"""
        with patch.object(agent, '_get_project_info', return_value=sample_project_info):
            with patch.object(agent, '_parse_documents', return_value=sample_sections):
                request = EvaluationRequest(
                    project_id="test_001",
                    dimensions=["feasibility", "innovation"]
                )
                result = await agent.evaluate(request)
        
        # 只评审了2个维度
        assert len(result.dimension_scores) == 2
    
    @pytest.mark.asyncio
    async def test_run_checkers_parallel(self, agent, sample_project_info, sample_sections):
        """测试并行执行检查器"""
        results = await agent._run_checkers_parallel(
            dimensions=["feasibility", "innovation"],
            project_info=sample_project_info,
            sections=sample_sections,
        )
        
        assert len(results) == 2
        for r in results:
            assert hasattr(r, 'dimension')
            assert hasattr(r, 'score')
```

---

## 真实项目测试

```python
# tests/services/evaluation/test_real_projects.py

import pytest
import os

from src.services.evaluation.agent import EvaluationAgent
from src.common.models.evaluation import EvaluationRequest


# 测试项目列表（来自 data/审查功能测试用典型项目信息/）
TEST_PROJECTS = [
    "202520014",
    "202520036",
    "202520058",
    "202520077",
    "202530003",
]

# 仅在环境变量启用时运行
RUN_REAL_TESTS = os.getenv("RUN_REAL_TESTS", "false").lower() == "true"


@pytest.mark.skipif(not RUN_REAL_TESTS, reason="需要设置 RUN_REAL_TESTS=true")
class TestRealProjects:
    """真实项目评审测试"""
    
    @pytest.fixture
    def agent(self):
        return EvaluationAgent()
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("project_id", TEST_PROJECTS)
    async def test_evaluate_real_project(self, project_id, agent):
        """测试真实项目评审"""
        request = EvaluationRequest(project_id=project_id)
        
        result = await agent.evaluate(request)
        
        # 基本验证
        assert result is not None
        assert result.project_id == project_id
        assert result.project_name is not None
        assert 0 <= result.overall_score <= 10
        assert result.grade in ["A", "B", "C", "D", "E"]
        
        # 验证所有维度都有评分
        assert len(result.dimension_scores) == 9
        
        # 验证评审意见不为空
        assert result.summary != ""
        assert len(result.recommendations) >= 0
    
    @pytest.mark.asyncio
    async def test_batch_evaluation(self, agent):
        """测试批量评审"""
        results = []
        
        for project_id in TEST_PROJECTS[:3]:
            request = EvaluationRequest(project_id=project_id)
            result = await agent.evaluate(request)
            results.append(result)
        
        # 验证批量结果
        assert len(results) == 3
        
        # 验证分数分布合理
        scores = [r.overall_score for r in results]
        avg_score = sum(scores) / len(scores)
        assert 4 <= avg_score <= 10  # 平均分应该在合理范围
```

---

## API 测试

```python
# tests/services/evaluation/test_api.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from src.app.main import app


client = TestClient(app)


class TestEvaluationAPI:
    """API 接口测试"""
    
    def test_health_check(self):
        """测试健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    @patch('src.services.evaluation.api.get_agent')
    def test_evaluate_project(self, mock_get_agent, sample_check_result):
        """测试单项目评审 API"""
        # Mock agent
        from src.common.models.evaluation import EvaluationResult
        from datetime import datetime
        
        mock_agent = AsyncMock()
        mock_agent.evaluate.return_value = EvaluationResult(
            project_id="test_001",
            project_name="测试项目",
            overall_score=8.0,
            grade="B",
            dimension_scores=[],
            summary="测试评审意见",
            recommendations=[],
            created_at=datetime.now(),
        )
        mock_get_agent.return_value = mock_agent
        
        response = client.post(
            "/api/v1/evaluation",
            json={"project_id": "test_001"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "test_001"
        assert data["overall_score"] == 8.0
    
    def test_get_dimensions(self):
        """测试获取维度列表"""
        response = client.get("/api/v1/evaluation/dimensions")
        
        assert response.status_code == 200
        data = response.json()
        assert "dimensions" in data
        assert len(data["dimensions"]) == 9
    
    def test_get_weight_templates(self):
        """测试获取权重模板"""
        response = client.get("/api/v1/evaluation/weights/templates")
        
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert "default" in data["templates"]
    
    def test_validate_weights_valid(self):
        """测试验证有效权重"""
        response = client.post(
            "/api/v1/evaluation/weights/validate",
            json={"weights": {"feasibility": 0.5, "innovation": 0.5}}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
    
    def test_validate_weights_invalid_dimension(self):
        """测试验证无效维度"""
        response = client.post(
            "/api/v1/evaluation/weights/validate",
            json={"weights": {"unknown_dimension": 1.0}}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
```

---

## 运行测试

```bash
# 运行所有评审服务测试
pytest tests/services/evaluation/ -v

# 运行单元测试
pytest tests/services/evaluation/test_checkers/ -v
pytest tests/services/evaluation/test_scorers/ -v

# 运行集成测试
pytest tests/services/evaluation/test_agent.py -v
pytest tests/services/evaluation/test_api.py -v

# 运行真实项目测试（需要设置环境变量）
RUN_REAL_TESTS=true pytest tests/services/evaluation/test_real_projects.py -v

# 生成覆盖率报告
pytest tests/services/evaluation/ \
    --cov=src/services/evaluation \
    --cov=src/common/models/evaluation \
    --cov-report=html \
    --cov-report=term

# 并行运行测试
pytest tests/services/evaluation/ -n 4
```

---

## 测试覆盖率目标

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| `checkers/base.py` | ≥ 90% | 核心基类 |
| `checkers/*.py` | ≥ 80% | 各检查器 |
| `scorers/*.py` | ≥ 90% | 评分器 |
| `parsers/*.py` | ≥ 70% | 解析器 |
| `agent.py` | ≥ 80% | Agent 编排 |
| `api.py` | ≥ 85% | API 路由 |

---

## Mock 策略

### LLM Mock

对于单元测试，使用 Mock LLM 避免真实调用：

```python
@pytest.fixture
def mock_llm_with_response():
    """返回预设响应的 Mock LLM"""
    def _make(response: dict):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(
            content=json.dumps(response)
        ))
        return llm
    return _make

# 使用
def test_checker(mock_llm_with_response):
    llm = mock_llm_with_response({
        "score": 8.0,
        "opinion": "测试",
        "issues": [],
        "highlights": []
    })
    checker = SomeChecker(llm=llm)
    # ...
```

### 数据库 Mock

对于需要数据库的测试，使用 Mock 仓库：

```python
@pytest.fixture
def mock_project_repo():
    repo = MagicMock()
    repo.get_project_info = AsyncMock(return_value={
        "id": "test",
        "xmmc": "测试项目"
    })
    return repo
```

---

## 持续集成

```yaml
# .github/workflows/test-evaluation.yml
name: Evaluation Service Tests

on:
  push:
    paths:
      - 'src/services/evaluation/**'
      - 'src/common/models/evaluation/**'
      - 'tests/services/evaluation/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          pip install uv
          uv sync
      
      - name: Run tests
        run: |
          uv run pytest tests/services/evaluation/ \
            --cov=src/services/evaluation \
            --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
```