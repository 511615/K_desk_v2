<script setup lang="ts">
import { computed } from 'vue'

type Point = { time?: string; value?: number; change?: number }
const props = defineProps<{ data?: Point[]; height?: number }>()

const width = 1000
const height = computed(() => props.height || 220)
const padding = { top: 18, right: 18, bottom: 28, left: 64 }
const sampled = computed(() => {
  const source = (props.data || []).filter(item => Number.isFinite(Number(item.value)))
  if (source.length <= 260) return source
  const step = Math.ceil(source.length / 260)
  return source.filter((_, index) => index % step === 0 || index === source.length - 1)
})
const values = computed(() => sampled.value.map(item => Number(item.value)))
const minimum = computed(() => Math.min(0, ...(values.value.length ? values.value : [0])))
const maximum = computed(() => Math.max(0, ...(values.value.length ? values.value : [1])))
const range = computed(() => Math.max(maximum.value - minimum.value, 1))
const x = (index: number) => padding.left + (index / Math.max(sampled.value.length - 1, 1)) * (width - padding.left - padding.right)
const y = (value: number) => padding.top + ((maximum.value - value) / range.value) * (height.value - padding.top - padding.bottom)
const path = computed(() => sampled.value.map((item, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(1)} ${y(Number(item.value)).toFixed(1)}`).join(' '))
const areaPath = computed(() => {
  if (!path.value) return ''
  const floor = height.value - padding.bottom
  return `${path.value} L ${x(sampled.value.length - 1)} ${floor} L ${x(0)} ${floor} Z`
})
const zeroY = computed(() => y(0))
const ticks = computed(() => Array.from({ length: 5 }, (_, index) => maximum.value - (range.value * index) / 4))
const format = (value: number) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
</script>

<template>
  <div class="svg-chart" v-if="sampled.length">
    <svg :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="累计净盈亏曲线" preserveAspectRatio="none">
      <defs>
        <linearGradient id="pnlArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#14a7ff" stop-opacity=".34" />
          <stop offset="1" stop-color="#14a7ff" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g class="grid-lines">
        <template v-for="tick in ticks" :key="tick">
          <line :x1="padding.left" :x2="width-padding.right" :y1="y(tick)" :y2="y(tick)" />
          <text :x="padding.left-10" :y="y(tick)+4" text-anchor="end">{{ format(tick) }}</text>
        </template>
      </g>
      <line class="zero-line" :x1="padding.left" :x2="width-padding.right" :y1="zeroY" :y2="zeroY" />
      <path :d="areaPath" fill="url(#pnlArea)" />
      <path :d="path" class="pnl-line" />
      <text class="axis-label" :x="padding.left" :y="height-7">{{ sampled[0]?.time || '' }}</text>
      <text class="axis-label" :x="width-padding.right" :y="height-7" text-anchor="end">{{ sampled[sampled.length-1]?.time || '' }}</text>
    </svg>
  </div>
</template>
