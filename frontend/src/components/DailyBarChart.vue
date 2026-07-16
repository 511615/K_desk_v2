<script setup lang="ts">
import { computed } from 'vue'

type Bar = { date?: string; profit?: number }
const props = defineProps<{ data?: Bar[] }>()
const visible = computed(() => (props.data || []).slice(-30))
const maxAbs = computed(() => Math.max(1, ...visible.value.map(item => Math.abs(Number(item.profit) || 0))))
const format = (value: number) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
</script>

<template>
  <div class="daily-bars" role="img" aria-label="每日净盈亏柱图" v-if="visible.length">
    <div v-for="item in visible" :key="item.date" class="daily-bar-cell" :title="`${item.date} · ${Number(item.profit) >= 0 ? '+' : ''}${format(Number(item.profit))}`">
      <div class="bar-half top"><i v-if="Number(item.profit) >= 0" class="bar positive-bar" :style="{height:`${Math.max(3, Math.abs(Number(item.profit))/maxAbs*100)}%`}" /></div>
      <div class="bar-half bottom"><i v-if="Number(item.profit) < 0" class="bar negative-bar" :style="{height:`${Math.max(3, Math.abs(Number(item.profit))/maxAbs*100)}%`}" /></div>
      <small>{{ String(item.date || '').slice(5) }}</small>
    </div>
  </div>
</template>
