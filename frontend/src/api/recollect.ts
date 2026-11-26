/** 补采领办接口：缺口清单、领办签发、位点幂等闭合与迟到原件写入。 */
import { request } from './client'

export type GapSegment = {
  来源渠道: string
  起始位点: string
  截止位点: string
  缺口批次: string[]
  批次数: number
  状态: string
  占用领办单: string
}

export type SourceGaps = {
  来源渠道: string
  segments: GapSegment[]
  可领办段数: number
}

export type CreatedClaim = {
  来源渠道: string
  起始位点: string
  截止位点: string
  领办编号: string
  关联重解析单: string
  缺口批次: string[]
  批次数: number
}

export type PendingSegment = {
  来源渠道: string
  起始位点: string
  截止位点: string
  原因: string
}

export type ClaimResult = {
  ok: boolean
  message: string
  created: CreatedClaim[]
  pending: PendingSegment[]
}

export async function fetchGapBoard(): Promise<{ sources: SourceGaps[] }> {
  const response = await request('/api/recollect/gap-board')
  if (!response.ok) throw new Error('补采区间清单读取失败')
  return (await response.json()) as { sources: SourceGaps[] }
}

export async function claimIntervals(
  channel: string,
  operator: string,
  segments: { 起始位点: string; 截止位点: string }[],
): Promise<ClaimResult> {
  const response = await request('/api/recollect/claim', {
    method: 'POST',
    body: JSON.stringify({ 来源渠道: channel, 领办人: operator, segments }),
  })
  return (await response.json()) as ClaimResult
}
