"""Saved-record schemas. Engine input and result schemas live in ``coastmath.schemas``."""
from app.schemas.account import AccountCreate, AccountRead
from app.schemas.assumption_curve import AssumptionCurveCreate, AssumptionCurveRead
from app.schemas.cash_flow_priority import (
    CashFlowPriorityBulkUpdate,
    CashFlowPriorityCreate,
    CashFlowPriorityRead,
)
from app.schemas.drawdown_order import (
    DrawdownOrderBulkUpdate,
    DrawdownOrderCreate,
    DrawdownOrderRead,
)
from app.schemas.expense import ExpenseCreate, ExpenseRead
from app.schemas.income import IncomeCreate, IncomeRead
from app.schemas.liability import LiabilityCreate, LiabilityRead, LiabilityUpdate
from app.schemas.milestone import MilestoneCreate, MilestoneRead
from app.schemas.plan import PlanCreate, PlanRead, PlanUpdate
from app.schemas.progress_point import ProgressPointCreate, ProgressPointRead
from app.schemas.real_asset import RealAssetCreate, RealAssetRead, RealAssetUpdate
from app.schemas.spouse import SpouseCreate, SpouseRead
from app.schemas.tax_jurisdiction import (
    TaxBracket,
    TaxJurisdictionCreate,
    TaxJurisdictionRead,
    TaxJurisdictionUpdate,
)
from app.schemas.user import UserRead
from coastmath.schemas.monte_carlo import (
    FailureDetail,
    MonteCarloRequest,
    MonteCarloResult,
    PercentileCurves,
)
from coastmath.schemas.simulation import SimMetadata, SimulationResult, YearSnapshot

__all__ = [
    "AccountCreate",
    "AccountRead",
    "AssumptionCurveCreate",
    "AssumptionCurveRead",
    "CashFlowPriorityBulkUpdate",
    "CashFlowPriorityCreate",
    "CashFlowPriorityRead",
    "DrawdownOrderBulkUpdate",
    "DrawdownOrderCreate",
    "DrawdownOrderRead",
    "ExpenseCreate",
    "ExpenseRead",
    "FailureDetail",
    "IncomeCreate",
    "IncomeRead",
    "LiabilityCreate",
    "LiabilityRead",
    "LiabilityUpdate",
    "MilestoneCreate",
    "MilestoneRead",
    "MonteCarloRequest",
    "MonteCarloResult",
    "PercentileCurves",
    "PlanCreate",
    "PlanRead",
    "PlanUpdate",
    "ProgressPointCreate",
    "ProgressPointRead",
    "RealAssetCreate",
    "RealAssetRead",
    "RealAssetUpdate",
    "SimMetadata",
    "SimulationResult",
    "SpouseCreate",
    "SpouseRead",
    "TaxBracket",
    "TaxJurisdictionCreate",
    "TaxJurisdictionRead",
    "TaxJurisdictionUpdate",
    "UserRead",
    "YearSnapshot",
]
