<template>
  <div class="app">
    <header class="topbar">
      <div>
        <h1>AI CAD Copilot</h1>
        <span class="subtitle">自然语言 → Design Engine → 实时操作正在运行的 FreeCAD</span>
      </div>
      <div class="top-actions">
        <div class="live-health" :class="freecadConnected ? 'connected' : 'disconnected'">
          {{ freecadConnected ? 'FreeCAD Connected' : 'FreeCAD Disconnected' }}
          <span v-if="freecadStatus.active_document">· {{ freecadStatus.active_document }}</span>
        </div>
        <button @click="runDemo" :disabled="busy" class="btn demo-btn" title="旧版离线流程，仅用于兼容验证">
          旧版离线流程
        </button>
        <div class="health" :class="healthOk ? 'ok' : 'bad'">
          {{ healthText }}
        </div>
      </div>
    </header>

    <!-- Demo 流程进度 -->
    <div v-if="demoSteps.length" class="demo-progress">
      <div v-for="(s, si) in demoSteps" :key="s.id" class="demo-step" :class="{ done: s.done, active: si === demoIdx }">
        <span class="demo-num">{{ si + 1 }}</span>
        <span class="demo-title">{{ s.title }}</span>
        <span v-if="s.done" class="demo-ok">✓</span>
      </div>
    </div>

    <main class="layout">
      <!-- 左侧：输入与参数 -->
      <section class="panel input-panel">
        <div class="live-agent-box">
          <h2>Live FreeCAD Agent</h2>
          <p class="live-help">命令会直接操作当前打开的 FreeCAD GUI，不启动 FreeCADCmd。</p>
          <textarea v-model="liveQuery" rows="3"
            placeholder="例如：创建一个300mm阶梯轴"></textarea>
          <div class="examples">
            <button class="chip" @click="liveQuery = '创建一个300mm阶梯轴'">300mm 阶梯轴</button>
            <button class="chip" @click="liveQuery = '创建一个M10螺栓'">M10 螺栓</button>
          </div>
          <div class="actions">
            <button @click="runLiveAgent" :disabled="busy || !freecadConnected" class="btn live-primary">
              在 FreeCAD 中执行
            </button>
            <button @click="createTestBox" :disabled="busy || !freecadConnected" class="btn">
              创建测试盒子
            </button>
          </div>
          <div v-if="liveMessage" class="live-result" :class="liveError ? 'bad' : 'ok'">
            {{ liveMessage }}
          </div>
          <div v-if="liveTree.length" class="live-tree">
            <b>当前 Feature Tree</b>
            <div v-for="obj in liveTree" :key="obj.name" class="tree-row">
              <span>{{ obj.name }}</span><code>{{ obj.type_id }}</code>
            </div>
          </div>
        </div>

        <h2>旧版文件生成（兼容模式）</h2>
        <p class="live-help">此区域保留旧版能力，不作为 AI CAD 2.0 的主验收路径。</p>
        <textarea v-model="nlText" rows="4"
          placeholder="例如：生成一个M10×40的六角头螺栓，8.8级，螺纹长度25mm，材料40Cr，表面发黑"></textarea>
        <div class="examples">
          <button v-for="ex in examples" :key="ex" @click="nlText = ex" class="chip">{{ ex }}</button>
        </div>
        <div class="actions">
          <button @click="parse" :disabled="busy" class="btn">解析参数</button>
          <button @click="generate" :disabled="busy || !spec" class="btn primary">生成 3D 模型 + 工程图</button>
        </div>

        <div v-if="spec" class="spec-box">
          <div class="spec-head">
            <b>识别：{{ partMeta.name }}</b>（{{ spec.part_name }} · 来源：{{ spec.source }}）
          </div>
          <div v-for="f in partMeta.fields" :key="f.name" class="field">
            <label>{{ f.label }}<span v-if="f.unit"> ({{ f.unit }})</span></label>
            <input v-if="f.type === 'number'" type="number" :value="fieldVal(f)"
              @change="setField(f, $event.target.value)" />
            <input v-else-if="f.type === 'text'" type="text" :value="fieldVal(f)"
              @change="setField(f, $event.target.value)" />
            <input v-else-if="f.type === 'list'" :value="fieldVal(f)" disabled class="readonly" />
            <input v-else :value="fieldVal(f)" disabled class="readonly" />
          </div>
          <div v-if="spec.params.derived" class="derived">
            <b>派生尺寸</b>
            <ul>
              <li v-for="(v, k) in spec.params.derived" :key="k">{{ k }} = {{ v }} mm</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- 右侧：结果 -->
      <section class="panel result-panel">
        <h2>旧版文件结果</h2>
        <div v-if="!sessionId" class="empty">AI CAD 2.0 的实时执行结果显示在左侧 Live FreeCAD Agent 区域。</div>

        <template v-if="sessionId">
          <div v-if="result" class="result-box">
            <div class="result-title" :class="result.ok ? 'ok' : 'bad'">
              {{ result.ok ? '✔ 模型与工程图生成成功' : '✘ 生成失败' }}
            </div>

            <div v-if="svgUrl" class="drawing">
              <h3>工程图（SVG）</h3>
              <iframe :src="svgUrl" class="svg-frame"></iframe>
            </div>

            <div class="files">
              <h3>生成文件</h3>
              <a v-for="(f, key) in files" :key="key" :href="f" class="file-link" target="_blank">
                {{ key.toUpperCase() }} 下载
              </a>
            </div>

            <div v-if="demoDuration" class="demo-report">
              ⏱ Demo 全流程 {{ demoDuration }}s（预算 180s）·
              <a :href="demoReport" target="_blank">📄 查看优化报告</a>
            </div>
          </div>

          <div class="checks">
            <h3>图纸审查</h3>
            <div class="actions">
              <button @click="runValidate" :disabled="busy" class="btn">规则检查</button>
              <button @click="runDrawingReview" :disabled="busy" class="btn">工程图审查</button>
              <button @click="runStepReview" :disabled="busy" class="btn">STEP 模型审查</button>
              <button @click="runLlmReview" :disabled="busy" class="btn">LLM 深度审查</button>
            </div>

            <div v-for="(grp, gi) in issueGroups" :key="gi" class="issues">
              <h4>{{ grp.title }}</h4>
              <div v-if="!grp.items.length" class="pass">✓ 未发现明显问题</div>
              <table v-else class="issue-table">
                <thead><tr><th>级别</th><th>问题项</th><th>工程分析</th><th>建议</th><th>依据标准</th></tr></thead>
                <tbody>
                  <tr v-for="(it, ii) in grp.items" :key="ii">
                    <td><span class="lvl" :class="it.level">{{ lvlText(it.level) }}</span>
                        <span v-if="it.risk_cn" class="risk">{{ it.risk_cn }}</span></td>
                    <td>{{ it.item }}</td>
                    <td>{{ it.detail || it.analysis }}</td>
                    <td>{{ it.suggestion || it.recommendation }}</td>
                    <td class="std">{{ it.standard || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="stepFeatures" class="issues step-features">
              <h4>STEP 特征（OpenCascade 提取）</h4>
              <div class="feature-chips">
                <span class="chip">面 {{ stepFeatures.faces }}</span>
                <span class="chip" v-for="h in stepFeatures.holes" :key="h.d">
                  φ{{ h.d }}×{{ h.count }}</span>
                <span class="chip" v-for="w in (stepFeatures.wall_thickness||[]).slice(0,3)" :key="w.hole_d">
                  壁厚 {{ w.wall }}mm</span>
                <span class="chip">倒角 {{ stepFeatures.chamfers }}</span>
                <span class="chip">圆角 {{ (stepFeatures.fillets||[]).length }}</span>
                <span class="chip">体积 {{ stepFeatures.volume }}mm³</span>
              </div>
            </div>

            <div v-if="reviewFiles" class="issues">
              <h4>工程图一致性</h4>
              <div v-for="(res, fn) in reviewFiles" :key="fn" class="review-file">
                <b>{{ fn }}</b>
                <span :class="res.passed ? 'pass' : 'bad'">{{ res.passed ? '通过' : '存在问题' }}</span>
                <ul v-if="!res.passed">
                  <li v-for="(p, i) in res.problems" :key="i">
                    [{{ p.risk_cn }}] {{ p.problem }} → {{ p.suggestion }}
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </template>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const nlText = ref('')
const spec = ref(null)
const partMetas = ref({})
const sessionId = ref(null)
const result = ref(null)
const busy = ref(false)
const healthText = ref('检测中…')
const healthOk = ref(false)
const ruleIssues = ref([])
const llmIssues = ref([])
const stepIssues = ref([])
const stepFeatures = ref(null)
const reviewFiles = ref(null)
const svgUrl = ref('')
const demoSteps = ref([])
const demoIdx = ref(-1)
const demoReport = ref('')
const demoDuration = ref(0)
const liveQuery = ref('创建一个300mm阶梯轴')
const freecadStatus = ref({})
const freecadConnected = ref(false)
const liveMessage = ref('')
const liveError = ref(false)
const liveTree = ref([])
let freecadTimer = null

const examples = ref([
  '生成一个M10×40的六角头螺栓，8.8级，螺纹长度25mm，材料40Cr，表面发黑',
  '做一个阶梯轴：直径25×60、30×40、35×50，末端倒角C1，材料45钢',
  '设计法兰盘：外径160mm，内径50mm，厚度18mm，8个M10螺栓孔，分度圆130mm',
  '直齿圆柱齿轮：模数2.5，齿数20，齿宽25mm，孔径30mm，8级精度',
])

const partMeta = computed(() => {
  if (!spec.value) return { fields: [] }
  return partMetas.value[spec.value.part_type] || { fields: [] }
})

const files = computed(() => {
  if (!result.value) return {}
  const out = {}
  for (const [k, p] of Object.entries(result.value.files || {})) out[k] = fileUrl(p)
  for (const [k, p] of Object.entries(result.value.drawing || {})) out['drawing_' + k] = fileUrl(p)
  return out
})

const issueGroups = computed(() => [
  { title: '规则检查（参数 + 输出完整性）', items: ruleIssues.value },
  { title: 'STEP 模型审查（OpenCascade）', items: stepIssues.value },
  { title: 'LLM 深度审查', items: llmIssues.value },
])

const api = (path, opts = {}) =>
  fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      return data
    })

const fileUrl = (p) => {
  if (!p || !sessionId.value) return '#'
  const name = String(p).split(/[\\/]/).pop()
  return `/api/sessions/${sessionId.value}/files/${encodeURIComponent(name)}`
}

const fieldVal = (f) => {
  const v = spec.value.params[f.name]
  if (Array.isArray(v) || typeof v === 'object') return JSON.stringify(v)
  return v ?? f.default ?? ''
}

const setField = (f, v) => {
  const num = f.type === 'number' ? parseFloat(v) : v
  spec.value.params[f.name] = Number.isNaN(num) ? v : num
  spec.value.params.derived = undefined
}

const lvlText = (l) => ({ error: '错误', warning: '警告', info: '提示' }[l] || l)

onMounted(async () => {
  try {
    const h = await api('/api/health')
    healthOk.value = true
    healthText.value = `旧版离线兼容: ${h.freecad_cmd_compat ? '可用' : '未配置'} · API Key: ${h.api_key ? '已配置' : '未配置'}`
    partMetas.value = (await api('/api/part-types')).parts
    examples.value = Object.values(partMetas.value).flatMap((m) => m.examples || [])
  } catch (e) {
    healthText.value = '后端连接失败: ' + e.message
  }
  await refreshFreecadStatus()
  freecadTimer = window.setInterval(refreshFreecadStatus, 2000)
})

onUnmounted(() => {
  if (freecadTimer) window.clearInterval(freecadTimer)
})

async function refreshFreecadStatus() {
  try {
    freecadStatus.value = await api('/api/freecad/status')
    freecadConnected.value = !!freecadStatus.value.freecad_online
  } catch (_) {
    freecadConnected.value = false
  }
}

async function runLiveAgent() {
  if (!liveQuery.value.trim()) return alert('请输入 Live FreeCAD 命令')
  busy.value = true
  liveError.value = false
  liveMessage.value = 'Design Engine 正在生成 CadPlan…'
  try {
    const r = await api('/api/freecad/agent', {
      method: 'POST', body: JSON.stringify({ query: liveQuery.value }),
    })
    liveMessage.value = r.message
    liveTree.value = r.execution?.tree?.objects || []
    await refreshFreecadStatus()
  } catch (e) {
    liveError.value = true
    liveMessage.value = e.message
  } finally {
    busy.value = false
  }
}

async function createTestBox() {
  busy.value = true
  liveError.value = false
  try {
    const r = await api('/api/freecad/create-box', { method: 'POST', body: '{}' })
    liveMessage.value = `已创建 ${r.object}（50×30×20mm）`
    const doc = await api('/api/freecad/document')
    liveTree.value = doc.objects || []
    await refreshFreecadStatus()
  } catch (e) {
    liveError.value = true
    liveMessage.value = e.message
  } finally {
    busy.value = false
  }
}

async function parse() {
  if (!nlText.value.trim()) return alert('请先输入零件描述')
  busy.value = true
  try {
    const r = await api('/api/parse', { method: 'POST', body: JSON.stringify({ text: nlText.value }) })
    spec.value = r.spec
    sessionId.value = (await api('/api/sessions', { method: 'POST' })).id
    result.value = null
    ruleIssues.value = []; llmIssues.value = []; reviewFiles.value = null; svgUrl.value = ''
  } catch (e) {
    alert('解析失败：' + e.message)
  } finally {
    busy.value = false
  }
}

async function generate() {
  busy.value = true
  try {
    result.value = await api(`/api/sessions/${sessionId.value}/parts`, {
      method: 'POST',
      body: JSON.stringify({ part_type: spec.value.part_type, part_name: spec.value.part_name, params: spec.value.params }),
    })
    svgUrl.value = fileUrl(result.value.drawing?.svg)
    runValidate()
  } catch (e) {
    alert('生成失败：' + e.message)
  } finally {
    busy.value = false
  }
}

async function runValidate() {
  try { ruleIssues.value = (await api(`/api/sessions/${sessionId.value}/validate`)).issues || [] }
  catch (e) { alert(e.message) }
}

async function runDrawingReview() {
  try {
    const r = await api(`/api/sessions/${sessionId.value}/drawing-review`)
    reviewFiles.value = r.files
  } catch (e) { alert(e.message) }
}

async function runStepReview() {
  busy.value = true
  try {
    const r = await api(`/api/sessions/${sessionId.value}/step-review`)
    stepIssues.value = r.problems || []
    stepFeatures.value = r.features || null
  } catch (e) { alert(e.message) }
  finally { busy.value = false }
}

async function runLlmReview() {
  busy.value = true
  try { llmIssues.value = (await api(`/api/sessions/${sessionId.value}/review`)).issues || [] }
  catch (e) { alert(e.message) }
  finally { busy.value = false }
}

async function runDemo() {
  busy.value = true
  demoSteps.value = [
    { id: 'input', title: '用户需求', done: false },
    { id: 'analysis', title: 'AI 需求理解', done: false },
    { id: 'recommend', title: '机械参数推荐', done: false },
    { id: 'model', title: 'FreeCAD CAD 生成', done: false },
    { id: 'drawing', title: '工程图生成', done: false },
    { id: 'review', title: 'CAD 智能审查', done: false },
    { id: 'report', title: '优化建议输出', done: false },
  ]
  demoIdx.value = 0
  try {
    const r = await api('/api/demo/run', { method: 'POST', body: '{}' })
    demoDuration.value = r.duration_s || 0
    const steps = r.steps || {}
    // 填充模型与工程图展示
    sessionId.value = steps.model?.session_id
    result.value = { ok: true, files: steps.model?.files || {}, drawing: { svg: steps.drawing?.svg } }
    svgUrl.value = fileUrl(steps.drawing?.svg)
    ruleIssues.value = steps.review?.rule || []
    stepIssues.value = steps.review?.step || []
    llmIssues.value = steps.review?.llm || []
    demoReport.value = '/api/demo/report'
    demoSteps.value.forEach((s) => { s.done = true })
    demoIdx.value = -1
  } catch (e) {
    alert('Demo 运行失败：' + e.message)
  } finally {
    busy.value = false
  }
}
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; background: #f0f2f5; color: #222; }
.app { min-height: 100vh; }
.topbar { background: #1d2939; color: #fff; padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; }
.topbar h1 { font-size: 20px; }
.subtitle { font-size: 12px; color: #9fb0c7; margin-left: 10px; }
.health { font-size: 12px; padding: 5px 12px; border-radius: 12px; }
.health.ok { background: #16a34a22; color: #4ade80; }
.health.bad { background: #dc262622; color: #f87171; }
.live-health { font-size: 12px; padding: 6px 12px; border-radius: 14px; font-weight: 700; }
.live-health.connected { background: #dcfce7; color: #166534; }
.live-health.disconnected { background: #fee2e2; color: #991b1b; }
.layout { display: grid; grid-template-columns: 400px 1fr; gap: 16px; padding: 16px; max-width: 1400px; margin: 0 auto; }
.panel { background: #fff; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px #00000018; }
.panel h2 { font-size: 15px; margin-bottom: 12px; border-bottom: 2px solid #1d2939; padding-bottom: 8px; }
.live-agent-box { border: 2px solid #4f46e5; border-radius: 10px; padding: 12px; margin-bottom: 18px; background: #f8f7ff; }
.live-agent-box h2 { color: #3730a3; border-bottom-color: #4f46e5; }
.live-help { color: #5b5b75; font-size: 12px; margin: -4px 0 10px; }
.btn.live-primary { background: #4f46e5; border-color: #4f46e5; color: #fff; }
.live-result { padding: 8px; border-radius: 6px; font-size: 12px; line-height: 1.5; margin-top: 8px; word-break: break-all; }
.live-result.ok { background: #ecfdf3; color: #067647; }
.live-result.bad { background: #fef3f2; color: #b42318; }
.live-tree { margin-top: 10px; max-height: 240px; overflow: auto; font-size: 12px; }
.tree-row { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; border-bottom: 1px solid #e5e7eb; }
.tree-row code { color: #4f46e5; font-size: 10px; }
textarea { width: 100%; padding: 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; resize: vertical; }
.examples { margin: 10px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: #eef2f7; border: 1px solid #d7dee8; border-radius: 14px; padding: 4px 10px; font-size: 11px; cursor: pointer; color: #334; }
.chip:hover { background: #dde6f0; }
.actions { display: flex; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
.btn { background: #eef2f7; border: 1px solid #c9d3e0; border-radius: 6px; padding: 8px 14px; font-size: 13px; cursor: pointer; }
.btn:hover:not(:disabled) { background: #dde6f0; }
.btn.primary { background: #1d2939; color: #fff; border-color: #1d2939; }
.btn.primary:hover:not(:disabled) { background: #2d3a4d; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.spec-box { margin-top: 14px; border: 1px solid #e5e9f0; border-radius: 8px; padding: 12px; background: #fafbfd; }
.spec-head { font-size: 13px; margin-bottom: 10px; }
.field { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 13px; }
.field label { width: 130px; flex-shrink: 0; }
.field input { flex: 1; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 5px; font-size: 13px; }
.field input.readonly { background: #f1f3f6; color: #666; }
.derived { margin-top: 10px; font-size: 12px; color: #555; }
.derived ul { margin: 6px 0 0 16px; }
.empty { color: #999; font-size: 13px; padding: 40px 0; text-align: center; }
.result-box .result-title { padding: 10px 12px; border-radius: 6px; font-size: 14px; margin-bottom: 12px; }
.result-title.ok { background: #ecfdf3; color: #067647; }
.result-title.bad { background: #fef3f2; color: #b42318; }
.drawing h3, .files h3, .checks h3 { font-size: 13px; margin: 10px 0 8px; }
.svg-frame { width: 100%; height: 560px; border: 1px solid #e5e9f0; border-radius: 6px; background: #fff; }
.files { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.file-link { display: inline-block; background: #eef2f7; border: 1px solid #c9d3e0; padding: 6px 12px; border-radius: 6px; font-size: 12px; text-decoration: none; color: #1d2939; }
.file-link:hover { background: #dde6f0; }
.checks h3 { border-top: 2px solid #eef2f7; padding-top: 10px; }
.issues h4 { font-size: 13px; margin: 10px 0 6px; color: #334; }
.pass { color: #067647; font-size: 13px; }
.bad { color: #b42318; }
.issue-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.issue-table th, .issue-table td { border: 1px solid #e5e9f0; padding: 5px 8px; text-align: left; }
.issue-table th { background: #f8fafc; }
.lvl { padding: 2px 6px; border-radius: 4px; font-size: 11px; }
.lvl.error { background: #fee2e2; color: #b42318; }
.lvl.warning { background: #fef3c7; color: #92400e; }
.lvl.info { background: #dbeafe; color: #1e40af; }
.risk { font-size: 10px; color: #888; margin-left: 4px; }
.std { color: #2563eb; font-size: 11px; }
.feature-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.feature-chips .chip { background: #eef2f7; border: 1px solid #d7dee8; border-radius: 12px; padding: 3px 10px; font-size: 11px; }
.top-actions { display: flex; align-items: center; gap: 14px; }
.demo-btn { background: #4f46e5 !important; color: #fff !important; font-size: 14px; padding: 8px 16px; }
.demo-progress { display: flex; gap: 6px; padding: 10px 24px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
.demo-step { display: flex; align-items: center; gap: 6px; background: #eef2f7; border-radius: 20px; padding: 4px 12px; font-size: 12px; color: #64748b; }
.demo-step.active { background: #4f46e5; color: #fff; }
.demo-step.done { background: #dcfce7; color: #166534; }
.demo-num { background: #cbd5e1; color: #334155; border-radius: 50%; width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; }
.demo-step.done .demo-num { background: #86efac; }
.demo-step.active .demo-num { background: #a5b4fc; }
.demo-ok { color: #16a34a; font-weight: bold; }
.demo-report { margin: 6px 0; font-size: 12px; color: #4f46e5; word-break: break-all; }
.review-file { font-size: 12px; margin: 6px 0; }
.review-file ul { margin: 4px 0 0 18px; color: #555; }
</style>
