"""补采领办链路测试：缺口清单、领办签发、来源隔离、幂等闭合与台账同步。

场景锚点：来源甲 channel-alpha 位点 040~045 中 041/043/044 三段未闭合记录，
来源乙 channel-beta 持有同编号位点 041，用于验证来源隔离。
"""
from __future__ import annotations

import pytest

from app.services import SERVICES
from app.store import store


@pytest.fixture(autouse=True)
def fresh_store():
    """每个测试从 seed 初始状态开始，避免跨测试污染。"""
    store.reload_seed()
    yield store
    store.reload_seed()


@pytest.fixture
def svc():
    return SERVICES["recollect_claim"]


def _claim(svc, channel, start, end, operator="op-07"):
    return svc.claim_intervals(
        channel, [{"起始位点": start, "截止位点": end}], operator, "2026-11-26T10:00:00")


def _claim_row(claim_no: str) -> dict:
    return next(r for r in store.rows("recollect_claim") if r["领办编号"] == claim_no)


def _task_row(task_no: str) -> dict:
    return next(r for r in store.rows("reparse_task") if r["重解析编号"] == task_no)


class TestGapSegments:
    def test_alpha_segments_split_by_closed_positions(self, svc):
        """041/043/044 三段未闭合记录被已闭合位点断开：042/045 不进任何区间。"""
        segments = svc.gap_segments("channel-alpha")
        ranges = [(s["起始位点"], s["截止位点"]) for s in segments]
        assert ("FI-A-041", "FI-A-041") in ranges
        assert ("FI-A-043", "FI-A-044") in ranges
        for seg in segments:
            assert "FI-A-040" not in seg["缺口批次"]
            assert "FI-A-042" not in seg["缺口批次"]
            assert "FI-A-045" not in seg["缺口批次"]

    def test_segments_start_claimable(self, svc):
        segments = svc.gap_segments("channel-alpha")
        assert segments
        assert all(s["状态"] == "可领办" for s in segments)

    def test_beta_lists_own_041_independently(self, svc):
        """乙的清单独立计算，只含自己的 041，不混入甲的同编号位点。"""
        segments = svc.gap_segments("channel-beta")
        assert [(s["起始位点"], s["截止位点"]) for s in segments] == [
            ("FI-B-041", "FI-B-041")]
        assert segments[0]["缺口批次"] == ["FI-B-041"]

    def test_gap_board_grouped_by_source(self, svc):
        board = svc.gap_board()
        by_channel = {item["来源渠道"]: item for item in board}
        assert "channel-alpha" in by_channel
        assert "channel-beta" in by_channel
        assert by_channel["channel-alpha"]["可领办段数"] == 2
        assert by_channel["channel-beta"]["可领办段数"] == 1


class TestClaimIntervals:
    def test_claim_issues_reparse_batch(self, svc):
        """领办 041：服务端核对区间后签发对应的重解析批次并登记台账。"""
        ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        assert ok is True
        assert len(result["created"]) == 1
        claim_no = result["created"][0]["领办编号"]
        task_no = result["created"][0]["关联重解析单"]
        claim = _claim_row(claim_no)
        assert claim["来源渠道"] == "channel-alpha"
        assert claim["缺口批次"] == "FI-A-041"
        assert claim["关联重解析单"] == task_no
        assert claim["status"] == "补采中"
        task = _task_row(task_no)
        assert task["起始位点"] == "FI-A-041"
        assert task["截止位点"] == "FI-A-041"
        assert task["受影响批次"] == "FI-A-041"
        assert task["status"] == "待执行"
        assert "补采领办" in task["重解析原因"]

    def test_interval_spanning_closed_position_rejected(self, svc):
        """已闭合位点之间的缺口不能合并：跨 042 的区间被服务端拒绝。"""
        ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-041", "FI-A-043")
        assert result["created"] == []
        assert len(result["pending"]) == 1
        assert "已闭合" in result["pending"][0]["原因"]
        assert "FI-A-042" in result["pending"][0]["原因"]

    def test_partial_failure_keeps_other_segments(self, svc):
        """一段确认前发生变化时其余段照常签发：已生成任务与仍需确认逐项区分。"""
        ok, msg, result = svc.claim_intervals(
            "channel-alpha",
            [
                {"起始位点": "FI-A-041", "截止位点": "FI-A-041"},  # 合法缺口
                {"起始位点": "FI-A-043", "截止位点": "FI-A-045"},  # 跨已闭合 045
            ],
            "op-07", "2026-11-26T10:00:00")
        assert ok is True
        assert len(result["created"]) == 1
        assert result["created"][0]["起始位点"] == "FI-A-041"
        assert len(result["pending"]) == 1
        assert result["pending"][0]["起始位点"] == "FI-A-043"
        assert "已闭合" in result["pending"][0]["原因"]
        assert "仍需确认" in msg

    def test_source_isolation_on_same_position_number(self, svc):
        """位点编号相同也按来源隔离：甲领办 041 不带走乙的同编号文件，乙仍可单领。"""
        ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        assert ok is True
        task = _task_row(result["created"][0]["关联重解析单"])
        assert "FI-B-041" not in task["受影响批次"]
        assert "FI-B-041" not in _claim_row(result["created"][0]["领办编号"])["缺口批次"]
        # 乙的同编号 041 未被甲占用，仍可单独领办
        ok2, _msg2, result2 = _claim(svc, "channel-beta", "FI-B-041", "FI-B-041", "op-08")
        assert ok2 is True
        assert len(result2["created"]) == 1
        task2 = _task_row(result2["created"][0]["关联重解析单"])
        assert task2["受影响批次"] == "FI-B-041"

    def test_double_claim_same_position_conflict(self, svc):
        """同一位点补采资格唯一：已被领办的位点再次领办判冲突。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041", "op-09")
        assert result["created"] == []
        assert "冲突" in result["pending"][0]["原因"]

    def test_segment_state_turns_claimed_after_claim(self, svc):
        """领办后该段转为已领办，其余段保持可领办。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        segments = svc.gap_segments("channel-alpha")
        seg041 = next(s for s in segments if s["起始位点"] == "FI-A-041")
        assert seg041["状态"] == "已领办"
        seg043 = next(s for s in segments if s["起始位点"] == "FI-A-043")
        assert seg043["状态"] == "可领办"

    def test_claim_requires_operator(self, svc):
        ok, msg, result = svc.claim_intervals(
            "channel-alpha",
            [{"起始位点": "FI-A-041", "截止位点": "FI-A-041"}], "", "t")
        assert ok is False
        assert "领办人" in msg
        assert result["created"] == []


class TestIdempotentClose:
    def test_concurrent_close_confirmed_only_once(self, svc):
        """迟到原件与补采结果并发提交：同一位点只允许确认一次闭合。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        ok1, _m1, _e1 = svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "补采结果", "op-07", "2026-11-26T11:00:00")
        ok2, msg2, _e2 = svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "迟到原件", "op-08", "2026-11-26T11:00:01")
        assert ok1 is True
        assert ok2 is False
        assert "已闭合" in msg2

    def test_replay_counts_only_once(self, svc):
        """重放同一闭合请求后 041 只算一次：批次闭合记录与台账结论都不重复。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "补采结果", "op-07", "2026-11-26T11:00:00")
        ok, msg, _e = svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "补采结果", "op-07", "2026-11-26T11:00:00")
        assert ok is False
        assert "重放只算一次" in msg
        closed = [
            r for r in store.rows("parse_batch")
            if r["关联投递批次"] == "FI-A-041" and r["批次状态"] == "已闭合"
        ]
        assert len(closed) == 1
        claim = next(
            r for r in store.rows("recollect_claim")
            if r["来源渠道"] == "channel-alpha" and r["缺口批次"] == "FI-A-041")
        assert claim["status"] == "已闭合"
        assert claim["确认结论"].count("由补采结果") == 1

    def test_close_removes_position_from_gap_list(self, svc):
        """闭合后该位点从缺口清单消失，其余缺口段不受影响。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "补采结果", "op-07", "t")
        ranges = [(s["起始位点"], s["截止位点"]) for s in svc.gap_segments("channel-alpha")]
        assert ("FI-A-041", "FI-A-041") not in ranges
        assert ("FI-A-043", "FI-A-044") in ranges

    def test_close_rejects_foreign_channel(self, svc):
        """位点闭合同样按来源隔离：甲的闭合请求不能闭合乙的位点。"""
        ok, msg, _e = svc.confirm_position_close(
            "channel-alpha", "FI-B-041", "补采结果", "op-07", "t")
        assert ok is False
        assert "不属于来源" in msg


class TestLateOriginalArrival:
    def test_late_arrival_after_claim_marks_conflict(self, svc):
        """领出 041 后迟到原投递开始写入：同一位点补采资格冲突被标记。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        ok, msg, info = svc.late_original_arrival(
            "channel-alpha", "FI-A-041", "2026-11-26T12:00:00")
        assert ok is True
        assert info["conflict"] is True
        assert "补采资格冲突" in msg
        claim = _claim_row(info["领办编号"])
        assert claim["abnormal"] is True
        assert "补采资格冲突" in claim["确认结论"]

    def test_late_original_can_close_via_position_check(self, svc):
        """原件迟到也可通过同一位点核对下一次闭合。"""
        _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        svc.late_original_arrival("channel-alpha", "FI-A-041", "2026-11-26T12:00:00")
        ok, msg, entry = svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "迟到原件", "op-08", "2026-11-26T12:05:00")
        assert ok is True
        assert "迟到原件" in msg
        batch = next(
            r for r in store.rows("parse_batch") if r["关联投递批次"] == "FI-A-041")
        assert batch["批次状态"] == "已闭合"

    def test_late_arrival_without_claim_no_conflict(self, svc):
        ok, _msg, info = svc.late_original_arrival(
            "channel-alpha", "FI-A-043", "2026-11-26T12:00:00")
        assert ok is True
        assert info["conflict"] is False


class TestLedgerSync:
    def test_reparse_conclusion_syncs_to_ledger(self, svc):
        """重解析的确认结论同步到补采执行台账。"""
        _ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-043", "FI-A-044")
        task_no = result["created"][0]["关联重解析单"]
        claim_no = result["created"][0]["领办编号"]
        reparse_svc = SERVICES["reparse_task"]
        reparse_svc.start_task(task_no)
        ok, msg, task = reparse_svc.complete_task(task_no, 2, "两段缺口重解析完成")
        assert ok is True
        assert "补采领办单" in msg
        claim = _claim_row(claim_no)
        assert "两段缺口重解析完成" in claim["确认结论"]

    def test_full_flow_claim_reparse_close(self, svc):
        """全链路：领办 → 重解析确认 → 结论回台账 → 位点闭合 → 缺口消失。"""
        _ok, _msg, result = _claim(svc, "channel-alpha", "FI-A-041", "FI-A-041")
        task_no = result["created"][0]["关联重解析单"]
        claim_no = result["created"][0]["领办编号"]
        reparse_svc = SERVICES["reparse_task"]
        reparse_svc.start_task(task_no)
        reparse_svc.complete_task(task_no, 1, "041 补采重解析完成")
        assert "041 补采重解析完成" in _claim_row(claim_no)["确认结论"]
        ok, _m, _e = svc.confirm_position_close(
            "channel-alpha", "FI-A-041", "补采结果", "op-07", "2026-11-26T13:00:00")
        assert ok is True
        claim = _claim_row(claim_no)
        assert claim["status"] == "已闭合"
        assert "041 补采重解析完成" in claim["确认结论"]
        assert "由补采结果" in claim["确认结论"]


class TestWatermarkBlocking:
    def test_pending_044_blocks_advance_to_045(self):
        """待处理的 044 拦住水位推进至 045。"""
        watermark = SERVICES["parse_watermark"]
        ok, msg, reading = watermark.advance_position(
            "channel-alpha", "FI-A-045", "2026-11-26T13:00:00")
        assert ok is False
        assert "FI-A-044" in msg
        assert reading["status"] in ("轻微滞后", "严重滞后")

    def test_close_all_gaps_allows_advance(self, svc):
        """三段缺口全部闭合后水位可推进至 045。"""
        for pos in ("FI-A-041", "FI-A-043", "FI-A-044"):
            ok, msg, _e = svc.confirm_position_close(
                "channel-alpha", pos, "补采结果", "op-07", "2026-11-26T14:00:00")
            assert ok is True, msg
        watermark = SERVICES["parse_watermark"]
        ok, msg, reading = watermark.advance_position(
            "channel-alpha", "FI-A-045", "2026-11-26T14:05:00")
        assert ok is True
        assert reading["已解析至位点"] == "FI-A-045"
        assert reading["status"] == "已推进"
