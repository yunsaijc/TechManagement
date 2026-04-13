<script setup>
const props = defineProps({
  action: { type: Object, default: null },
  formData: { type: Object, required: true },
  files: { type: Object, required: true },
  requestInProgress: { type: Boolean, default: false },
  lastResult: { type: [Object, String, null], default: null },
});

const emit = defineEmits(['file-change', 'file-remove', 'submit', 'stop-request', 'fill-example', 'copy-result', 'clear-result']);

function fileLabel(fileField) {
  if (!fileField) return '';
  if (Array.isArray(fileField)) return `${fileField.length} 个文件已选择`;
  return fileField.name || '';
}

function isMultiSelected(fieldName, optionValue) {
  const current = props.formData[fieldName];
  return Array.isArray(current) && current.includes(optionValue);
}

function toggleMultiSelect(fieldName, optionValue) {
  const current = Array.isArray(props.formData[fieldName]) ? [...props.formData[fieldName]] : [];
  const next = current.includes(optionValue)
    ? current.filter((value) => value !== optionValue)
    : [...current, optionValue];
  props.formData[fieldName] = next;
}
</script>

<template>
  <div v-if="action" class="form">
    <div v-for="field in action.fields" :key="field.name" class="form-group">
      <label v-if="field.type !== 'checkbox'" class="form-label">
        {{ field.label }}
        <span v-if="field.required" class="required">*</span>
      </label>

      <input
        v-if="field.type === 'text'"
        v-model="formData[field.name]"
        class="form-control"
        :placeholder="field.placeholder"
      >

      <select
        v-else-if="field.type === 'select'"
        v-model="formData[field.name]"
        class="form-control"
      >
        <option
          v-for="option in field.options || []"
          :key="option.value"
          :value="option.value"
        >
          {{ option.label }}
        </option>
      </select>

      <input
        v-else-if="field.type === 'number'"
        v-model="formData[field.name]"
        type="number"
        class="form-control number"
        :placeholder="field.placeholder"
      >

      <textarea
        v-else-if="field.type === 'textarea'"
        v-model="formData[field.name]"
        class="form-control textarea"
        :placeholder="field.placeholder"
      />

      <div v-else-if="field.type === 'multi-select'" class="multi-select-group">
        <button
          v-for="option in field.options || []"
          :key="option.value"
          type="button"
          class="multi-select-option"
          :class="{ selected: isMultiSelected(field.name, option.value) }"
          @click="toggleMultiSelect(field.name, option.value)"
        >
          <span class="multi-select-option-label">{{ option.label }}</span>
          <span v-if="option.description" class="multi-select-option-desc">{{ option.description }}</span>
        </button>
        <p v-if="field.helpText" class="form-help-text">{{ field.helpText }}</p>
      </div>

      <div v-else-if="field.type === 'checkbox'" class="checkbox-group">
        <input
          :id="field.name"
          v-model="formData[field.name]"
          type="checkbox"
          class="checkbox"
        >
        <label :for="field.name" class="checkbox-label">{{ field.label }}</label>
      </div>

      <div v-else-if="field.type === 'file'" class="file-upload">
        <div class="file-upload-icon">FILE</div>
        <div class="file-upload-text">选择文件</div>
        <div class="file-upload-hint">点击上传或拖拽文件</div>
        <input
          type="file"
          class="file-upload-input"
          @change="emit('file-change', field, $event.target.files)"
        >
      </div>
      <div class="file-list" v-if="field.type === 'file' && files[field.name]">
        <div class="file-tag">
          <span>{{ fileLabel(files[field.name]) }}</span>
          <button type="button" class="file-tag-remove" @click="emit('file-remove', field, 0)" aria-label="移除">×</button>
        </div>
      </div>

      <div v-else-if="field.type === 'file-multi'" class="file-upload">
        <div class="file-upload-icon">FILES</div>
        <div class="file-upload-text">选择多个文件</div>
        <div class="file-upload-hint">至少需要2个文件（可多次选择，会自动合并）</div>
        <input
          type="file"
          multiple
          class="file-upload-input"
          @change="emit('file-change', field, $event.target.files)"
        >
      </div>
      <div class="file-list" v-if="field.type === 'file-multi' && files[field.name]?.length">
        <div v-for="(file, idx) in files[field.name]" :key="idx" class="file-tag">
          <span>{{ file.name }}</span>
          <button type="button" class="file-tag-remove" @click="emit('file-remove', field, idx)" aria-label="移除">×</button>
        </div>
      </div>
    </div>

    <div class="button-group">
      <button
        v-if="!requestInProgress"
        class="btn btn-primary"
        @click="emit('submit')"
      >
        {{ action?.title || '提交请求' }}
      </button>
      <button
        v-else
        class="btn btn-danger-soft"
        @click="emit('stop-request')"
      >
        停止执行
      </button>
      <button class="btn btn-secondary" @click="emit('fill-example')">填充示例</button>
      <button v-if="lastResult" class="btn btn-secondary" @click="emit('copy-result')">复制结果</button>
      <button v-if="lastResult" class="btn btn-secondary btn-danger-soft" @click="emit('clear-result')">清空结果</button>
    </div>
  </div>
</template>
