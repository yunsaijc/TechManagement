# 🚀 智能系统前端应用

> 基于 Vue 3 + Vite + Vue Router + Pinia 的标准工程化前端

## ⚡ 快速开始

### 一键启动（全部）
```bash
# 从项目根目录
bash start_all.sh
```

### 分别启动

**后端**（需要 FastAPI）
```bash
cd /home/tdkx/ljh/Tech
uvicorn src.app.main:app --port 8005 --reload
```

**前端（开发模式）**
```bash
cd /home/tdkx/ljh/Tech/frontend
npm install
npm run dev
```

**前端（生产构建）**
```bash
cd /home/tdkx/ljh/Tech/frontend
npm run build
```

### 打开应用
`http://localhost:8005/frontend`

## 📚 文档导航

| 文档 | 内容 | 适合 |
|------|------|------|
| **README.md** (本文件) | 快速入门 | 所有用户 |
| **[FRONTEND_QUICK_REF.md](../FRONTEND_QUICK_REF.md)** | 快速参考 | 开发者 |
| **[FRONTEND_SETUP.md](../FRONTEND_SETUP.md)** | 详细指南 | 架构师/运维 |
| **[FRONTEND_DELIVERY.md](../FRONTEND_DELIVERY.md)** | 交付总结 | 项目经理 |

## 🎯 五大功能模块

### 📝 材料完整性审查 (review)
上传签字、盖章、材料完整度等形式要素

**操作：**
- 发起审查
- 查询审查结果
- 查看支持的文档类型

### 👥 项目分组与专家匹配 (grouping)
智能分组 + 专家分配

**操作：**
- 项目分组
- 专家匹配
- 完整流程

### 🔍 相似内容检测 (plagiarism)
对比多份文档，识别重复改写段落

**操作：**
- 开始检测
- 查看文件类型
- 查看检测范围模板

### ⭐ 正文智能分析 (evaluation)
多维度评审，输出评分建议

**操作：**
- 按项目分析
- 上传文件分析
- 基于结果提问
- 查看评审维度

### ✅ 申报与任务对照核验 (perfcheck)
识别申报书与任务书的偏差

**操作：**
- 文件核验
- 文本核验
- 查询任务状态
- 获取核验报告

## 🏗️ 项目结构

```
frontend/
├── package.json
├── vite.config.js
├── index.html
├── src/
│   ├── main.js
│   ├── App.vue
│   ├── router/
│   │   └── index.js
│   ├── stores/
│   │   └── workbench.js
│   ├── views/
│   │   ├── WorkbenchView.vue
│   │   └── HistoryView.vue
│   ├── components/
│   │   ├── AppHeader.vue
│   │   ├── ModuleNav.vue
│   │   ├── ActionTabs.vue
│   │   ├── DynamicForm.vue
│   │   ├── ResultDisplay.vue
│   │   ├── HistoryPanel.vue
│   │   ├── ToastNotice.vue
│   │   └── RequestHud.vue
│   └── config/
│       └── modules.js
└── styles/
    └── professional.css
```

## 🎨 主要特性

- ✅ **标准工程化** - Vite 构建与热更新
- ✅ **路由拆分** - 工作台/历史页面独立路由
- ✅ **集中状态管理** - Pinia 管理请求与展示状态
- ✅ **响应式** - 适配桌面/平板/手机
- ✅ **组件化** - 多个 `.vue` 组件拆分
- ✅ **实时同步** - 历史记录自动保存
- ✅ **现代 API** - Fetch、localStorage、FormData
- ✅ **错误处理** - 完善的异常捕获

## 💡 使用场景

### 场景 1：单个操作
1. 选择模块
2. 选择操作
3. 填表单
4. 提交查看结果

### 场景 2：批量操作
1. 进行多个操作
2. 查看历史记录
3. 重试失败的请求
4. 导出结果

### 场景 3：对比分析
1. 上传多个文件
2. 查看对比结果
3. 复制重点内容
4. 下载完整报告

## 🔧 配置修改

### 改变 API 服务器地址

编辑 `components/ModuleContent.js`：

```javascript
apiBase() {
    return 'http://your-api-server/api/v1';
}
```

### 修改请求超时时间

编辑 `components/ModuleContent.js` 的 `fetchWithTimeout` 参数（毫秒）：

```javascript
const result = await this.fetchWithTimeout(request.url, options, 120000); // 120秒
```

### 调整历史记录数量

编辑 `components/ModuleContent.js` 的 `recordHistory` 方法：

```javascript
this.requestHistory = this.requestHistory.slice(0, 50); // 保留 50 条
```

## 📱 浏览器支持

| 浏览器 | 版本 | 支持 |
|--------|------|------|
| Chrome | 90+ | ✅ |
| Firefox | 88+ | ✅ |
| Safari | 14+ | ✅ |
| Edge | 90+ | ✅ |
| IE 11 | 11 | ❌ (不支持 ES6 Modules) |

## 🐛 常见问题

### Q: 无法连接后端
**A:** 确保后端已启动在 localhost:8001，检查浏览器控制台 CORS 错误

### Q: 表单不显示
**A:** 按 F12 检查浏览器控制台错误，确认模块定义完整

### Q: 历史记录消失
**A:** localStorage 被清理或达到浏览器存储限制（通常 5-10MB）

### Q: 文件上传失败
**A:** 检查文件格式、大小是否符合要求，查看后端限制

### Q: 页面加载缓慢
**A:** 检查网络连接、浏览器缓存是否禁用、后端响应速度

## 🔍 调试技巧

### 打开开发者工具
```
Windows/Linux: F12
Mac: Cmd + Option + I
```

### 查看网络请求
Devtools → Network → 选择 XHR → 查看请求/响应

### 检查本地存储
Devtools → Application → localStorage → 查看每个模块的历史

### 清除所有缓存
```javascript
// 在浏览器控制台运行
localStorage.clear()
```

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 页面加载时间 | < 2秒 |
| API 请求超时 | 60秒 |
| 历史记录数量 | 20条/模块 |
| 本地存储容量 | ~5-10MB |
| 支持并发请求 | 无限制 |

## 🚀 部署建议

### 开发环境
```bash
python3 -m http.server 8000
```

### 生产环境 (Nginx)
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    
    root /path/to/frontend;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api/ {
        proxy_pass http://backend-server:8001;
        proxy_set_header Host $host;
    }
}
```

### Docker 部署
```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY . .
RUN npm install -g http-server
EXPOSE 8000
CMD ["http-server", "."]
```

## 📈 扩展指南

### 添加新操作
编辑对应模块文件（如 `modules/review.js`），在 `actions` 数组中添加新对象

### 添加新字段类型
1. 编辑 `components/ActionForm.js` 模板部分
2. 添加新的 `v-else-if` 分支
3. 处理字段值的初始化和提交

### 添加新模块
1. 在 `modules/` 下创建 `newmodule.js`
2. 在 `modules/index.js` 中导入并添加到数组
3. 刷新即可看到新模块

## 🎓 学习资源

- [Vue 3 官方文档](https://v3.vuejs.org/)
- [Fetch API](https://mdn.io/fetch)
- [FormData API](https://mdn.io/formdata)
- [localStorage](https://mdn.io/localstorage)

## 📝 许可证

[待定]

## 👥 团队

**开发：** Tech Team  
**文档：** Tech Team  
**维护：** Tech Team  

---

## ❓ 获取帮助

### 文档
- 快速参考：[FRONTEND_QUICK_REF.md](../FRONTEND_QUICK_REF.md)
- 详细指南：[FRONTEND_SETUP.md](../FRONTEND_SETUP.md)
- 交付总结：[FRONTEND_DELIVERY.md](../FRONTEND_DELIVERY.md)

### 反馈
- Bug 报告：[GitHub Issues]
- 功能建议：[GitHub Discussions]

---

**版本：** 1.0.0  
**最后更新：** 2026-03-26  
**状态：** ✅ 生产就绪
