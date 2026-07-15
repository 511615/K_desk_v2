<script setup lang="ts">
defineProps<{ loading?: boolean; error?: Error | null; empty?: boolean; emptyText?: string }>()
</script>

<template>
  <div v-if="loading" class="panel-state"><span class="spinner" /> 正在读取...</div>
  <div v-else-if="error" class="panel-state error">{{ error.message }}</div>
  <div v-else-if="empty" class="panel-state">{{ emptyText || '暂无数据' }}</div>
  <slot v-else />
</template>
