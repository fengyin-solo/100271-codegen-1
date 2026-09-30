<template>
  <section class="page" data-module="shorepower">
    <header class="page-head">
      <div>
        <h2>岸电接电台账</h2>
        <p class="page-desc">
          接电单随船走动：靠泊开单、插枪通电、掉电退回待接、拔枪结算收口；
          同船重复提交只认第一张，同泊位复靠自动延续，供电量按电表抄见数结算。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">靠泊开接电单</button>
        <button class="btn" type="button" @click="exportRows">导出台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>单号 / 船舶</span>
        <input v-model="filters.keyword" placeholder="按接电单号、船舶编号或船名检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>泊位</span>
        <input v-model="filters.berth" placeholder="按泊位编号检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['接电单号'] }}</td>
          <td>{{ row['泊位编号'] }}</td>
          <td>{{ row['船名'] }}<div class="sub-text">{{ row['船舶编号'] }}</div></td>
          <td>{{ row['接电箱号'] || '—' }}</td>
          <td><span class="status-tag" :data-status="row.status">{{ row.status }}</span></td>
          <td>{{ row['续靠次数'] }}</td>
          <td>{{ row['起始读数'] ?? '—' }}</td>
          <td>{{ row['末次抄见数'] ?? '—' }}</td>
          <td>{{ row['供电量'] }}</td>
          <td>
            <span v-if="row['掉电原因']" class="outage-text">{{ row['掉电原因'] }}</span>
            <span v-else>—</span>
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">台账明细</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              :class="{ danger: action === '掉电复位' }"
              type="button"
              @click="openAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无接电单，靠泊后先开一张接电单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张接电单</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 开单弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>靠泊开接电单</h3>
        <p class="modal-tip">
          同一艘船已有未收口单据时只认第一张；同一泊位复靠会自动接上一张延续，不另开新单。
          当前当班：{{ session.operator }} · {{ session.shiftLabel }}
        </p>
        <div class="form-grid">
          <label><span>泊位编号 *</span><input v-model="createForm['泊位编号']" placeholder="如 BERT-001" /></label>
          <label><span>船舶编号 *</span><input v-model="createForm['船舶编号']" placeholder="如 VESS-1001" /></label>
          <label><span>船名 *</span><input v-model="createForm['船名']" /></label>
          <label><span>接电箱号</span><input v-model="createForm['接电箱号']" placeholder="如 BOX-A12" /></label>
          <label class="grid-span-2">
            <span>电表起始抄见数</span>
            <input v-model="createForm['起始读数']" placeholder="插枪时也可补录，留空按 0 起算" />
          </label>
        </div>
        <p v-if="actionError" class="error-text">{{ actionError }}</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">开具接电单</button>
        </div>
      </div>
    </div>

    <!-- 动作弹窗 -->
    <div v-if="actionOpen" class="modal-mask" @click.self="actionOpen = false">
      <div class="modal">
        <h3>{{ currentAction }} · {{ currentRow?.['接电单号'] }}</h3>
        <p class="modal-tip">
          {{ currentRow?.['船名'] }}（{{ currentRow?.['泊位编号'] }}）·
          当前状态：{{ currentRow?.status }} · 经办人：{{ session.operator }}（{{ session.shiftLabel }}）
        </p>

        <div v-if="currentAction === '插枪通电'" class="form-grid">
          <label class="grid-span-2">
            <span>电表起始抄见数</span>
            <input v-model="actionForm['起始读数']" placeholder="留空则取开单底数，再缺按 0 起算" />
          </label>
        </div>

        <div v-else-if="currentAction === '掉电复位'" class="form-grid">
          <label class="grid-span-2">
            <span>掉电原因 *</span>
            <textarea v-model="actionForm['掉电原因']" rows="3" placeholder="如：接电箱跳闸、电缆受拽脱落……不注明原因不能复位"></textarea>
          </label>
          <label class="grid-span-2">
            <span>掉电时抄见数</span>
            <input v-model="actionForm['末次抄见数']" placeholder="选填，填写后截算本段已供电量" />
          </label>
        </div>

        <div v-else-if="currentAction === '重新插枪'">
          <p v-if="currentRow?.['末次抄见数']" class="modal-tip">
            单据处于掉电待接状态，重新插枪后将沿用上段止数
            <strong>{{ currentRow?.['末次抄见数'] }}</strong> 继续计量，不允许直接收口。
          </p>
          <div v-else class="form-grid">
            <label class="grid-span-2">
              <span>本次插枪电表抄见数 *</span>
              <input v-model="actionForm['起始读数']" placeholder="掉电时没抄表，重新插枪必须补一次读数以截算上段" />
            </label>
          </div>
        </div>

        <div v-else-if="currentAction === '拔枪结算'" class="form-grid">
          <label class="grid-span-2">
            <span>电表末次抄见数 *</span>
            <input v-model="actionForm['末次抄见数']" placeholder="末数未填不允许结算" />
          </label>
        </div>

        <p v-if="actionError" class="error-text">{{ actionError }}</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="actionOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">确认{{ currentAction }}</button>
        </div>
      </div>
    </div>

    <!-- 台账明细：接电段 + 当班处理追溯 -->
    <div v-if="detailOpen" class="modal-mask" @click.self="detailOpen = false">
      <div class="modal modal-wide">
        <h3>接电单台账 · {{ detail?.['接电单号'] }}</h3>
        <p class="modal-tip">
          {{ detail?.['船名'] }}（{{ detail?.['船舶编号'] }}）停靠 {{ detail?.['泊位编号'] }}，
          接电箱 {{ detail?.['接电箱号'] || '—' }}，复靠 {{ detail?.['续靠次数'] }} 次，
          累计供电 <strong>{{ detail?.['供电量'] }}</strong> 度。
          开单：{{ detail?.['开单经办人'] }}（{{ detail?.['开单工班'] }}）{{ detail?.['开单时间'] }}；
          收口：{{ detail?.['收口经办人'] || '—' }}<template v-if="detail?.['收口工班']">（{{ detail?.['收口工班'] }}）</template>{{ detail?.['收口时间'] || '' }}
        </p>

        <h4 class="section-title">接电段（按电表抄见数逐段计量）</h4>
        <table class="data-table inner-table">
          <thead>
            <tr><th>段次</th><th>起数</th><th>止数</th><th>段供电量(度)</th><th>插枪</th><th>收口</th><th>掉电原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="seg in detail?.['接电段']" :key="seg['段次']">
              <td>{{ seg['段次'] }}</td>
              <td>{{ seg['起数'] }}</td>
              <td>{{ seg['止数'] ?? '—' }}</td>
              <td>{{ seg['段供电量'] ?? '—' }}</td>
              <td>{{ seg['插枪经办人'] }}<div class="sub-text">{{ seg['插枪时间'] }}</div></td>
              <td>{{ seg['收口时间'] ?? '—' }}</td>
              <td>{{ seg['掉电原因'] || '—' }}</td>
            </tr>
            <tr v-if="!detail?.['接电段']?.length">
              <td colspan="7" class="empty-state">尚未插枪，暂无接电段</td>
            </tr>
          </tbody>
        </table>

        <h4 class="section-title">处理记录（交班后按此追溯当班人）</h4>
        <table class="data-table inner-table">
          <thead>
            <tr><th>时间</th><th>动作</th><th>经办人</th><th>当班工班</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="(rec, idx) in detail?.['处理记录']" :key="idx">
              <td>{{ rec['时间'] }}</td>
              <td>{{ rec['动作'] }}</td>
              <td>{{ rec['经办人'] }}</td>
              <td>{{ rec['工班'] }}</td>
              <td>{{ rec['说明'] }}</td>
            </tr>
          </tbody>
        </table>

        <div class="modal-foot">
          <button class="btn primary" type="button" @click="detailOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/shorepower'
const session = useSessionStore()

type Segment = {
  段次: number
  起数: string
  止数: string | null
  段供电量: string | null
  插枪时间: string
  收口时间: string | null
  插枪经办人: string
  插枪工班: string
  掉电原因: string
}
type Trace = { 时间: string; 动作: string; 经办人: string; 工班: string; 说明: string }
type Order = {
  id: number
  接电单号: string
  泊位编号: string
  船舶编号: string
  船名: string
  接电箱号: string
  status: string
  续靠次数: number
  起始读数: string | null
  末次抄见数: string | null
  供电量: string
  掉电原因: string
  开单时间: string
  开单经办人: string
  开单工班: string
  收口时间: string | null
  收口经办人: string | null
  收口工班: string | null
  接电段: Segment[]
  处理记录: Trace[]
}
type Summary = {
  接电单总数: number
  待接单数: number
  通电中单数: number
  已收口单数: number
  已结算接电段: number
  累计供电量: number
}

const columns = ['接电单号', '泊位', '船舶', '接电箱号', '状态', '复靠', '起始读数', '末次抄见数', '供电量(度)', '掉电原因']
const statuses = ['待接', '已通电', '已收口']

const rows = ref<Order[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '', berth: '' })
const stats = ref<{ label: string; value: number | string }[]>([
  { label: '接电单总数', value: 0 },
  { label: '待接', value: 0 },
  { label: '通电中', value: 0 },
  { label: '已收口', value: 0 },
  { label: '已结算接电段', value: 0 },
  { label: '累计供电量(度)', value: 0 },
])

const createOpen = ref(false)
const createForm = ref<Record<string, string>>({ 泊位编号: '', 船舶编号: '', 船名: '', 接电箱号: '', 起始读数: '' })

const actionOpen = ref(false)
const currentAction = ref('')
const currentRow = ref<Order | null>(null)
const actionForm = ref<Record<string, string>>({})
const actionError = ref('')
const submitting = ref(false)

const detailOpen = ref(false)
const detail = ref<Order | null>(null)

function availableActions(row: Order): string[] {
  if (row.status === '已通电') return ['掉电复位', '拔枪结算']
  if (row.status === '待接') return [row['掉电原因'] ? '重新插枪' : '插枪通电']
  return []
}

function resetFilters() {
  filters.value = { keyword: '', status: '', berth: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = { 泊位编号: '', 船舶编号: '', 船名: '', 接电箱号: '', 起始读数: '' }
  actionError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  actionError.value = ''
  submitting.value = true
  try {
    const payload = Object.fromEntries(Object.entries(createForm.value).filter(([, v]) => v.trim()))
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { 经办人: session.operator, 当班工班: session.shiftLabel, ...payload } }),
    })
    const result = await response.json().catch(() => ({ ok: false, message: '接口返回异常' }))
    if (!result.ok) {
      // 重复提交/复靠延续都把原单带回来，列表照常刷新，错误文案放到弹窗里提示。
      actionError.value = result.message
      await reload()
      return
    }
    createOpen.value = false
    errorMessage.value = result.message
    await reload()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '开单失败'
  } finally {
    submitting.value = false
  }
}

function openAction(action: string, row: Order) {
  currentAction.value = action
  currentRow.value = row
  actionForm.value = {}
  actionError.value = ''
  actionOpen.value = true
}

async function submitAction() {
  if (!currentRow.value) return
  actionError.value = ''
  submitting.value = true
  try {
    const values: Record<string, string> = {
      action: currentAction.value,
      经办人: session.operator,
      当班工班: session.shiftLabel,
    }
    for (const [key, val] of Object.entries(actionForm.value)) {
      if (val.trim()) values[key] = val.trim()
    }
    const response = await request(`${ENDPOINT}/${currentRow.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const result = await response.json().catch(() => ({ ok: false, message: '接口返回异常' }))
    if (!result.ok) {
      actionError.value = result.message
      return
    }
    actionOpen.value = false
    errorMessage.value = result.message
    await reload()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: Order) {
  detail.value = null
  detailOpen.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('台账明细读取失败')
    detail.value = await response.json()
  } catch (error) {
    detailOpen.value = false
    errorMessage.value = error instanceof Error ? error.message : '台账明细读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  if (filters.value.berth) query.set('berth', filters.value.berth)
  try {
    const [listResp, summaryResp] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/summary`),
    ])
    if (!listResp.ok) throw new Error('接电单列表读取失败')
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (summaryResp.ok) {
      const summary = (await summaryResp.json()) as Summary
      stats.value = [
        { label: '接电单总数', value: summary['接电单总数'] },
        { label: '待接', value: summary['待接单数'] },
        { label: '通电中', value: summary['通电中单数'] },
        { label: '已收口', value: summary['已收口单数'] },
        { label: '已结算接电段', value: summary['已结算接电段'] },
        { label: '累计供电量(度)', value: summary['累计供电量'] },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接电单列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.sub-text { color: var(--muted); font-size: 12px; }
.outage-text { color: #b42318; }
.status-tag {
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 12px; border: 1px solid var(--border);
}
.status-tag[data-status='待接'] { background: #f2f4f7; color: #475467; }
.status-tag[data-status='已通电'] { background: #ecfdf3; color: #027a48; border-color: #abefc6; }
.status-tag[data-status='已收口'] { background: #eff8ff; color: #175cd3; border-color: #b2ddff; }
.link.danger { color: #b42318; margin-left: 8px; }
.link + .link { margin-left: 8px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal {
  background: #fff; border-radius: 10px; padding: 20px 24px;
  width: 560px; max-width: 92vw; max-height: 88vh; overflow: auto;
}
.modal-wide { width: 880px; }
.modal h3 { margin: 0 0 8px; }
.modal-tip { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
.form-grid label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-grid input, .form-grid textarea, .form-grid select {
  width: 100%; box-sizing: border-box; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 6px; font: inherit;
}
.grid-span-2 { grid-column: span 2; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.section-title { margin: 18px 0 8px; font-size: 14px; }
.inner-table { font-size: 12px; }
</style>
