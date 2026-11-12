<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const data = ref(null)
const runs = ref([])
const err = ref('')
const msg = ref('')
const busy = ref(false)

const latestReport = computed(() => data.value?.latest_run?.report || null)
const checks = computed(() => latestReport.value?.checks || [])

async function load() {
  data.value = await getJSON('/api/metric-mart')
  runs.value = await getJSON('/api/metric-mart/runs')
}

async function refresh() {
  err.value = ''
  msg.value = ''
  busy.value = true
  try {
    const report = await postJSON('/api/metric-mart/refresh', {})
    msg.value = `批次 #${report.run_id} 刷新完成：${report.metric_row_count} 行类目指标，对账${report.reconciled ? '通过' : '未通过'}`
    await load()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function pct(v) {
  return `${(Number(v) * 100).toFixed(1)}%`
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div class="page">
    <h1>类目指标集市</h1>
    <p class="muted">
      指标全部由当前有效 Canonical 主数据实时聚合，不使用手工缓存：每次刷新重建整批类目指标并落库。
      口径：件数 = COUNT(*)，价格合计 = SUM(price)，均价 = AVG(price)（= 合计 / 件数），另附最小/最大价与件数占比。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>

    <div class="panel">
      <button :disabled="busy" @click="refresh">{{ busy ? '刷新中…' : '一键刷新指标' }}</button>
      <span v-if="data?.stale" class="tag warn" style="margin-left:0.75rem">
        主数据已变化，当前指标为旧批次，请重新刷新
      </span>
      <span v-else-if="data?.latest_run" class="tag ok" style="margin-left:0.75rem">指标与当前主数据同源</span>
    </div>

    <div class="tiles" v-if="data">
      <div class="tile">
        <div class="hero-num">{{ data.canonical_total_now }}</div>
        <div class="muted">主数据总件数（实时）</div>
      </div>
      <div class="tile">
        <div class="hero-num">{{ data.distinct_category_count_now }}</div>
        <div class="muted">主数据类目数（实时）</div>
      </div>
      <div class="tile">
        <div class="hero-num">{{ data.metrics.length }}</div>
        <div class="muted">指标行数（最新批次）</div>
      </div>
    </div>

    <div class="panel">
      <h3>类目指标（最新批次）</h3>
      <p v-if="!data?.metrics.length" class="muted">尚未刷新，点击上方按钮生成第一批指标。</p>
      <table v-else>
        <thead>
          <tr>
            <th>category</th><th>件数</th><th>价格合计</th><th>均价</th>
            <th>最低价</th><th>最高价</th><th>件数占比</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in data.metrics" :key="m.category">
            <td>{{ m.category }}</td>
            <td class="mono">{{ m.item_count }}</td>
            <td class="mono">{{ m.price_total.toFixed(2) }}</td>
            <td class="mono">{{ m.price_avg.toFixed(2) }}</td>
            <td class="mono">{{ m.price_min.toFixed(2) }}</td>
            <td class="mono">{{ m.price_max.toFixed(2) }}</td>
            <td class="mono">{{ pct(m.count_share) }}</td>
          </tr>
          <tr v-if="data.metrics.length">
            <td><strong>合计</strong></td>
            <td class="mono"><strong>{{ data.metrics.reduce((s, m) => s + m.item_count, 0) }}</strong></td>
            <td class="mono">
              <strong>{{ data.metrics.reduce((s, m) => s + m.price_total, 0).toFixed(2) }}</strong>
            </td>
            <td class="muted">—</td>
            <td class="muted">—</td>
            <td class="mono">
              <strong>{{ pct(data.metrics.reduce((s, m) => s + m.item_count, 0) / data.canonical_total_now) }}</strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel" v-if="latestReport">
      <h3>
        最近批次对账报告 · #{{ latestReport.run_id }}
        <span class="tag" :class="latestReport.reconciled ? 'ok' : 'danger'">
          {{ latestReport.reconciled ? '对账通过' : '对账未通过' }}
        </span>
      </h3>
      <p class="mono muted">
        生成于 {{ latestReport.created_at }} ·
        主数据总件数={{ latestReport.canonical_total }} ·
        类目数={{ latestReport.category_count }} ·
        指标行数={{ latestReport.metric_row_count }} ·
        主数据价格合计={{ latestReport.canonical_price_total?.toFixed(2) }}
      </p>
      <table>
        <thead>
          <tr><th>对账项</th><th>结果</th><th>明细</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in checks" :key="c.name">
            <td class="mono">{{ c.name }}</td>
            <td><span class="tag" :class="c.passed ? 'ok' : 'danger'">{{ c.passed ? 'PASS' : 'FAIL' }}</span></td>
            <td class="mono muted">{{ c.detail }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="margin-bottom:0">
        逐项互证：各类目件数之和 {{ latestReport.sum_item_count }} = 主数据总件数
        {{ latestReport.canonical_total }}；各类目价格合计之和
        {{ latestReport.sum_price_total?.toFixed(2) }} = 主数据价格合计
        {{ latestReport.canonical_price_total?.toFixed(2) }}。
      </p>
    </div>

    <div class="panel">
      <h3>刷新批次历史</h3>
      <p v-if="!runs.length" class="muted">暂无刷新批次。</p>
      <table v-else>
        <thead>
          <tr><th>批次</th><th>状态</th><th>主数据件数</th><th>类目数</th><th>指标行数</th><th>对账</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>#{{ r.id }}</td>
            <td><span class="tag" :class="r.status === 'ok' ? 'ok' : 'danger'">{{ r.status }}</span></td>
            <td class="mono">{{ r.canonical_total }}</td>
            <td class="mono">{{ r.category_count }}</td>
            <td class="mono">{{ r.metric_row_count }}</td>
            <td>
              <span class="tag" :class="r.reconciled ? 'ok' : 'danger'">
                {{ r.reconciled ? 'PASS' : 'FAIL' }}
              </span>
            </td>
            <td class="mono">{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
