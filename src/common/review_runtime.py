"""Review 子服务运行时参数（统一配置）"""


class ReviewRuntime:
    """集中管理 Review 运行参数，避免依赖环境变量手动配置"""

    # 批次级并发：同一批次并行处理项目数
    BATCH_PROJECT_CONCURRENCY = 3

    # 项目内并发：同一项目并行分类附件数
    ATTACHMENT_CLASSIFY_CONCURRENCY = 6

    # 项目内并发：同一项目并行跑附件细粒度审查数
    ATTACHMENT_REVIEW_CONCURRENCY = 2

    # 附件分类阈值
    ATTACHMENT_CLASSIFY_CONFIDENCE = 0.70

    # PDF 预览构建参数
    ATTACHMENT_PDF_RENDER_ZOOM = 1.4
    ATTACHMENT_PDF_TEXT_PAGES = 1
    ATTACHMENT_PREVIEW_TEXT_LIMIT = 1200

    # 发送给 LLM 的图像压缩参数
    ATTACHMENT_LLM_MAX_DIM = 1200
    ATTACHMENT_LLM_JPEG_QUALITY = 70
