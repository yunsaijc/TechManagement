# 图片查重库设计（Image Corpus）

## 1. 目标

图片查重采用与正文查重一致的思路：

1. 先离线建库（可断点续跑）
2. 在线请求只做“primary 查询 -> corpus 召回 -> 精校验”
3. 不做在线全量两两比

这条链路对应行业常见的 `fast retrieve + expensive verify`。

## 2. 技术基线（Solid References）

### 2.1 精确去重（Exact Match）

- `SHA-256` 作为精确重复判定（同图或标准化后同图）
- 参考：NIST FIPS 180-4（Secure Hash Standard）
  - https://csrc.nist.gov/pubs/fips/180-4/upd1/final

### 2.2 感知哈希粗召回（Perceptual Hash）

- 主哈希：`PDQ`（256-bit）
- 兼容兜底：`pHash`
- 参考：
  - Meta ThreatExchange PDQ：
    - https://github.com/facebook/ThreatExchange/tree/main/pdq
  - OpenCV `img_hash`（含 pHash）：
    - https://docs.opencv.org/4.x/d4/d93/group__img__hash.html

### 2.3 向量检索与重排（后续增强）

- 推荐：SSCD（copy detection 专用描述子）+ Faiss
- 参考：
  - SSCD 论文（CVPR 2022）：
    - https://openaccess.thecvf.com/content/CVPR2022/papers/Pizzi_A_Self-Supervised_Descriptor_for_Image_Copy_Detection_CVPR_2022_paper.pdf
  - SSCD 官方实现：
    - https://github.com/facebookresearch/sscd-copy-detection
  - Faiss 文档：
    - https://faiss.ai/
  - Faiss 选型指南：
    - https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index

### 2.4 几何一致性验证（False Positive 抑制）

- 局部特征匹配 + RANSAC Homography
- 参考：OpenCV Feature Matching + Homography 教程
  - https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html

## 3. 架构原则

1. 与正文查重完全隔离：
- 代码目录：`src/services/plagiarism_image/`
- 数据目录：`data/plagiarism_image/`
- 调试目录：`debug_plagiarism/image/`

2. 在线接口不扫描远端全库：
- 在线只读已构建好的图片索引
- 索引构建通过离线 batch 接口执行

3. 可恢复性：
- 每次构建只处理小批次
- checkpoint 记录游标
- 失败文档单独记录，不阻断整体

4. 建库任务化：
- API 负责提交 job
- 后台单 worker 串行执行
- 状态与结果写入 `build_jobs`

## 4. 数据模型（V2）

### 4.1 Manifest

`data/plagiarism_image/index/image_manifest.json`

每条文档记录：
- `doc_id`
- `doc_path`
- `file_size`
- `file_mtime`
- `action` (`new` / `update` / `unchanged`)

### 4.2 Primary Index DB

`data/plagiarism_image/index/image_features.sqlite3`

主表：
- `documents`
- `images`
- `image_features`
- `manifest_docs`
- `build_state`

说明：
- `documents/images` 是主索引元数据
- `image_features` 存压缩后的 ORB 描述子 + 关键点
- `manifest_docs/build_state` 管理扫描结果与断点续跑
- 在线阶段直接读 SQLite，不再依赖大 JSON 主文件

## 5. 流程

### 5.1 离线建库

1. 扫描文档目录，生成 manifest
2. `build_batch(limit)` 解析 docx/pdf 抽图
3. 生成 hash + ORB 特征，并增量写入 SQLite
4. 更新 checkpoint

安全保护：
- 大语料（>=3000 文档）下，`limit < 1000` 会被拒绝（HTTP 400）
- 目的：避免小批次循环触发高频全量扫描/大文件重写导致磁盘 IO 打满
- build 任务有全局锁（同一时刻仅允许 1 个 build-batch 执行）

### 5.2 在线查重（by-guide-codes）

1. 查询项目元数据（`zndm IN (...) and isSubmit='1'`）
2. 读取 primary 文档并抽图
3. 每张 primary 图在 corpus 中召回候选（索引检索，不线性扫）：
- exact：`sha256_norm`
- near-dup：`pHash BK-tree` + `Hamming <= 阈值`
4. 对候选做几何验证（ORB + RANSAC，按 query 图并行）
5. `exact_sha256_norm` 命中时该 query 图直接早停
6. 生成按 primary 项目聚合的结果 + HTML 报告

## 6. 默认阈值（V1）

- `hash_hamming_max = 18`
- `high_score = 0.82`
- `medium_score = 0.62`
- `min_inliers_high = 10`

说明：这些是可运行基线，后续需基于真实数据校准。

## 7. API 约束

当前图片查重主入口是：

- `POST /api/v1/plagiarism/image/by-guide-codes`

上传入口不作为生产主路径（避免“批内两两比”偏离目标流程）。

## 8. 后续增强路线

1. 在 V1 哈希库稳定后，引入 `SSCD + Faiss` 做二阶段重排
2. 增加 `recall@k / precision@k` 离线评估
3. 增加按年份/指南的分片索引与并行检索
