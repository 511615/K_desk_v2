<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import PanelState from '../components/PanelState.vue'

const router = useRouter()
const search = ref('')
const query = useQuery({ queryKey: ['accounts'], queryFn: () => api<any>('/api/accounts') })
const records = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return (query.data.value?.records || []).filter((row: any) => !needle || JSON.stringify(row).toLowerCase().includes(needle))
})

function openAccount(login = search.value.trim()) {
  if (login) router.push(`/account/${encodeURIComponent(login)}`)
}
</script>

<template>
  <header class="topbar"><div><b>K_desk v2</b><span>模块化开发环境 · 8877</span></div><a href="/?legacy=1">旧版完整工作台</a></header>
  <main class="workbench">
    <section class="hero">
      <div><div class="eyebrow">ACCOUNT RISK WORKBENCH</div><h1>账户风险工作台</h1><p>SQLite 台账与类型化 API 已启用；生产 8777 不受影响。</p></div>
      <div class="lookup"><input v-model="search" placeholder="输入账号或筛选台账" @keyup.enter="openAccount()"><button @click="openAccount()">打开账号</button></div>
    </section>
    <section class="summary-grid">
      <article><span>台账记录</span><strong>{{ query.data.value?.summary?.total ?? '-' }}</strong></article>
      <article><span>服务状态</span><strong class="positive">DEV READY</strong></article>
      <article><span>数据存储</span><strong>SQLite</strong></article>
    </section>
    <section class="panel"><div class="section-head"><h2>问题账户台账</h2><a href="/download/problematic_accounts.xlsx">导出 Excel</a></div>
      <PanelState :loading="query.isLoading.value" :error="query.error.value as Error">
        <div class="table-wrap"><table><thead><tr><th>账号</th><th>建议动作</th><th>当前分组</th><th>风险标签</th><th>状态</th><th>修改时间</th></tr></thead>
          <tbody><tr v-for="row in records" :key="row['记录ID']"><td><RouterLink :to="`/account/${encodeURIComponent(row['账号'])}`">{{ row['账号'] || '-' }}</RouterLink></td><td>{{ row['建议动作'] || '-' }}</td><td>{{ row['当前分组'] || '-' }}</td><td>{{ row['风险标签'] || '-' }}</td><td>{{ row['状态'] || '-' }}</td><td>{{ row['修改时间'] || '-' }}</td></tr></tbody>
        </table></div>
      </PanelState>
    </section>
  </main>
</template>
