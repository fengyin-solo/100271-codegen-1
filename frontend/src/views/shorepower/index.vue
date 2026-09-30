<template>
  <section class="page" data-module="shorepower">
    <header class="page-head">
      <div>
        <h2>岸电接电台账</h2>
        <p class="page-desc">
          靠泊后在接电箱开单，按「待接 → 已通电 → 已结算」切换；中途掉电退回待接并注明原因，
          计量只认电表抄见数。同一艘船重复开单只认第一张，同泊位复靠自动延续上一张。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">开具接电单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 接电单 -->
    <template v-if="activeTab === 'orders'">
      <form class="filter-bar" @submit.prevent="reloadOrders">
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="orderFilter.keyword" placeholder="单号 / 船名 / 泊位 / 接电箱" />
        </label>
        <label class="filter-item">
          <span>状态</span>
          <select v-model="orderFilter.status">
            <option value="">全部</option>
            <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetOrderFilter">重置</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>接电单号</th>
            <th>船名 / 编号</th>
            <th>泊位 / 接电箱</th>
            <th>状态</th>
            <th>枪数</th>
            <th>起始抄见</th>
            <th>结算抄见</th>
            <th>供电量(度)</th>
            <th>掉电</th>
            <th>延续</th>
            <th>最近处理人 / 工班</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in orders" :key="row.id" :class="{ abnormal: row.abnormal }">
            <td>{{ row.order_no }}</td>
            <td>{{ row.vessel_name }}<br /><small>{{ row.vessel_code }}</small></td>
            <td>{{ row.berth_code }}<br /><small>{{ row.box_code }}</small></td>
            <td><span class="badge" :class="badgeClass(row.status)">{{ row.status }}</span>
              <div v-if="row.last_drop_reason" class="cell-note" :title="row.last_drop_reason">
                掉电：{{ row.last_drop_reason }}
              </div>
            </td>
            <td>{{ row.gun_count ?? '—' }}</td>
            <td>{{ row.meter_start ?? '—' }}</td>
            <td>{{ row.meter_end ?? '—' }}</td>
            <td>{{ row.status === '已结算' ? row.kwh : '—' }}</td>
            <td>{{ row.outage_count || 0 }}</td>
            <td>
              <span v-if="row.visit_no > 1">第{{ row.visit_no }}次接电<br /><small>链 {{ chainNo(row) }}</small></span>
              <span v-else class="muted">首次</span>
            </td>
            <td>{{ row.last_operator }}<br /><small>{{ row.last_shift }}</small></td>
            <td class="row-actions">
              <button
                v-if="row.status === '待接'"
                class="link"
                type="button"
                @click="openEnergize(row)"
              >插枪通电</button>
              <button
                v-if="row.status === '已通电'"
                class="link warn"
                type="button"
                @click="openDropout(row)"
              >中途掉电</button>
              <button
                v-if="row.status === '已通电'"
                class="link"
                type="button"
                @click="openSettle(row)"
              >拔枪结算</button>
              <button class="link" type="button" @click="openTrail(row)">轨迹</button>
            </td>
          </tr>
          <tr v-if="!orders.length">
            <td :colspan="12" class="empty-state">暂无接电单，靠泊后可在右上角开具</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ orderTotal }} 张接电单</span>
        <span v-if="message" class="error-text">{{ message }}</span>
      </footer>
    </template>

    <!-- 随船台账 -->
    <template v-else-if="activeTab === 'ledger'">
      <div v-for="book in ledger" :key="book.vessel_code || book.vessel_name" class="ledger-book">
        <div class="ledger-head">
          <strong>{{ book.vessel_name }} <small>{{ book.vessel_code }}</small></strong>
          <span class="muted">
            接电 {{ book.order_count }} 次 · 累计供电
            <b class="kwh">{{ book.total_kwh }}</b> 度
            <template v-if="book.open_status"> · 当前 <span class="badge" :class="badgeClass(book.open_status)">{{ book.open_status }}</span></template>
          </span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>接电单号</th><th>同链</th><th>第几次</th><th>泊位</th><th>状态</th>
              <th>枪数</th><th>起始</th><th>结算</th><th>供电量</th><th>掉电</th><th>开单</th><th>结算</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in book.orders" :key="o.id" :class="{ abnormal: o.status === '待接' && o.outage_count }">
              <td>{{ o.order_no }}</td>
              <td>{{ o.chain_no }}</td>
              <td>{{ o.visit_no }}</td>
              <td>{{ o.berth_code }}</td>
              <td><span class="badge" :class="badgeClass(o.status)">{{ o.status }}</span></td>
              <td>{{ o.gun_count ?? '—' }}</td>
              <td>{{ o.meter_start ?? '—' }}</td>
              <td>{{ o.meter_end ?? '—' }}</td>
              <td>{{ o.kwh || '—' }}</td>
              <td>{{ o.outage_count || 0 }}</td>
              <td><small>{{ o.opened_at }}</small></td>
              <td><small>{{ o.settled_at ?? '—' }}</small></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!ledger.length" class="empty-state">暂无随船台账</p>
    </template>

    <!-- 当班审计 -->
    <template v-else>
      <form class="filter-bar" @submit.prevent="reloadEvents">
        <label class="filter-item">
          <span>船名 / 编号</span>
          <input v-model="eventFilter.vessel" placeholder="按船检索" />
        </label>
        <label class="filter-item">
          <span>当班处理人</span>
          <input v-model="eventFilter.operator" placeholder="按处理人检索" />
        </label>
        <label class="filter-item">
          <span>工班</span>
          <input v-model="eventFilter.shift" placeholder="如 2026-09-30 夜班" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetEventFilter">重置</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th><th>接电单号</th><th>船名</th><th>泊位</th><th>动作</th>
            <th>状态变化</th><th>当班处理人</th><th>工班</th><th>明细</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ev in events" :key="ev.id">
            <td><small>{{ ev.at }}</small></td>
            <td>{{ ev.order_no }}</td>
            <td>{{ ev.vessel_name }}</td>
            <td>{{ ev.berth_code }}</td>
            <td>{{ ev.action }}</td>
            <td>{{ ev.from_status ?? '—' }} → {{ ev.to_status ?? '—' }}</td>
            <td>{{ ev.operator }}</td>
            <td>{{ ev.shift }}</td>
            <td><small v-for="(v, k) in detailPairs(ev.detail)" :key="k">{{ k }}：{{ v }}；</small></td>
          </tr>
          <tr v-if="!events.length">
            <td :colspan="9" class="empty-state">暂无操作记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ eventTotal }} 条操作记录，交班后仍可在此追溯</span></footer>
    </template>

    <!-- 开单弹窗 -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>开具接电单</h3>
        <div class="form-grid">
          <label><span>船舶编号</span><input v-model="form.vessel_code" placeholder="如 VESS-0881" /></label>
          <label><span>船名</span><input v-model="form.vessel_name" placeholder="编号、船名至少填一个" /></label>
          <label><span>泊位 *</span><input v-model="form.berth_code" placeholder="如 B-03" /></label>
          <label><span>接电箱 *</span><input v-model="form.box_code" placeholder="如 BOX-B03-01" /></label>
          <label><span>航次</span><input v-model="form.voyage" placeholder="选填" /></label>
          <label><span>开单当班人</span><input v-model="form.operator" /></label>
        </div>
        <p class="modal-hint">同船已有未收口接电单时只返回第一张；同泊位复靠会延续上一张。</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">开具</button>
        </div>
      </div>
    </div>

    <!-- 动作弹窗：插枪 / 掉电 / 结算 -->
    <div v-if="modal && modal !== 'create' && modal !== 'trail'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>{{ modalTitle }} · {{ activeRow?.order_no }}</h3>
        <div class="form-grid">
          <template v-if="modal === 'energize'">
            <label :class="{ required: needsStartReading }">
              <span>{{ needsStartReading ? '起始电表抄见数 *' : '恢复抄见数(选填)' }}</span>
              <input v-model.number="form.meter_reading" type="number" step="0.01"
                :placeholder="needsStartReading ? '首次通电必须填' : '沿用首次起始读数'" />
            </label>
            <label :class="{ required: needsGuns }">
              <span>插接枪数 {{ needsGuns ? '*' : '(选填)' }}</span>
              <input v-model.number="form.gun_count" type="number" min="1"
                :placeholder="needsGuns ? '插了几条' : '沿用上次'" />
            </label>
          </template>
          <template v-else-if="modal === 'dropout'">
            <label class="required"><span>掉电原因 *</span>
              <input v-model="form.reason" placeholder="如 接电箱漏保跳闸" /></label>
            <label><span>掉电时抄见数(选填)</span>
              <input v-model.number="form.meter_reading" type="number" step="0.01" /></label>
          </template>
          <template v-else>
            <label class="required"><span>结算电表抄见数 *</span>
              <input v-model.number="form.meter_end" type="number" step="0.01" :placeholder="`不小于起始 ${activeRow?.meter_start ?? ''}`" /></label>
            <label><span>拔枪枪数(选填)</span>
              <input v-model.number="form.gun_count" type="number" min="1" placeholder="默认沿用接枪数" /></label>
          </template>
          <label><span>当班处理人</span><input v-model="form.operator" /></label>
        </div>
        <p v-if="modal === 'dropout'" class="modal-hint warn">掉电后接电单退回「待接」，需重新插枪通电才能结算，不能直接收口。</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">确认</button>
        </div>
      </div>
    </div>

    <!-- 轨迹弹窗 -->
    <div v-if="modal === 'trail'" class="modal-mask" @click.self="closeModal">
      <div class="modal wide">
        <h3>接电单轨迹 · {{ activeRow?.order_no }}（{{ activeRow?.vessel_name }}）</h3>
        <table class="data-table">
          <thead><tr><th>时间</th><th>动作</th><th>变化</th><th>处理人</th><th>工班</th><th>明细</th></tr></thead>
          <tbody>
            <tr v-for="ev in trail" :key="ev.id">
              <td><small>{{ ev.at }}</small></td>
              <td>{{ ev.action }}</td>
              <td>{{ ev.from_status ?? '—' }} → {{ ev.to_status ?? '—' }}</td>
              <td>{{ ev.operator }}</td>
              <td>{{ ev.shift }}</td>
              <td><small v-for="(v, k) in detailPairs(ev.detail)" :key="k">{{ k }}：{{ v }}；</small></td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot"><button class="btn" type="button" @click="closeModal">关闭</button></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const ENDPOINT = '/api/shorepower'
const STATUSES = ['待接', '已通电', '已结算']

type Row = Record<string, any>
type ModalKind = '' | 'create' | 'energize' | 'dropout' | 'settle' | 'trail'

const tabs = [
  { key: 'orders', label: '接电单' },
  { key: 'ledger', label: '随船台账' },
  { key: 'events', label: '当班审计' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('orders')
const modal = ref<ModalKind>('')
const submitting = ref(false)
const message = ref('')
const activeRow = ref<Row | null>(null)

const orders = ref<Row[]>([])
const orderTotal = ref(0)
const orderFilter = reactive({ keyword: '', status: '' })

const ledger = ref<Row[]>([])

const events = ref<Row[]>([])
const eventTotal = ref(0)
const eventFilter = reactive({ vessel: '', operator: '', shift: '' })

const trail = ref<Row[]>([])

const summary = ref({
  total_orders: 0, waiting: 0, energized: 0, settled: 0,
  open_chains: 0, outage_count: 0, active_guns: 0, total_kwh: 0,
})
const statCards = computed(() => [
  { label: '累计供电量(度)', value: summary.value.total_kwh },
  { label: '待接', value: summary.value.waiting },
  { label: '已通电(在供)', value: summary.value.energized },
  { label: '在接枪数', value: summary.value.active_guns },
  { label: '已结算', value: summary.value.settled },
  { label: '掉电回退(次)', value: summary.value.outage_count },
])

const emptyForm = () => ({
  vessel_code: '', vessel_name: '', berth_code: '', box_code: '', voyage: '',
  operator: session.operator, meter_reading: null as number | null,
  meter_end: null as number | null, gun_count: null as number | null, reason: '',
})
const form = reactive(emptyForm())

const modalTitle = computed(
  () => ({ energize: '插枪通电', dropout: '登记中途掉电', settle: '拔枪结算' } as const)[
    modal.value as 'energize' | 'dropout' | 'settle'
  ] ?? '',
)
const needsStartReading = computed(() => activeRow.value?.meter_start == null)
const needsGuns = computed(() => activeRow.value?.gun_count == null)

function badgeClass(status: string) {
  return { 待接: 'b-wait', 已通电: 'b-on', 已结算: 'b-done' }[status] ?? ''
}
function chainNo(row: Row) {
  return row.root_id ? `SP-${String(row.root_id).padStart(4, '0')}` : row.order_no
}
function detailPairs(detail: Record<string, any> | undefined | null) {
  return detail ?? {}
}

async function refreshSummary() {
  try {
    const res = await request(`${ENDPOINT}/summary`)
    if (res.ok) summary.value = await res.json()
  } catch {
    /* 总览刷新失败不阻断操作 */
  }
}

async function reloadOrders() {
  message.value = ''
  const qs = new URLSearchParams()
  if (orderFilter.keyword) qs.set('keyword', orderFilter.keyword)
  if (orderFilter.status) qs.set('status', orderFilter.status)
  try {
    const res = await request(`${ENDPOINT}?${qs.toString()}`)
    const payload = await res.json()
    if (!res.ok) throw new Error('接电单列表读取失败')
    orders.value = payload.items ?? []
    orderTotal.value = payload.total ?? 0
  } catch (error) {
    message.value = error instanceof Error ? error.message : '接电单列表读取失败'
  }
}
function resetOrderFilter() {
  orderFilter.keyword = ''
  orderFilter.status = ''
  void reloadOrders()
}

async function reloadLedger() {
  try {
    const res = await request(`${ENDPOINT}/ledger`)
    const payload = await res.json()
    ledger.value = payload.items ?? []
  } catch {
    /* 台账读取失败保持原状 */
  }
}

async function reloadEvents() {
  const qs = new URLSearchParams()
  if (eventFilter.vessel) qs.set('vessel', eventFilter.vessel)
  if (eventFilter.operator) qs.set('operator', eventFilter.operator)
  if (eventFilter.shift) qs.set('shift', eventFilter.shift)
  try {
    const res = await request(`${ENDPOINT}/events?${qs.toString()}`)
    const payload = await res.json()
    events.value = payload.items ?? []
    eventTotal.value = payload.total ?? 0
  } catch {
    /* 审计读取失败保持原状 */
  }
}
function resetEventFilter() {
  eventFilter.vessel = ''
  eventFilter.operator = ''
  eventFilter.shift = ''
  void reloadEvents()
}

function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  if (key === 'ledger') void reloadLedger()
  if (key === 'events') void reloadEvents()
}

function openCreate() {
  Object.assign(form, emptyForm())
  modal.value = 'create'
}
function openEnergize(row: Row) {
  activeRow.value = row
  Object.assign(form, emptyForm())
  modal.value = 'energize'
}
function openDropout(row: Row) {
  activeRow.value = row
  Object.assign(form, emptyForm())
  modal.value = 'dropout'
}
function openSettle(row: Row) {
  activeRow.value = row
  Object.assign(form, emptyForm())
  modal.value = 'settle'
}
async function openTrail(row: Row) {
  activeRow.value = row
  modal.value = 'trail'
  trail.value = []
  try {
    const res = await request(`${ENDPOINT}/${row.id}/events`)
    if (res.ok) {
      const payload = await res.json()
      trail.value = payload.items ?? []
    }
  } catch {
    /* 轨迹读取失败展示空表 */
  }
}
function closeModal() {
  modal.value = ''
  activeRow.value = null
}

async function postAction(url: string, body: Record<string, any>, after: () => void) {
  submitting.value = true
  message.value = ''
  try {
    const res = await request(url, { method: 'POST', body: JSON.stringify(body) })
    const payload = await res.json()
    if (!res.ok || !payload.ok) {
      message.value = payload.message || '操作未生效'
      return
    }
    message.value = payload.message
    closeModal()
    after()
    await refreshSummary()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '操作未送达'
  } finally {
    submitting.value = false
  }
}

function submitCreate() {
  void postAction(
    ENDPOINT,
    {
      vessel_code: form.vessel_code || null,
      vessel_name: form.vessel_name || null,
      berth_code: form.berth_code || null,
      box_code: form.box_code || null,
      voyage: form.voyage || null,
      operator: form.operator || session.operator,
    },
    () => {
      void reloadOrders()
      if (activeTab.value === 'ledger') void reloadLedger()
    },
  )
}

function submitAction() {
  if (!activeRow.value) return
  const body: Record<string, any> = {
    action: modalTitle.value,
    operator: form.operator || session.operator,
  }
  if (modal.value === 'energize') {
    if (form.meter_reading != null) body.meter_reading = form.meter_reading
    if (form.gun_count != null) body.gun_count = form.gun_count
  } else if (modal.value === 'dropout') {
    body.reason = form.reason
    if (form.meter_reading != null) body.meter_reading = form.meter_reading
  } else {
    body.meter_end = form.meter_end
    if (form.gun_count != null) body.gun_count = form.gun_count
  }
  void postAction(`${ENDPOINT}/${activeRow.value.id}/actions`, body, () => {
    void reloadOrders()
    if (activeTab.value === 'ledger') void reloadLedger()
  })
}

onMounted(() => {
  void refreshSummary()
  void reloadOrders()
})
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin: 8px 0 12px; }
.tab-btn { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
.tab-btn.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.b-wait { background: #fef3c7; color: #92400e; }
.b-on { background: #dcfce7; color: #166534; }
.b-done { background: #e2e8f0; color: #334155; }
tr.abnormal td { background: #fef2f2; }
.cell-note { color: #b42318; font-size: 12px; margin-top: 2px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { color: var(--muted); }
.kwh { color: var(--brand); }
.link.warn { color: #b42318; }
.ledger-book { background: #fff; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 14px; overflow: hidden; }
.ledger-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid var(--border); font-size: 14px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 520px; max-width: 92vw; max-height: 88vh; overflow: auto; }
.modal.wide { width: 760px; }
.modal h3 { margin: 0 0 14px; font-size: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-grid input { width: 100%; padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; }
.form-grid label.required span { color: #b42318; }
.modal-hint { font-size: 12px; color: var(--muted); margin: 12px 0 0; }
.modal-hint.warn { color: #b42318; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
select { padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; }
</style>
