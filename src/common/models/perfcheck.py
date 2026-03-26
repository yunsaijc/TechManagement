from typing import List, Optional, Union
from pydantic import BaseModel

class ResearchContent(BaseModel):
    id: str
    text: str

class PerformanceTarget(BaseModel):
    id: str
    type: str
    subtype: Optional[str] = None
    text: str = ""
    source: str = ""
    value: Union[float, str]
    unit: str
    constraint: str = "≥"

class BudgetItem(BaseModel):
    type: str
    amount: float

class Budget(BaseModel):
    total: float
    items: List[BudgetItem]

class UnitBudgetAllocation(BaseModel):
    unit_name: str
    type: str
    amount: float

class Organization(BaseModel):
    name: str
    role: Optional[str] = None

class TeamMember(BaseModel):
    name: str
    duty: Optional[str] = None

class BasicInfo(BaseModel):
    undertaking_unit: Optional[str] = None
    partner_units: List[str] = []
    team_members: List[TeamMember] = []

class DocumentSchema(BaseModel):
    project_name: str
    research_contents: List[ResearchContent]
    performance_targets: List[PerformanceTarget]
    budget: Budget
    basic_info: Optional[BasicInfo] = None
    units_budget: List[UnitBudgetAllocation] = []

class PerfCheckRequest(BaseModel):
    declaration_text: str
    task_text: str
    project_id: str = "default_project"
    budget_shift_threshold: float = 0.10
    strict_mode: bool = True
    enable_llm_enhancement: bool = False
    enable_table_vision_extraction: bool = True
    enable_llm_entailment: bool = True

class MetricComparison(BaseModel):
    apply_id: str
    task_id: str
    apply_value: float
    task_value: float
    apply_display: Optional[str] = None
    task_display: Optional[str] = None
    apply_subtype: Optional[str] = None
    task_subtype: Optional[str] = None
    unit: str
    type: str
    risk_level: str  # RED, YELLOW, GREEN
    reason: str

class ContentComparison(BaseModel):
    apply_id: str
    apply_text: str
    task_text: str = ""
    is_covered: bool
    coverage_score: float
    risk_level: str
    reason: str

class BudgetComparison(BaseModel):
    type: str
    apply_amount: float
    task_amount: float
    apply_ratio: float
    task_ratio: float
    ratio_delta: float
    risk_level: str
    reason: str

class OtherInfoComparison(BaseModel):
    field: str
    apply_value: str
    task_value: str
    risk_level: str
    reason: str

class UnitBudgetComparison(BaseModel):
    unit_name: str
    type: str
    apply_amount: float
    task_amount: float
    delta: float
    risk_level: str
    reason: str

class PerfCheckResult(BaseModel):
    project_id: str
    task_id: str
    metrics_risks: List[MetricComparison]
    content_risks: List[ContentComparison]
    budget_risks: List[BudgetComparison]
    other_risks: List[OtherInfoComparison] = []
    unit_budget_risks: List[UnitBudgetComparison] = []
    warnings: List[str] = []
    summary: str = ""

class PerfCheckTask(BaseModel):
    task_id: str
    project_id: str
    state: str
    progress: float = 0.0
    stage: str = ""
    error_code: str = ""
    message: str = ""
    summary: str = ""
    result: Optional[PerfCheckResult] = None
