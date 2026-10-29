<template>
  <el-container class="app-root">
    <el-header class="app-header">
      <div class="brand">
        <el-icon :size="22"><Monitor /></el-icon>
        <span>GPU Queue Allocation</span>
      </div>
      <el-menu
        :default-active="active"
        mode="horizontal"
        class="nav-menu"
        @select="onSelect"
      >
        <el-menu-item index="overview">Overview</el-menu-item>
        <el-menu-item index="tasks">Tasks</el-menu-item>
        <el-menu-item index="gpus">GPUs</el-menu-item>
      </el-menu>
      <div class="conn-status">
        <el-badge :type="backendOk ? 'success' : 'danger'">
          <el-icon :size="16"><Connection v-if="backendOk" :size="16" /><CircleClose v-else /></el-icon>
        </el-badge>
        <span>{{ backendOk ? 'Backend online' : 'Backend offline' }}</span>
      </div>
    </el-header>

    <el-main class="app-main">
      <div v-if="active === 'overview'">
        <el-row :gutter="16" class="stats-row">
          <el-col :span="6">
            <el-card shadow="hover">
              <el-statistic title="Total GPUs" :value="gpus.length" />
              <el-progress :percentage="gpuIdlePercent" :stroke-width="10" :show-text="true" class="gpu-bar">
                <template #default="{ percentage }">
                <span class="gpu-bar-text">{{ percentage }}% · {{ gpus.filter(g => g.status === 'IDLE').length }} / {{ gpus.length }} idle</span>
                    </template>

              </el-progress>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <el-statistic title="Queued" :value="statusCounts.QUEUED" />
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <el-statistic title="Running" :value="statusCounts.RUNNING" />
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <el-statistic title="Completed / Failed" :value="statusCounts.COMPLETED + statusCounts.FAILED" />
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="16" class="main-row">
          <el-col :span="10">
            <el-card shadow="never" class="panel">
              <template #header>
                <span class="panel-title">Submit Task</span>
              </template>
              <el-form :model="submitForm" :rules="submitRules" ref="submitRef" label-width="100px">
                <el-form-item label="Task Name" prop="name">
                  <el-input v-model="submitForm.name" placeholder="e.g. training-run-01" maxlength="128" show-word-limit />
                </el-form-item>
                <el-form-item label="Command" prop="command">
                  <el-input v-model="submitForm.command" type="textarea" :rows="3" placeholder="e.g. python train.py --lr 0.001" />
                </el-form-item>
                <el-form-item label="GPU Count">
                  <el-input-number v-model="submitForm.gpu_count" :min="1" :max="Math.max(1, gpus.length)" />
                </el-form-item>
                <el-form-item label="GPU Preference">
                  <el-input v-model="submitForm.gpu_model_preference" placeholder="optional, e.g. RTX 3090" clearable />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" @click="submitTask" :loading="submitting">Submit</el-button>
                  <el-button @click="resetSubmit">Reset</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span class="panel-title">GPU Status</span>
                  <el-button link type="primary" @click="refreshAll">Refresh</el-button>
                </div>
              </template>
              <div v-if="gpus.length === 0" class="empty">
                <el-empty description="No GPUs registered" />
              </div>
              <div v-else class="gpu-grid">
                <div v-for="g in gpus" :key="g.id" class="gpu-card" :class="'gpu-' + g.status.toLowerCase()">
                  <div class="gpu-top">
                    <span class="gpu-name">{{ g.name }}</span>
                    <el-tag :type="gpuTagType(g.status)" effect="dark">{{ g.status }}</el-tag>
                  </div>
                  <div class="gpu-model">{{ g.model }}</div>
                  <div class="gpu-mem">{{ g.total_memory_mb }} MB</div>
                  <div class="gpu-task" v-if="g.current_task_id">Running task #{{ g.current_task_id }}</div>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </div>

      <div v-else-if="active === 'tasks'">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span class="panel-title">Task Queue</span>
              <div>
                <el-tag v-for="(c, k) in statusCounts" :key="k" type="info" class="count-tag">{{ k }}: {{ c }}</el-tag>
              </div>
            </div>
          </template>
          <el-table :data="tasks" stripe style="width: 100%" empty-text="No tasks yet">
            <el-table-column prop="id" label="#" width="60" />
            <el-table-column prop="name" label="Name" min-width="160" />
            <el-table-column prop="command" label="Command" min-width="200" show-overflow-tooltip />
            <el-table-column label="Status" width="130">
              <template #default="{ row }">
                <el-tag :type="taskTagType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Queue Pos" width="90" align="center">
              <template #default="{ row }">
                <span v-if="row.queue_position">#{{ row.queue_position }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="GPU" width="100" align="center">
              <template #default="{ row }">
                <span v-if="row.allocated_gpu_ids">#{{ row.allocated_gpu_ids.split(',').join(' #') }}</span>
                <span v-else-if="row.allocated_gpu_id">#{{ row.allocated_gpu_id }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="Submitted" width="170">
              <template #default="{ row }">{{ fmt(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="Duration" width="100" align="center">
              <template #default="{ row }">
                <span v-if="row.started_at && row.finished_at">{{ duration(row.started_at, row.finished_at) }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="Action" width="200" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="danger" :disabled="row.status !== 'QUEUED'" @click="cancelTask(row)">
                  Cancel
                </el-button>
                <el-button
                  v-if="row.status === 'RUNNING' || row.status === 'PENDING'"
                  size="small"
                  type="warning"
                  @click="terminateTask(row)"
                >
                  Terminate
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <div v-else-if="active === 'gpus'">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span class="panel-title">GPU Management</span>
              <el-button link type="primary" @click="refreshAll">Refresh</el-button>
            </div>
          </template>
          <el-table :data="gpus" stripe style="width: 100%" empty-text="No GPUs registered">
            <el-table-column prop="id" label="#" width="60" />
            <el-table-column prop="name" label="Name" width="140" />
            <el-table-column prop="model" label="Model" width="180" />
            <el-table-column prop="total_memory_mb" label="Memory (MB)" width="130" />
            <el-table-column label="Status" width="130">
              <template #default="{ row }">
                <el-tag :type="gpuTagType(row.status)" effect="dark">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Current Task" width="140">
              <template #default="{ row }">
                <span v-if="row.current_task_id">#{{ row.current_task_id }}</span>
                <span v-else class="muted">None</span>
              </template>
            </el-table-column>
            <el-table-column prop="notes" label="Notes" min-width="160" show-overflow-tooltip />
            <el-table-column prop="created_at" label="Created" width="170">
              <template #default="{ row }">{{ fmt(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Monitor, Connection, CircleClose } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const API_BASE = 'http://localhost:8000'

const active = ref('overview')
const backendOk = ref(false)
const gpus = ref([])
const tasks = ref([])
const submitting = ref(false)

const submitForm = ref({ name: '', command: '', gpu_count: 1, gpu_model_preference: '' })
const submitRef = ref(null)
const submitRules = {
  name: [{ required: true, message: 'Task name is required', trigger: 'blur' }],
  command: [{ required: true, message: 'Command is required', trigger: 'blur' }],
}

let pollTimer = null

async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function checkBackend() {
  try {
    await api('/health')
    backendOk.value = true
  } catch {
    backendOk.value = false
  }
}

async function refreshAll() {
  await checkBackend()
  if (!backendOk.value) return
  try {
    const [g, t] = await Promise.all([api('/gpus?page_size=100'), api('/tasks/admin?page_size=100')])
    gpus.value = g.items
    tasks.value = t.items
  } catch (e) {
    console.error('Refresh failed:', e)
  }
}

async function submitTask() {
  await submitRef.value.validate()
  submitting.value = true
  try {
    const payload = { ...submitForm.value }
    if (!payload.gpu_model_preference) delete payload.gpu_model_preference
    const created = await api('/tasks', { method: 'POST', body: JSON.stringify(payload) })
    ElMessage.success(`Task #${created.id} submitted (${created.status})`)
    resetSubmit()
    await refreshAll()
  } catch (e) {
    ElMessage.error('Submit failed: ' + e.message)
  } finally {
    submitting.value = false
  }
}

async function cancelTask(row) {
  try {
    const updated = await api(`/tasks/${row.id}/cancel`, { method: 'POST' })
    ElMessage.success(`Task #${updated.id} cancelled`)
    await refreshAll()
  } catch (e) {
    ElMessage.error('Cancel failed: ' + e.message)
  }
}

async function terminateTask(row) {
  try {
    await ElMessageBox.confirm(
      `Task #${row.id} is ${row.status.toLowerCase()}. Terminating will kill its process and release the GPU. Continue?`,
      'Terminate Task',
      { type: 'warning', confirmButtonText: 'Terminate', cancelButtonText: 'Cancel' }
    )
  } catch {
    return  // user cancelled the confirm dialog
  }
  try {
    const updated = await api(`/tasks/${row.id}/terminate`, { method: 'POST' })
    ElMessage.success(`Task #${updated.id} terminated (${updated.status})`)
    await refreshAll()
  } catch (e) {
    ElMessage.error('Terminate failed: ' + e.message)
  }
}

function resetSubmit() {
  submitForm.value = { name: '', command: '', gpu_count: 1, gpu_model_preference: '' }
  submitRef.value?.resetFields()
}

function onSelect(idx) { active.value = idx }

const statusCounts = computed(() => {
  const counts = { QUEUED: 0, PENDING: 0, RUNNING: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0, TERMINATED: 0 }
  tasks.value.forEach(t => { counts[t.status] = (counts[t.status] || 0) + 1 })
  return counts
})

const gpuIdlePercent = computed(() => {
  if (gpus.value.length === 0) return 0
  const idle = gpus.value.filter(g => g.status === 'IDLE').length
  return Math.round(idle / gpus.value.length * 100)
})

function gpuTagType(s) {
  return { IDLE: 'success', ALLOCATED: 'warning', RUNNING: 'primary', MAINTENANCE: 'info', FAULTY: 'danger' }[s] || 'info'
}

function taskTagType(s) {
  return { QUEUED: 'info', PENDING: 'warning', RUNNING: 'primary', COMPLETED: 'success', FAILED: 'danger', CANCELLED: 'info', TERMINATED: 'danger' }[s] || 'info'
}

function fmt(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString()
}

function duration(startIso, endIso) {
  const s = new Date(startIso).getTime()
  const e = new Date(endIso).getTime()
  const sec = Math.max(0, Math.round((e - s) / 1000))
  if (sec < 60) return sec + 's'
  const m = Math.floor(sec / 60)
  return m + 'm' + (sec % 60) + 's'
}

onMounted(() => {
  refreshAll()
  pollTimer = setInterval(refreshAll, 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.app-root { height: 100vh; }
.app-header {
  display: flex; align-items: center; gap: 32px;
  background: #fff; border-bottom: 1px solid #e4e7ed; padding: 0 24px;
}
.brand { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: #409eff; white-space: nowrap; }
.nav-menu { border-bottom: none; flex: 0; }
.conn-status { margin-left: auto; display: flex; align-items: center; gap: 8px; font-size: 13px; color: #606266; }
.app-main { background: #f5f7fa; padding: 20px; overflow-y: auto; }
.stats-row { margin-bottom: 16px; }
.gpu-bar { margin-top: 8px; }
.gpu-bar-text { font-size: 12px; color: #909399; }
.main-row { margin-top: 16px; }
.panel { border-radius: 4px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-weight: 600; font-size: 15px; color: #303133; }
.count-tag { margin-right: 4px; }
.gpu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.gpu-card {
  border: 2px solid #e4e7ed; border-radius: 8px; padding: 12px;
  background: #fafafa; transition: transform .1s;
}
.gpu-card:hover { transform: translateY(-2px); }
.gpu-idle { border-color: #67c23a; background: #f0f9eb; }
.gpu-running { border-color: #409eff; background: #ecf5ff; }
.gpu-allocated { border-color: #e6a23c; background: #fdf6ec; }
.gpu-maintenance { border-color: #909399; background: #f4f4f5; }
.gpu-faulty { border-color: #f56c6c; background: #fef0f0; }
.gpu-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.gpu-name { font-weight: 600; color: #303133; }
.gpu-model { font-size: 13px; color: #606266; margin-bottom: 2px; }
.gpu-mem { font-size: 12px; color: #909399; margin-bottom: 4px; }
.gpu-task { font-size: 12px; color: #409eff; font-weight: 500; }
.empty { padding: 40px 0; }
.muted { color: #c0c4cc; }
</style>