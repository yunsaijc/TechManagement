<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  topicOptions: { type: Array, default: () => [] },
  selectedTopicIds: { type: Array, default: () => [] },
  keyword: { type: String, default: '' },
});

const emit = defineEmits(['apply-search', 'update:selectedTopicIds', 'update:keyword']);
const method = ref('increase_support');
const intensity = ref(65);
const effectiveYear = ref('2026');
const note = ref('对 7 个研究方向增加支持，新增经费 28.7 万元，新增项目 9 个');

const keywordModel = computed({
  get: () => props.keyword || '',
  set: (value) => emit('update:keyword', value),
});

const filteredTopicOptions = computed(() => {
  const kw = String(keywordModel.value || '').trim().toLowerCase();
  return (props.topicOptions || []).filter((item) => !kw || String(item.label || '').toLowerCase().includes(kw));
});

function apply() {
  emit('apply-search', keywordModel.value.trim());
}

function toggleTopic(id, checked) {
  const set = new Set((props.selectedTopicIds || []).map((item) => String(item)));
  if (checked) set.add(String(id));
  else set.delete(String(id));
  emit('update:selectedTopicIds', Array.from(set));
}

function clearSelection() {
  emit('update:selectedTopicIds', []);
}

function selectAll() {
  emit('update:selectedTopicIds', (props.topicOptions || []).map((item) => String(item.id)));
}
</script>

<template>
  <aside id="instructions" class="sidebar">
    <section class="sidebar-card">
      <div class="step-head"><span class="step-index">1</span><span>选择调整对象</span></div>
      <div class="field">
        <label for="selection-search-vue">搜索研究方向</label>
        <input id="selection-search-vue" v-model="keywordModel" class="input" type="search" placeholder="搜索研究方向" @input="apply">
      </div>
      <div class="toggle-row">
        <button class="toggle-btn active" type="button" @click="selectAll">全选</button>
        <button class="toggle-btn" type="button" @click="clearSelection">清空</button>
      </div>
      <div class="selection-panel">
        <div class="selection-group">
          <strong>研究方向（{{ filteredTopicOptions.length }}）</strong>
          <label v-for="item in filteredTopicOptions" :key="item.id" class="selection-item">
            <input type="checkbox" :checked="selectedTopicIds.includes(item.id)" @change="toggleTopic(item.id, $event.target.checked)">
            <div>
              <span>{{ item.label }}</span>
              <small>{{ item.id }}</small>
            </div>
          </label>
        </div>
      </div>
    </section>

    <section class="sidebar-card">
      <div class="step-head"><span class="step-index">2</span><span>设置调整方案</span></div>
      <div class="hint-box">本次怎么调：先选方式，再拖动幅度，最后确定生效时间。</div>
      <div class="field">
        <label for="adjustment-method-vue">调整方式</label>
        <select id="adjustment-method-vue" v-model="method" class="select">
          <option value="increase_support">增加支持</option>
          <option value="quota_adjustment">调整配额</option>
          <option value="budget_raise">增加经费</option>
        </select>
      </div>
      <div class="field">
        <label for="adjustment-intensity-vue">调整幅度</label>
        <div class="range-shell">
          <div class="range-row">
            <input id="adjustment-intensity-vue" v-model.number="intensity" class="range-input" type="range" min="-50" max="100" step="1">
            <div class="range-value">{{ intensity }}</div>
          </div>
          <div class="range-scale"><span>-50%</span><span>0%</span><span>+50%</span><span>+100%</span></div>
        </div>
      </div>
      <div class="field">
        <label for="effective-year-vue">生效时间</label>
        <select id="effective-year-vue" v-model="effectiveYear" class="select">
          <option value="2025">2025年</option>
          <option value="2026">2026年</option>
          <option value="2027">2027年</option>
        </select>
      </div>
      <div class="field">
        <label for="scenario-note-vue">方案备注（选填）</label>
        <textarea id="scenario-note-vue" v-model="note" class="textarea" placeholder="请输入方案备注..." />
      </div>
    </section>

    <section class="sidebar-card">
      <div class="step-head"><span class="step-index">3</span><span>运行推演</span></div>
      <button class="run-btn" type="button" @click="apply">运行推演</button>
      <div class="eta">预计耗时：约 30 秒</div>
    </section>
  </aside>
</template>

<style scoped>
.sidebar { min-height: 0; overflow: auto; padding-right: 2px; }
.sidebar-card { border: 1px solid #e5eaf2; border-radius: 12px; background: #fff; padding: 10px; margin-bottom: 10px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03); }
.step-head { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #334155; }
.step-index { width: 18px; height: 18px; border-radius: 999px; background: #e8efff; color: #3563dc; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 800; }
.field { margin-top: 8px; }
.field label { display: block; margin-bottom: 4px; font-size: 12px; color: #5d6f86; }
.input,.select,.textarea { width: 100%; border: 1px solid #d9e2ef; border-radius: 8px; padding: 7px 9px; font-size: 12px; color: #1f2a37; background: #fff; }
.textarea { min-height: 64px; resize: vertical; }
.toggle-row { margin-top: 8px; display: flex; gap: 8px; }
.toggle-btn { height: 28px; padding: 0 10px; border: 1px solid #d6deeb; border-radius: 999px; background: #f7f9fc; color: #3b4f68; font-size: 12px; cursor: pointer; }
.toggle-btn.active { color: #2b63df; background: #edf3ff; border-color: #b9caf3; }
.selection-panel { margin-top: 8px; border: 1px solid #e7ecf4; border-radius: 10px; max-height: 240px; overflow: auto; padding: 8px; background: #fbfcff; }
.selection-group > strong { font-size: 12px; color: #5b6f89; }
.selection-item { margin-top: 6px; display: grid; grid-template-columns: 16px minmax(0,1fr); gap: 8px; align-items: start; }
.selection-item span { font-size: 12px; color: #223247; line-height: 1.45; }
.selection-item small { display: block; color: #8a97a8; font-size: 10px; line-height: 1.3; }
.hint-box { margin-top: 8px; font-size: 11px; color: #6c7b90; background: #f7f9fd; border: 1px dashed #d8e1ee; border-radius: 8px; padding: 7px 8px; }
.range-shell { margin-top: 4px; }
.range-row { display: flex; align-items: center; gap: 8px; }
.range-input { width: 100%; }
.range-value { min-width: 34px; text-align: center; font-size: 11px; color: #2b63df; border: 1px solid #cdd9ec; border-radius: 8px; background: #fff; padding: 3px 0; }
.range-scale { margin-top: 4px; display: flex; justify-content: space-between; font-size: 10px; color: #8a97a8; }
.run-btn { width: 100%; height: 34px; border: 1px solid #b8caf6; border-radius: 10px; background: linear-gradient(180deg, #e8efff, #dce8ff); color: #2e61da; font-size: 13px; font-weight: 700; cursor: pointer; }
.eta { margin-top: 6px; font-size: 11px; color: #8794a6; text-align: center; }
</style>
