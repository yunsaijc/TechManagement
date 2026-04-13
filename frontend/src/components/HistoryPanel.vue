<script setup>
defineProps({
  requestHistory: { type: Array, required: true },
  historyStats: { type: Object, required: true },
  showStats: { type: Boolean, default: true },
});

const emit = defineEmits(['replay', 'clear']);
</script>

<template>
  <div class="history-container">
    <div class="history-header">
      <div class="history-title">📜 请求历史</div>
      <div v-if="showStats" class="history-stats">
        <div class="history-stat">
          <div class="history-stat-dot" style="background:#e5e7eb"></div>
          共 {{ historyStats.total }} 条
        </div>
        <div class="history-stat">
          <div class="history-stat-dot success"></div>
          成功 {{ historyStats.success }}
        </div>
        <div class="history-stat">
          <div class="history-stat-dot fail"></div>
          失败 {{ historyStats.fail }}
        </div>
      </div>
    </div>

    <div v-if="requestHistory.length" class="history-list">
      <div v-for="(item, idx) in requestHistory" :key="idx" class="history-item">
        <div class="history-status" :class="item.ok ? 'success' : 'fail'"></div>
        <div class="history-info">
          <div class="history-item-title">{{ item.title }}</div>
          <div class="history-details">{{ item.method }} | {{ item.time }}</div>
        </div>
        <div class="history-actions">
          <button v-if="item.ok" class="history-btn" @click="emit('replay', item)">🔄 重试</button>
        </div>
      </div>
    </div>

    <div v-else class="result-content history-empty">
      <div class="result-json">暂无请求历史，先执行任意功能后会在此集中展示。</div>
    </div>

    <div class="button-group history-footer">
      <button class="btn btn-secondary" :disabled="!requestHistory.length" @click="emit('clear')">🗑️ 清空历史</button>
    </div>
  </div>
</template>
