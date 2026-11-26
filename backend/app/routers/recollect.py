"""补采领办专用接口：缺口清单、领办签发、位点幂等闭合与迟到原件写入。

路由层只做参数传递，区间核对、签发与闭合规则全部在 RecollectClaimService。
固定前缀 /api/recollect，必须先于通用资源路由 /api/{module} 注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services import SERVICES

router = APIRouter(prefix="/api/recollect", tags=["补采领办"])


def _service():
    return SERVICES["recollect_claim"]


class ClaimSegment(BaseModel):
    起始位点: str
    截止位点: str


class ClaimPayload(BaseModel):
    来源渠道: str
    领办人: str
    segments: list[ClaimSegment] = Field(default_factory=list)
    领办时间: str = ""


class ClosePayload(BaseModel):
    来源渠道: str
    位点: str
    闭合来源: str = "补采结果"
    操作人: str = ""
    闭合时间: str = ""


class LateArrivalPayload(BaseModel):
    来源渠道: str
    位点: str
    到达时间: str = ""


@router.get("/gap-board")
def gap_board() -> dict[str, Any]:
    """补采区间清单：按来源排列的可领办缺口段，供解析进度页清单视图消费。"""
    return {"sources": _service().gap_board()}


@router.post("/claim")
def claim(payload: ClaimPayload) -> dict[str, Any]:
    """提交领办：逐段核对后签发重解析批次，已生成任务与仍需确认逐项返回。"""
    ok, message, result = _service().claim_intervals(
        payload.来源渠道,
        [segment.model_dump() for segment in payload.segments],
        payload.领办人,
        payload.领办时间,
    )
    return {"ok": ok, "message": message, **result}


@router.post("/close", response_model=ActionResult)
def close(payload: ClosePayload) -> ActionResult:
    """位点闭合核对：同一来源同一位点只允许确认一次闭合，重放幂等。"""
    ok, message, entry = _service().confirm_position_close(
        payload.来源渠道, payload.位点, payload.闭合来源, payload.操作人, payload.闭合时间)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.post("/late-arrival", response_model=ActionResult)
def late_arrival(payload: LateArrivalPayload) -> ActionResult:
    """迟到原投递写入：同一位点已领办时标记补采资格冲突。"""
    ok, message, entry = _service().late_original_arrival(
        payload.来源渠道, payload.位点, payload.到达时间)
    return ActionResult(ok=ok, message=message, entry=entry)
