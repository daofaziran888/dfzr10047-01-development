<template>
  <section class="recollect-panel" data-testid="recollect-gap-panel">
    <header class="panel-head">
      <div>
        <h3>补采区间清单</h3>
        <p class="panel-desc">
          按来源列出未闭合位点形成的补采缺口，逐段勾选后提交领办，由服务端核对区间并签发重解析批次。
        </p>
      </div>
      <div class="panel-actions">
        <input
          v-model="operator"
          class="operator-input"
          data-testid="claim-operator"
          placeholder="领办人标识"
        />
        <button class="btn" type="button" data-testid="reload-gaps" @click="reload">刷新清单</button>
      </div>
    </header>

    <div
      v-for="source in board"
      :key="source.来源渠道"
      class="source-group"
      :data-testid="`source-${source.来源渠道}`"
    >
      <header class="source-head">
        <strong>{{ source.来源渠道 }}</strong>
        <span class="source-meta">可领办 {{ source.可领办段数 }} 段</span>
        <button
          class="btn primary"
          type="button"
          :disabled="claiming || !selectedCount(source) || !operator.trim()"
          :data-testid="`claim-${source.来源渠道}`"
          @click="submitClaim(source)"
        >
          提交领办（{{ selectedCount(source) }} 段）
        </button>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>勾选</th>
            <th>位点区间</th>
            <th>缺口批次</th>
            <th>批次数</th>
            <th>段状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="seg in source.segments"
            :key="segKey(seg)"
            :data-testid="`seg-${segKey(seg)}`"
            :class="{ 'row-claimed': seg.状态 !== '可领办' }"
          >
            <td>
              <input
                type="checkbox"
                :disabled="seg.状态 !== '可领办'"
                :checked="isSelected(seg)"
                :data-testid="`check-${segKey(seg)}`"
                @change="toggle(seg, $event)"
              />
            </td>
            <td>{{ seg.起始位点 }} ~ {{ seg.截止位点 }}</td>
            <td>{{ seg.缺口批次.join('、') }}</td>
            <td>{{ seg.批次数 }}</td>
            <td>
              {{ seg.状态 }}
              <span v-if="seg.占用领办单" class="source-meta">（{{ seg.占用领办单 }}）</span>
            </td>
          </tr>
          <tr v-if="!source.segments.length">
            <td colspan="5" class="empty-state">该来源当前没有补采缺口</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="created.length" class="claim-result created" data-testid="claim-created">
      <h4>已生成任务</h4>
      <p v-for="item in created" :key="item.领办编号" class="claim-line">
        <span class="tag">领办回执</span>
        {{ item.领办编号 }}（{{ item.来源渠道 }} · {{ item.起始位点 }} ~ {{ item.截止位点 }}，
        {{ item.批次数 }} 个批次）→ 重解析单
        <RouterLink class="link" to="/reparse_task">{{ item.关联重解析单 }}</RouterLink>
      </p>
    </div>

    <div v-if="pending.length" class="claim-result pending" data-testid="claim-pending">
      <h4>仍需确认</h4>
      <p
        v-for="item in pending"
        :key="segKey(item)"
        class="claim-line"
      >
        <span class="tag warn">待确认</span>
        {{ item.来源渠道 }} · {{ item.起始位点 }} ~ {{ item.截止位点 }}：{{ item.原因 }}
        <button
          class="link"
          type="button"
          :data-testid="`reselect-${segKey(item)}`"
          @click="reselect(item)"
        >
          回到原位点
        </button>
      </p>
    </div>

    <p v-if="notice" class="notice-text" data-testid="claim-notice">{{ notice }}</p>
    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { claimIntervals, fetchGapBoard } from '@/api/recollect'
import type { CreatedClaim, GapSegment, PendingSegment, SourceGaps } from '@/api/recollect'

const board = ref<SourceGaps[]>([])
const operator = ref('')
const claiming = ref(false)
const notice = ref('')
const errorMessage = ref('')
const created = ref<CreatedClaim[]>([])
const pending = ref<PendingSegment[]>([])
const selected = ref<Set<string>>(new Set())

type SegmentRef = { 来源渠道: string; 起始位点: string; 截止位点: string }

function segKey(seg: SegmentRef): string {
  return `${seg.来源渠道}|${seg.起始位点}|${seg.截止位点}`
}

function isSelected(seg: SegmentRef): boolean {
  return selected.value.has(segKey(seg))
}

function toggle(seg: GapSegment, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const next = new Set(selected.value)
  if (checked) next.add(segKey(seg))
  else next.delete(segKey(seg))
  selected.value = next
}

function selectedCount(source: SourceGaps): number {
  return source.segments.filter((seg) => seg.状态 === '可领办' && isSelected(seg)).length
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchGapBoard()
    board.value = payload.sources
    // 清单刷新后：已从清单消失的段（如已闭合）释放勾选，仍在清单的段保留勾选
    const existing = new Set<string>()
    for (const source of payload.sources) {
      for (const seg of source.segments) existing.add(segKey(seg))
    }
    selected.value = new Set([...selected.value].filter((key) => existing.has(key)))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补采区间清单读取失败'
  }
}

async function submitClaim(source: SourceGaps) {
  const segments = source.segments.filter((seg) => seg.状态 === '可领办' && isSelected(seg))
  if (!segments.length) return
  claiming.value = true
  errorMessage.value = ''
  try {
    const result = await claimIntervals(
      source.来源渠道,
      operator.value.trim(),
      segments.map((seg) => ({ 起始位点: seg.起始位点, 截止位点: seg.截止位点 })),
    )
    if (!result.ok && !result.created.length) throw new Error(result.message)
    created.value = [...created.value, ...result.created]
    pending.value = [...pending.value, ...result.pending]
    notice.value = result.message
    // 已生成任务的段解除勾选；仍需确认的段保留勾选，核对后可再次提交
    const doneKeys = new Set(result.created.map((item) => segKey(item)))
    const next = new Set(selected.value)
    for (const key of doneKeys) next.delete(key)
    selected.value = next
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '领办提交失败'
  } finally {
    claiming.value = false
  }
}

function reselect(item: PendingSegment) {
  // 回到原位点：把仍需确认的段重新置为勾选，保留其余勾选，操作员可继续处理
  const key = segKey(item)
  const next = new Set(selected.value)
  next.add(key)
  selected.value = next
  pending.value = pending.value.filter((entry) => segKey(entry) !== key)
  const row = document.querySelector(`[data-testid="seg-${key}"]`)
  row?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

onMounted(reload)
</script>
