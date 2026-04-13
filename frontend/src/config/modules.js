// Migrated from legacy app.js
const REVIEW_DOCUMENT_TYPES = [
    { value: 'patent_certificate', label: '专利证书' },
    { value: 'acceptance_report', label: '验收报告' },
    { value: 'retrieval_report', label: '检索报告' },
    { value: 'award_certificate', label: '奖励证书' },
    { value: 'award_contributor', label: '奖励-主要完成人情况表' },
    { value: 'paper', label: '论文' },
    { value: 'unknown', label: '其他 / 未知' },
];

const REVIEW_CHECK_ITEMS = [
    { value: 'signature', label: '签字检查', description: '检查文档中是否存在签字' },
    { value: 'stamp', label: '盖章检查', description: '检查文档中是否存在印章' },
    { value: 'prerequisite', label: '前置条件', description: '检查是否满足前置材料要求' },
    { value: 'consistency', label: '一致性检查', description: '检查材料信息是否一致' },
    { value: 'completeness', label: '完整性检查', description: '检查文档内容是否完整' },
    { value: 'work_unit_consistency', label: '单位一致性', description: '检查工作单位、完成单位与印章单位是否一致' },
    { value: 'signature_name_consistency', label: '签字人与姓名一致性', description: '检查签字人与表单姓名是否一致' },
];

const MODULES = [
    {
        id: 'review',
        icon: '📝',
        title: '形式审查',
        description: '检查材料是否有签字、盖章，内容是否完整',
        actions: [
            {
                id: 'review_submit',
                title: '开始审查',
                description: '上传材料后自动进行完整性检查',
                api: {
                    method: 'POST',
                    path: '/review',
                    contentType: 'multipart/form-data',
                },
                output: [
                    { name: 'id', label: '审查编号', description: '用于追踪本次审查结果' },
                    { name: 'document_type_raw', label: '文档类型', description: '材料类型（专利证书/检索报告等）' },
                    { name: 'conclusion', label: '总体结论', description: '通过/警告/未通过的汇总结论' },
                    { name: 'results', label: '检查项明细', description: '前置条件/签字/盖章/完整性等逐项结果与证据' },
                    { name: 'suggestions', label: '修改建议', description: '对警告/失败项给出可操作建议' },
                    { name: 'extracted_data', label: '提取信息', description: '页数/签字/印章等可视信息提取结果（已做可读展示）' },
                ],
                fields: [
                    { name: 'file', label: '上传材料', type: 'file', required: true },
                    { name: 'document_type', label: '材料类型', type: 'select', required: true, options: REVIEW_DOCUMENT_TYPES, value: 'patent_certificate' },
                    { name: 'check_items', label: '检查项（可选）', type: 'multi-select', options: REVIEW_CHECK_ITEMS, helpText: '不选则按材料类型自动选择常用检查项' },
                    { name: 'enable_llm_analysis', label: '启用智能分析', type: 'checkbox' },
                    { name: 'papers', label: '论文列表', type: 'textarea', placeholder: '每行一篇论文标题（例如第1篇…第6篇）' },
                    { name: 'metadata', label: '补充信息（可选）', type: 'textarea', placeholder: '例如：{"项目编号":"demo"}；检索报告可直接填 papers 字段' },
                ],
                buildRequest(form, files, helpers) {
                    const fd = new FormData();
                    fd.append('file', files.file);
                    fd.append('document_type', form.document_type);
                    if (Array.isArray(form.check_items) && form.check_items.length) fd.append('check_items', form.check_items.join(','));
                    fd.append('enable_llm_analysis', String(Boolean(form.enable_llm_analysis)));
                    let meta = {};
                    const metaParsed = helpers.parseJsonIfAny(form.metadata);
                    if (metaParsed && typeof metaParsed === 'object' && !Array.isArray(metaParsed)) {
                        meta = metaParsed;
                    }
                    if (helpers.hasText(form.papers)) {
                        const papers = String(form.papers)
                            .split(/\r?\n/)
                            .map((s) => s.trim())
                            .filter(Boolean);
                        if (papers.length) meta.papers = papers;
                    }
                    if (Object.keys(meta).length) {
                        fd.append('metadata', JSON.stringify(meta));
                    } else if (helpers.hasText(form.metadata)) {
                        fd.append('metadata', form.metadata);
                    }
                    return { method: 'POST', url: `${helpers.apiBase()}/review`, body: fd, replayable: false };
                }
            }
        ],
        fillExample(setField) {
            setField('review_submit', 'document_type', 'patent_certificate');
            setField('review_submit', 'check_items', ['signature', 'stamp']);
        }
    },
    {
        id: 'grouping',
        icon: '👥',
        title: '项目分组',
        description: '按学科自动完成项目分组',
        actions: [
            {
                id: 'grouping_full',
                title: '开始分组',
                description: '按学科自动完成项目分组（暂不进行专家匹配）',
                api: {
                    method: 'POST',
                    path: '/grouping/projects',
                    contentType: 'application/json',
                },
                output: [
                    { name: 'id', label: '结果编号', description: '用于追踪本次分组结果' },
                    { name: 'groups', label: '分组结果', description: '按学科 subject_name 展示，展开查看项目 xmmc 列表' },
                    { name: 'statistics', label: '统计信息', description: '分组数/项目数/均衡度等' },
                ],
                fields: [
                    { name: 'category', label: '分组类别（可选）', type: 'text', placeholder: '例如：default（默认）' },
                    { name: 'max_per_group', label: '每组最多项目数', type: 'number', value: '15' },
                ],
                buildRequest(form, _files, helpers) {
                    return {
                        method: 'POST',
                        url: `${helpers.apiBase()}/grouping/projects`,
                        headers: { 'Content-Type': 'application/json' },
                        body: {
                            category: helpers.hasText(form.category) ? form.category : null,
                            max_per_group: helpers.toNumber(form.max_per_group, 15),
                        },
                        replayable: true
                    };
                }
            }
        ],
        fillExample(setField) {
            setField('grouping_full', 'category', 'default');
        }
    },
    {
        id: 'plagiarism',
        icon: '🔍',
        title: '查重检测',
        description: '直接展示已生成的查重报告，不再走上传流程',
        actions: [
            {
                id: 'plagiarism_submit',
                title: '查看查重报告',
                description: '打开系统内的查重报告预览',
                api: {
                    method: 'POST',
                    path: '/plagiarism',
                    contentType: 'multipart/form-data',
                },
                output: [
                    { name: 'id', label: '查重编号', description: '用于追踪本次查重结果' },
                    { name: 'high_similarity', label: '高相似对比', description: '高风险相似对比列表（不展示原始 JSON）' },
                    { name: 'medium_similarity', label: '中相似对比', description: '中风险相似对比列表（带片段预览）' },
                    { name: 'low_similarity', label: '低相似对比', description: '低风险相似对比列表' },
                    { name: 'report_url', label: '可视化报告', description: '生成双栏高亮对照报告（推荐）' },
                ],
                fields: [
                    { name: 'files', label: '上传文件（≥2个）', type: 'file-multi', required: true },
                    { name: 'threshold', label: '查重判定阈值', type: 'number', value: '0.5' },
                    { name: 'threshold_high', label: '高查重阈值', type: 'number', value: '0.8' },
                    { name: 'threshold_medium', label: '中查重阈值', type: 'number', value: '0.5' },
                    { name: 'doc_type', label: '文档类别', type: 'text', value: 'default', placeholder: '' },
                    { name: 'section_config', label: '检测范围配置（可选）', type: 'textarea', placeholder: '' },
                    { name: 'include_report', label: '生成可视化报告（推荐）', type: 'checkbox', checked: true },
                    { name: 'debug', label: '保存调试信息（开发用）', type: 'checkbox' }
                ],
                buildRequest(form, files, helpers) {
                    const fd = new FormData();
                    (files.files || []).forEach((f) => fd.append('files', f));
                    fd.append('threshold', String(helpers.toNumber(form.threshold, 0.5)));
                    fd.append('threshold_high', String(helpers.toNumber(form.threshold_high, 0.8)));
                    fd.append('threshold_medium', String(helpers.toNumber(form.threshold_medium, 0.5)));
                    fd.append('doc_type', helpers.hasText(form.doc_type) ? form.doc_type : 'default');
                    if (helpers.hasText(form.section_config)) fd.append('section_config', form.section_config);
                    fd.append('include_report', String(Boolean(form.include_report)));
                    fd.append('debug', String(Boolean(form.debug)));
                    return { method: 'POST', url: `${helpers.apiBase()}/plagiarism`, body: fd, replayable: false };
                }
            }
        ],
        fillExample(setField) {
            setField('plagiarism_submit', 'section_config', '{"primary":{"start_pattern":"项目立项背景及意义"}}');
        }
    },
    {
        id: 'evaluation',
        icon: '⭐',
        title: '智能评审',
        description: '从多个维度给出评分和分析建议',
        actions: [
            {
                id: 'evaluation_debug',
                title: '加载测试结果',
                description: '从 debug_eval 读取已测试结果并展示',
                api: {
                    method: 'GET',
                    path: '/evaluation/debug-results',
                },
                output: [
                    { name: 'project_id', label: '项目编号', description: '结果所属项目' },
                    { name: 'overall_score', label: '总分', description: '综合评分' },
                    { name: 'grade', label: '等级', description: 'A/B/C 等级' },
                    { name: 'dimension_scores', label: '维度评分', description: '分维度分数与意见' },
                    { name: 'recommendations', label: '修改建议', description: '可操作的优化建议' },
                    { name: 'chat_ready', label: '可问答', description: '是否可基于评审结果进行问答' },
                ],
                fields: [],
                buildRequest(_form, _files, helpers) {
                    return { method: 'GET', url: `${helpers.apiBase()}/evaluation/debug-results`, replayable: false };
                }
            }
        ],
        fillExample() {}
    },
    {
        id: 'sandbox',
        icon: '🧪',
        title: '政策沙盘',
        description: '执行 Step1-5 与 Step3-5 pipeline 调试链路',
        actions: [],
        fillExample() {}
    },
    {
        id: 'perfcheck',
        icon: '✅',
        title: '核验对比',
        description: '对比申报书与任务书，快速找出差异',
        actions: [
            {
                id: 'perfcheck_file',
                title: '上传文件核验',
                description: '上传申报书和任务书进行对比',
                api: {
                    method: 'POST',
                    path: '/perfcheck/compare-async',
                    contentType: 'multipart/form-data',
                    polling: { method: 'GET', path: '/perfcheck/{task_id}' },
                },
                output: [
                    { name: 'task_id', label: '任务编号', description: '用于查询进度与结果' },
                    { name: 'summary', label: '核验结论', description: '总体结论摘要' },
                    { name: 'metrics_risks', label: '核心考核指标对齐', description: '指标逐条对齐核验结果' },
                    { name: 'content_risks', label: '研究内容对比', description: '严格限定研究内容小节进行对比，避免论文/专利/承担项目混入' },
                    { name: 'budget_risks', label: '预算一致性', description: '预算类别/占比/金额差异核验' },
                    { name: 'warnings', label: '提示', description: '解析不足/指标抽取过少等提示信息' },
                ],
                fields: [
                    { name: 'declaration_file', label: '申报书文件', type: 'file', required: true },
                    { name: 'task_file', label: '任务书文件', type: 'file', required: true },
                    { name: 'project_id', label: '项目编号（可选）', type: 'text', placeholder: '' },
                    { name: 'budget_shift_threshold', label: '预算差异阈值', type: 'number', value: '0.10' },
                    { name: 'strict_mode', label: '严格比对模式', type: 'checkbox', checked: true },
                    { name: 'enable_llm_enhancement', label: '启用智能增强分析', type: 'checkbox' },
                    { name: 'enable_table_vision_extraction', label: '启用表格识别（推荐）', type: 'checkbox', checked: true },
                    { name: 'enable_llm_entailment', label: '启用语义一致性校验', type: 'checkbox', checked: true },
                ],
                buildRequest(form, files, helpers) {
                    const fd = new FormData();
                    fd.append('declaration_file', files.declaration_file);
                    fd.append('task_file', files.task_file);
                    if (helpers.hasText(form.project_id)) fd.append('project_id', form.project_id);
                    fd.append('budget_shift_threshold', String(helpers.toNumber(form.budget_shift_threshold, 0.10)));
                    fd.append('strict_mode', String(Boolean(form.strict_mode)));
                    fd.append('enable_llm_enhancement', String(Boolean(form.enable_llm_enhancement)));
                    fd.append('enable_table_vision_extraction', String(Boolean(form.enable_table_vision_extraction)));
                    fd.append('enable_llm_entailment', String(Boolean(form.enable_llm_entailment)));
                    return { method: 'POST', url: `${helpers.apiBase()}/perfcheck/compare-async`, body: fd, replayable: false };
                }
            }
        ],
        fillExample(setField) {
            setField('perfcheck_file', 'project_id', 'demo_001');
        }
    },
    // {
    //     id: 'logicon',
    //     icon: '🧩',
    //     title: '逻辑自洽',
    //     description: '对单份文档做全局逻辑一致性校验（执行期/预算/指标等）',
    //     actions: [
    //         {
    //             id: 'logicon_file',
    //             title: '上传文件核验',
    //             description: '上传申报书或任务书，自动检测跨章节逻辑矛盾',
    //             api: {
    //                 method: 'POST',
    //                 path: '/logicon/check',
    //                 contentType: 'multipart/form-data',
    //             },
    //             output: [
    //                 { name: 'doc_id', label: '文档编号', description: '用于追踪本次核验结果' },
    //                 { name: 'doc_kind', label: '文档类型', description: 'declaration/task/unknown' },
    //                 { name: 'conflicts', label: '冲突列表', description: '执行期跨度/预算求和/指标冲突等' },
    //                 { name: 'warnings', label: '提示', description: '降级或抽取不足提示' },
    //             ],
    //             fields: [
    //                 { name: 'file', label: '上传文档', type: 'file', required: true },
    //                 { name: 'doc_kind', label: '文档类型', type: 'select', required: true, options: [
    //                     { value: 'auto', label: '自动识别' },
    //                     { value: 'declaration', label: '申报书' },
    //                     { value: 'task', label: '任务书' },
    //                 ], value: 'auto' },
    //                 { name: 'enable_llm', label: '启用语义归一（可选）', type: 'checkbox' },
    //                 { name: 'return_graph', label: '返回图谱（开发用）', type: 'checkbox' },
    //                 { name: 'amount_tolerance_wan', label: '金额容忍（万元）', type: 'number', value: '0.01' },
    //                 { name: 'date_tolerance_days', label: '时间容忍（天）', type: 'number', value: '30' },
    //                 { name: 'metric_tolerance_ratio', label: '指标容忍比例', type: 'number', value: '0.01' },
    //             ],
    //             buildRequest(form, files, helpers) {
    //                 const fd = new FormData();
    //                 fd.append('file', files.file);
    //                 fd.append('doc_kind', helpers.hasText(form.doc_kind) ? form.doc_kind : 'auto');
    //                 fd.append('enable_llm', String(Boolean(form.enable_llm)));
    //                 fd.append('return_graph', String(Boolean(form.return_graph)));
    //                 fd.append('amount_tolerance_wan', String(helpers.toNumber(form.amount_tolerance_wan, 0.01)));
    //                 fd.append('date_tolerance_days', String(helpers.toNumber(form.date_tolerance_days, 30)));
    //                 fd.append('metric_tolerance_ratio', String(helpers.toNumber(form.metric_tolerance_ratio, 0.01)));
    //                 return { method: 'POST', url: `${helpers.apiBase()}/logicon/check`, body: fd, replayable: false };
    //             }
    //         }
    //     ],
    //     fillExample(_setField) {}
    // }
];

const HISTORY_MODULE = {
    id: 'history',
    icon: '📜',
    title: '请求历史',
    description: '集中查看所有请求记录和处理状态'
};

export { MODULES, HISTORY_MODULE };
