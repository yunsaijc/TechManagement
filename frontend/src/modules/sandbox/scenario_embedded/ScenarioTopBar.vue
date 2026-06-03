<script setup>
defineProps({
  title: {
    type: String,
    default: '政策沙盘推演',
  },
  subtitle: {
    type: String,
    default: '',
  },
});

const emit = defineEmits(['guide', 'examples', 'export']);
</script>

<template>
  <header class="scenario-topbar">
    <div class="brand">
      <div class="brand-mark">政</div>
      <div class="brand-copy">
        <h1>{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </div>
    </div>
    <div class="top-actions">
      <button type="button" class="ghost-link" @click="emit('guide')">操作指南</button>
      <button type="button" class="ghost-link" @click="emit('examples')">使用案例</button>
      <button type="button" class="action-btn primary" @click="emit('export')">导出报告</button>
    </div>
  </header>
</template>

<style scoped>
.scenario-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid #e4e9f2;
  background: #f8fafd;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, #4f86ff, #2f69d9);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
}
.brand-copy h1 {
  margin: 0;
  font-size: 16px;
  line-height: 1.2;
}
.brand-copy p {
  margin: 2px 0 0;
  font-size: 11px;
  color: #72839a;
}
.top-actions {
  display: flex;
  gap: 8px;
}
.ghost-link,
.action-btn {
  height: 34px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid #d7deea;
  background: #f6f8fb;
  color: #2f3540;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.action-btn.primary {
  border-color: #b8caf6;
  background: #e4ecff;
  color: #3563dc;
}
</style>
