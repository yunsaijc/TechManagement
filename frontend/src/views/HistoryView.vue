<script setup>
import { useRouter } from 'vue-router';
import { computed, onMounted } from 'vue';
import { useHistoryStore } from '../stores/history';
import { useRequestStore } from '../stores/request';
import { useUiStore } from '../stores/ui';
import HistoryPanel from '../components/HistoryPanel.vue';

const router = useRouter();
const hist = useHistoryStore();
const req = useRequestStore();
const ui = useUiStore();

const historyStats = computed(() => ({
  total: hist.requestHistory.length,
  success: hist.requestHistory.filter((x) => x.ok).length,
  fail: hist.requestHistory.filter((x) => !x.ok).length,
}));

onMounted(() => {
  hist.load();
});

function goBack() {
  router.push({ name: 'workbench' });
}
</script>

<template>
  <div class="main-content">
    <div class="module-header">
      <p>集中查看全部请求记录与重试状态</p>
    </div>

    <div class="content-scroll">
      <section class="panel-shell panel-shell-stretch">
        <div class="panel-shell-head">历史明细</div>
        <HistoryPanel
          :request-history="hist.requestHistory"
          :history-stats="historyStats"
          :show-stats="false"
          @replay="async (item) => { try { await req.fetchWithTimeout(item.url, { method: item.method }, 60000); ui.toast('已重新发送'); } catch (e) { ui.toast(String(e), 'error', 3000); } }"
          @clear="() => { hist.clear(); ui.toast('历史已清空'); }"
        />
      </section>
    </div>
  </div>
</template>
