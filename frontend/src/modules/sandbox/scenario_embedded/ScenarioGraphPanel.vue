<template>
  <main class="main-panel scenario-graph-panel">
    <slot />
  </main>
</template>

<style scoped>
.scenario-graph-panel {
  min-height: 0;
  overflow: auto;
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: none;
  padding: 6px;
}
</style>
