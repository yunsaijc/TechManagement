<script setup>
import ResultDisplay from '../../components/ResultDisplay.vue';
import { computed, onMounted, ref, watch } from 'vue';
import { useGroupingStore } from '../../stores/grouping';

const store = useGroupingStore();
const activeDatasetKey = ref('');
const searchKeyword = ref('');
const selectedKeyword = ref('');

const activeDataset = computed(() => {
  if (!Array.isArray(store.fixedResults) || !store.fixedResults.length) return null;
  return store.fixedResults.find((x) => x.key === activeDatasetKey.value) || store.fixedResults[0];
});

const navOptions = computed(() => {
  const payload = activeDataset.value?.payload;
  const groups = Array.isArray(payload?.groups) ? payload.groups : [];
  const seen = new Set();
  const out = [];

  groups.forEach((g) => {
    const subjectName = String(g?.subject_name || '').trim();
    if (subjectName && !seen.has(subjectName)) {
      seen.add(subjectName);
      out.push(subjectName);
    }
    const subjectCode = String(g?.subject_code || '').trim();
    if (subjectCode && !seen.has(subjectCode)) {
      seen.add(subjectCode);
      out.push(subjectCode);
    }
  });

  return out.slice(0, 600);
});

const activeFilter = computed(() => {
  const typed = String(searchKeyword.value || '').trim();
  if (typed) return typed;
  return String(selectedKeyword.value || '').trim();
});

const activeFilterExact = computed(() => {
  const typed = String(searchKeyword.value || '').trim();
  if (typed) return false;
  return Boolean(String(selectedKeyword.value || '').trim());
});

watch(
  () => store.fixedResults,
  (next) => {
    if (!Array.isArray(next) || !next.length) {
      activeDatasetKey.value = '';
      clearFilter();
      return;
    }
    if (!activeDatasetKey.value || !next.some((x) => x.key === activeDatasetKey.value)) {
      activeDatasetKey.value = next[0].key;
    }
  },
  { immediate: true },
);

function selectDataset(key) {
  activeDatasetKey.value = key;
}

function clearFilter() {
  searchKeyword.value = '';
  selectedKeyword.value = '';
}

onMounted(() => {
  if (!store.activeActionId) {
    store.initialize();
  }
  store.loadFixedResults();
});
</script>

<template>
  <div class="content-scroll">
    <section class="panel-shell panel-shell-stretch">
      <template v-if="store.fixedResults && store.fixedResults.length">
        <div class="grouping-dataset-switcher">
          <button
            v-for="item in store.fixedResults"
            :key="`tab_${item.key}`"
            type="button"
            class="grouping-dataset-tab"
            :class="{ active: item.key === activeDatasetKey }"
            @click="selectDataset(item.key)"
          >
            {{ item.title }}
          </button>
        </div>

        <div v-if="activeDataset" class="grouping-dataset-block">
          <div class="grouping-filter-bar">
            <div class="grouping-filter-field">
              <label class="grouping-filter-label" for="grouping-filter-input">模糊搜索</label>
              <input
                id="grouping-filter-input"
                v-model="searchKeyword"
                type="text"
                class="grouping-filter-input"
                placeholder="输入学科名 / 学科编码"
              >
            </div>
            <div class="grouping-filter-field">
              <label class="grouping-filter-label" for="grouping-filter-select">快速选择</label>
              <select id="grouping-filter-select" v-model="selectedKeyword" class="grouping-filter-select">
                <option value="">请选择学科</option>
                <option v-for="item in navOptions" :key="`nav_${item}`" :value="item">{{ item }}</option>
              </select>
            </div>
            <button type="button" class="grouping-filter-clear" @click="clearFilter">清空</button>
          </div>

          <ResultDisplay
            :request-meta="store.requestMeta"
            :summary-items="store.summaryItems"
            :is-markdown-report-payload="store.isMarkdownReportPayload"
            :last-result="{ data: activeDataset.payload }"
            :result-cards="store.resultCards"
            :result-text="store.resultText"
            :module-id="store.moduleId"
            :action-id="store.activeActionId"
            :grouping-filter="activeFilter"
            :grouping-filter-exact="activeFilterExact"
          />
        </div>
      </template>
      <ResultDisplay
        v-else-if="store.lastResult || store.resultText"
        :request-meta="store.requestMeta"
        :summary-items="store.summaryItems"
        :is-markdown-report-payload="store.isMarkdownReportPayload"
        :last-result="store.lastResult"
        :result-cards="store.resultCards"
        :result-text="store.resultText"
        :module-id="store.moduleId"
        :action-id="store.activeActionId"
      />
      <div v-else-if="store.loadingFixedResult" class="result-container grouping-skeleton-container">
        <div class="result-summary result-summary-inline-3">
          <div class="summary-item">
            <div class="summary-key">项目数</div>
            <div class="grouping-skeleton-bar grouping-skeleton-value"></div>
          </div>
          <div class="summary-item">
            <div class="summary-key">分组数</div>
            <div class="grouping-skeleton-bar grouping-skeleton-value"></div>
          </div>
          <div class="summary-item">
            <div class="summary-key">平均每组项目数</div>
            <div class="grouping-skeleton-bar grouping-skeleton-value"></div>
          </div>
        </div>

        <div class="grouping-table-wrap">
          <table class="grouping-table">
            <thead>
              <tr>
                <th class="grouping-col-subject">学科名称</th>
                <th class="grouping-col-code">学科编码</th>
                <th class="grouping-col-count">项目数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="i in 8" :key="i" class="grouping-skeleton-row">
                <td class="grouping-cell grouping-col-subject">
                  <div class="grouping-skeleton-bar grouping-skeleton-subject"></div>
                </td>
                <td class="grouping-cell grouping-col-code">
                  <div class="grouping-skeleton-bar grouping-skeleton-code"></div>
                </td>
                <td class="grouping-cell grouping-col-count">
                  <div class="grouping-skeleton-bar grouping-skeleton-count"></div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else class="result-empty-state">
        <div class="result-empty-title">分组结果加载失败</div>
        <div class="result-empty-desc">请检查后端服务后刷新页面重试。</div>
      </div>
    </section>
  </div>
</template>
