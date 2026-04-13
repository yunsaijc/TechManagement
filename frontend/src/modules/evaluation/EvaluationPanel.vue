<script setup>
import { computed, onMounted, ref } from 'vue';
import { useEvaluationStore } from '../../stores/evaluation';

const store = useEvaluationStore();
const openDimensionIndex = ref(0);

onMounted(() => {
	if (!store.activeDebugResult) {
		store.initialize();
	}
});

const reportData = computed(() => store.lastResult?.data || null);
const dimensionScores = computed(() => (Array.isArray(reportData.value?.dimension_scores) ? reportData.value.dimension_scores : []));
const recommendations = computed(() => {
	const value = reportData.value?.recommendations;
	if (Array.isArray(value)) return value;
	if (typeof value === 'string' && value.trim()) return [value.trim()];
	return [];
});

const scoreText = computed(() => {
	const n = Number(reportData.value?.overall_score);
	return Number.isFinite(n) ? n.toFixed(2) : '-';
});

const gradeText = computed(() => reportData.value?.grade || '-');

const highlightGroups = computed(() => {
	const h = reportData.value?.highlights;
	if (Array.isArray(h)) {
		return h.length ? [{ label: '亮点', items: h }] : [];
	}
	if (h && typeof h === 'object') {
		return [
			{ label: '研究目标', items: Array.isArray(h.research_goals) ? h.research_goals : [] },
			{ label: '创新点', items: Array.isArray(h.innovations) ? h.innovations : [] },
			{ label: '技术路线', items: Array.isArray(h.technical_route) ? h.technical_route : [] },
		].filter((x) => x.items.length);
	}
	return [];
});

const issueItems = computed(() => {
	const v = reportData.value?.errors;
	if (Array.isArray(v)) return v;
	if (typeof v === 'string' && v.trim()) return [v.trim()];
	return [];
});

const industryFit = computed(() => reportData.value?.industry_fit || null);
const benchmark = computed(() => reportData.value?.benchmark || null);

const evidenceList = computed(() => {
	const items = reportData.value?.evidence;
	return Array.isArray(items) ? items : [];
});

const qnaCards = computed(() => {
	const cards = [];
	if (highlightGroups.value.length) {
		cards.push({
			q: '这个项目的研究目标是什么？',
			a: highlightGroups.value[0].items.slice(0, 2).join('；') || '未提取到明确研究目标。',
		});
	}
	if (dimensionScores.value.length) {
		const top = [...dimensionScores.value].sort((a, b) => Number(b.score || 0) - Number(a.score || 0))[0];
		const low = [...dimensionScores.value].sort((a, b) => Number(a.score || 0) - Number(b.score || 0))[0];
		cards.push({
			q: '这个项目的优势和短板分别是什么？',
			a: `优势维度：${top?.dimension_name || top?.dimension || '-'}；需重点改进：${low?.dimension_name || low?.dimension || '-'}`,
		});
	}
	if (recommendations.value.length) {
		cards.push({ q: '最先要改哪一点？', a: recommendations.value[0] });
	}
	return cards;
});

const defaultQuestions = [
	'这个项目的研究目标是什么？',
	'这个项目的创新点是什么？',
	'申报书里有验证数据吗？',
	'这项工作目前进展到什么程度了？',
	'这项技术有可能落地或量产吗？',
	'这个项目的预期成果和效益是什么？',
];

function onSelectResult(id) {
	store.selectDebugResult(id);
	store.loadSelectedDebugResult();
}

function onResultChange(event) {
	const target = event?.target;
	onSelectResult(target?.value || '');
}

function jumpTo(id) {
	const el = document.getElementById(id);
	if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function askSuggested(question) {
	store.askQuestion(question);
}
</script>

<template>
	<div class="content-scroll eval-page">
		<section class="panel-shell panel-shell-stretch eval-shell">
			<header class="panel hero">
				<div class="hero-top">
					<div>
						<div class="eyebrow">Expert Evaluation Report</div>
						<h1 class="report-title">{{ store.activeDebugResult?.title || reportData?.project_name || '正文评审报告' }}</h1>
						<div class="report-subtitle">项目智能评审报告</div>
					</div>
					<div class="hero-controls">
						<div class="score-card">
							<div class="score-label">综合评分 / 等级</div>
							<div class="score-main">
								<div class="score-value">{{ scoreText }}</div>
								<div class="score-grade">{{ gradeText }}</div>
							</div>
						</div>
						<div class="result-select-row" v-if="store.debugResults.length">
							<label class="result-select-label" for="debug-result-select">切换测试结果</label>
							<select
								id="debug-result-select"
								class="result-select"
								:value="store.selectedDebugResultId"
								@change="onResultChange"
							>
								<option v-for="item in store.debugResults" :key="item.id" :value="item.id">
									{{ item.title }}
								</option>
							</select>
						</div>
					</div>
				</div>

				<div class="hero-lead">面向专家快速阅览的正文评审报告，重点展示结论、问题、证据与可追问能力。</div>

				<nav class="hero-nav">
					<a class="nav-link" href="#report-overview" @click.prevent="jumpTo('report-overview')">评审结论</a>
					<a class="nav-link" href="#report-dimensions" @click.prevent="jumpTo('report-dimensions')">维度评分</a>
					<a class="nav-link" href="#report-chat" @click.prevent="jumpTo('report-chat')">专家聊天</a>
					<a class="nav-link" href="#report-qna" @click.prevent="jumpTo('report-qna')">典型问答</a>
					<a class="nav-link" href="#report-fit" @click.prevent="jumpTo('report-fit')">指南贴合</a>
					<a class="nav-link" href="#report-benchmark" @click.prevent="jumpTo('report-benchmark')">技术摸底</a>
					<a class="nav-link" href="#report-evidence" @click.prevent="jumpTo('report-evidence')">证据链</a>
				</nav>
			</header>

			<div class="content-grid">
				<main class="main-stack">
					<section class="panel" id="report-overview">
						<div class="panel-inner">
							<div class="panel-head">
								<h2>评审结论</h2>
								<div class="panel-note">先给专家连续阅读的结论，再进入逐项核对。</div>
							</div>
							<p class="summary">{{ reportData?.summary || '暂无评审结论' }}</p>

							<div class="facts-grid">
								<div class="mini-card"><div class="label">结构化摘要</div><div class="value">{{ highlightGroups.length ? '已生成' : '未生成' }}</div></div>
								<div class="mini-card"><div class="label">专家问答</div><div class="value">{{ store.questionAnswer ? '已生成' : '未生成' }}</div></div>
								<div class="mini-card"><div class="label">聊天索引</div><div class="value">{{ reportData?.chat_ready ? '已构建' : '未构建' }}</div></div>
								<div class="mini-card"><div class="label">建议条数</div><div class="value">{{ recommendations.length }}</div></div>
								<div class="mini-card"><div class="label">证据总数</div><div class="value">{{ evidenceList.length }}</div></div>
								<div class="mini-card"><div class="label">模型版本</div><div class="value">{{ reportData?.model_version || '-' }}</div></div>
							</div>

							<div class="highlight-grid" v-if="highlightGroups.length">
								<div class="highlight-card" v-for="group in highlightGroups" :key="group.label">
									<div class="highlight-label">{{ group.label }}</div>
									<ol class="list">
										<li v-for="item in group.items" :key="item">{{ item }}</li>
									</ol>
								</div>
							</div>
						</div>
					</section>

					<section class="panel" id="report-dimensions">
						<div class="panel-inner">
							<div class="panel-head">
								<h2>维度评分</h2>
								<div class="panel-note">默认展开最需要关注的一项，其余按需展开。</div>
							</div>

							<div class="score-list" v-if="dimensionScores.length">
								<div class="score-accordion">
									<div
										class="score-item"
										v-for="(dimension, idx) in dimensionScores"
										:key="dimension.dimension || dimension.dimension_name"
										:class="{ 'is-open': openDimensionIndex === idx }"
									>
										<button class="score-trigger" type="button" @click="openDimensionIndex = openDimensionIndex === idx ? -1 : idx">
											<div class="score-trigger-main">
												<div class="score-card-title">{{ dimension.dimension_name || dimension.dimension }}</div>
												<div class="score-trigger-sub">{{ dimension.opinion || '暂无评语' }}</div>
											</div>
											<div class="score-trigger-meta">
												<div class="score-pill">得分 {{ Number(dimension.score || 0).toFixed(2) }}</div>
												<div class="score-chevron">{{ openDimensionIndex === idx ? '收起详情' : '展开详情' }}</div>
											</div>
										</button>

										<div class="score-body">
											<div class="score-detail-card">
												<div class="score-detail-label">补充信息</div>
												<div class="tag-row" v-if="Array.isArray(dimension.highlights) && dimension.highlights.length">
													<span class="tag" v-for="item in dimension.highlights" :key="`h-${item}`">亮点：{{ item }}</span>
												</div>
												<div class="tag-row" v-if="Array.isArray(dimension.issues) && dimension.issues.length">
													<span class="tag" v-for="item in dimension.issues" :key="`i-${item}`">问题：{{ item }}</span>
												</div>
												<div class="empty" v-if="(!Array.isArray(dimension.highlights) || !dimension.highlights.length) && (!Array.isArray(dimension.issues) || !dimension.issues.length)">暂无补充信息</div>
											</div>
										</div>
									</div>
								</div>
							</div>

							<div class="empty" v-else>暂无维度评分</div>
						</div>
					</section>
				</main>

				<aside class="side-stack">
					<section class="panel" id="report-chat">
						<div class="panel-inner">
							<h2>专家即时问答</h2>
							<div class="chat-shell">
								<div class="chat-status" v-if="!reportData?.chat_ready">
									当前评审未构建聊天索引，无法发起实时问答。请重新评审并启用 enable_chat_index。
								</div>

								<div class="chat-suggestions">
									<button class="chat-suggestion" type="button" v-for="q in defaultQuestions" :key="q" @click="askSuggested(q)" :disabled="store.requestInProgress">
										{{ q }}
									</button>
								</div>

								<form class="chat-form" @submit.prevent="store.askQuestion()">
									<textarea
										v-model="store.questionDraft"
										class="chat-textarea"
										placeholder="输入专家问题，例如：这项技术有可能量产吗？"
										:disabled="store.requestInProgress || !reportData?.chat_ready"
									/>
									<div class="chat-actions">
										<div class="chat-status">{{ store.requestInProgress ? '正在生成回答...' : '等待提问' }}</div>
										<button class="chat-submit" type="submit" :disabled="store.requestInProgress || !reportData?.chat_ready">发送问题</button>
									</div>
								</form>

								<div class="qa-card" v-if="store.questionAnswer">
									<div class="qa-question">实时回答</div>
									<div class="qa-answer">{{ store.questionAnswer }}</div>
									<details class="fold" v-if="store.questionCitations.length">
										<summary>查看页码证据</summary>
										<div class="fold-body">
											<div class="citation-list">
												<div class="citation" v-for="(citation, idx) in store.questionCitations" :key="idx">
													<div>页码：第 {{ citation.page || '-' }} 页</div>
													<div>文件：{{ citation.file || '-' }}</div>
													<div>片段：{{ citation.snippet || '-' }}</div>
												</div>
											</div>
										</div>
									</details>
								</div>
							</div>
						</div>
					</section>

					<section class="panel" id="report-qna">
						<div class="panel-inner">
							<div class="panel-head">
								<h2>专家关注问答</h2>
								<div class="panel-note">展示典型问题，证据默认折叠。</div>
							</div>
							<div class="qa-list" v-if="qnaCards.length">
								<div class="qa-card" v-for="qa in qnaCards" :key="qa.q">
									<div class="qa-question">{{ qa.q }}</div>
									<div class="qa-answer">{{ qa.a }}</div>
								</div>
							</div>
							<div class="empty" v-else>暂无典型问答</div>
						</div>
					</section>

					<section class="panel" id="report-fit">
						<div class="panel-inner">
							<h2>指南贴合</h2>
							<div v-if="industryFit" class="support-list">
								<div class="support-item">贴合得分：{{ Number(industryFit.fit_score || 0).toFixed(2) }}</div>
								<div class="support-item" v-if="Array.isArray(industryFit.matched) && industryFit.matched.length">已匹配：{{ industryFit.matched.join('；') }}</div>
								<div class="support-item" v-if="Array.isArray(industryFit.gaps) && industryFit.gaps.length">缺口：{{ industryFit.gaps.join('；') }}</div>
								<div class="support-item" v-if="Array.isArray(industryFit.suggestions) && industryFit.suggestions.length">建议：{{ industryFit.suggestions.join('；') }}</div>
							</div>
							<div class="empty" v-else>未启用或暂无结果</div>
						</div>
					</section>

					<section class="panel" id="report-benchmark">
						<div class="panel-inner">
							<h2>技术摸底</h2>
							<div v-if="benchmark" class="support-list">
								<div class="support-item">新颖性：{{ benchmark.novelty_level || '-' }}</div>
								<div class="support-item" v-if="benchmark.literature_position">文献定位：{{ benchmark.literature_position }}</div>
								<div class="support-item" v-if="benchmark.patent_overlap">专利重叠：{{ benchmark.patent_overlap }}</div>
								<div class="support-item" v-if="benchmark.conclusion">结论：{{ benchmark.conclusion }}</div>
							</div>
							<div class="empty" v-else>未启用或暂无结果</div>
						</div>
					</section>

					<section class="panel" id="report-evidence">
						<div class="panel-inner">
							<div class="panel-head">
								<h2>证据链</h2>
								<div class="panel-note">需要核对原文时再展开。</div>
							</div>
							<div class="report-block" v-if="evidenceList.length">
								<details class="fold" v-for="(ev, idx) in evidenceList" :key="idx">
									<summary>{{ ev.source || 'document' }} · 第 {{ ev.page || '-' }} 页</summary>
									<div class="fold-body">
										<div><strong>文件：</strong>{{ ev.file || '-' }}</div>
										<div><strong>片段：</strong>{{ ev.snippet || '-' }}</div>
									</div>
								</details>
							</div>
							<div class="empty" v-else>暂无证据链</div>
						</div>
					</section>
				</aside>
			</div>
		</section>
	</div>
</template>

<style scoped>
.eval-page {
	--bg: #f3f5f7;
	--panel: #ffffff;
	--panel-soft: #f7f9fb;
	--ink: #1b2430;
	--muted: #66758a;
	--line: #d7dfe8;
	--brand: #1d3c61;
	--brand-soft: #e8eff6;
	--shadow: 0 8px 24px rgba(18, 31, 53, 0.05);
	background: var(--bg);
}

.eval-shell {
	display: grid;
	gap: 20px;
}

.panel {
	background: var(--panel);
	border: 1px solid var(--line);
	border-radius: 18px;
	box-shadow: var(--shadow);
	scroll-margin-top: 16px;
}

.hero {
	padding: 18px 22px 16px;
	background: linear-gradient(180deg, #fbfcfd 0%, #f4f7fa 100%);
}

.hero-top {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	gap: 20px;
	flex-wrap: wrap;
}

.hero-controls {
	display: flex;
	align-items: flex-start;
	justify-content: flex-end;
	gap: 12px;
	flex-wrap: wrap;
	min-width: 420px;
	margin-left: auto;
}

.eyebrow {
	color: var(--brand);
	font-size: 12px;
	font-weight: 700;
	letter-spacing: 0.08em;
	text-transform: uppercase;
	margin-bottom: 8px;
}

.report-title {
	margin: 0;
	font-size: 28px;
	line-height: 1.35;
	font-weight: 700;
	color: var(--ink);
}

.report-subtitle {
	margin-top: 8px;
	color: var(--muted);
	font-size: 14px;
}

.score-card {
	min-width: 220px;
	padding: 18px 20px;
	background: var(--panel);
	border: 1px solid var(--line);
	border-radius: 16px;
	flex: 0 0 220px;
}

.score-label {
	color: var(--muted);
	font-size: 12px;
	margin-bottom: 8px;
}

.score-main {
	display: flex;
	align-items: baseline;
	gap: 10px;
}

.score-value {
	font-size: 44px;
	line-height: 1;
	font-weight: 800;
}

.score-grade {
	font-size: 20px;
	font-weight: 700;
	color: var(--brand);
}

.hero-lead {
	margin-top: 12px;
	color: var(--muted);
	font-size: 14px;
	line-height: 1.8;
}


.result-select-row {
	margin-top: 0;
	display: grid;
	gap: 8px;
	max-width: 320px;
	flex: 1 1 260px;
}

.result-select-label {
	color: var(--muted);
	font-size: 12px;
	font-weight: 700;
	letter-spacing: 0.04em;
	text-transform: uppercase;
}

.result-select {
	width: 100%;
	border: 1px solid var(--line);
	background: var(--panel);
	color: var(--ink);
	border-radius: 14px;
	padding: 12px 14px;
	font-size: 14px;
	font-weight: 600;
	outline: none;
	box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
	appearance: none;
	background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%);
	background-position: calc(100% - 18px) calc(50% - 3px), calc(100% - 12px) calc(50% - 3px);
	background-size: 6px 6px, 6px 6px;
	background-repeat: no-repeat;
}

.result-select:focus {
	border-color: var(--brand);
	box-shadow: 0 0 0 3px rgba(29, 60, 97, 0.12);
}

.hero-nav {
	display: flex;
	gap: 10px;
	flex-wrap: wrap;
	margin-top: 12px;
}

.nav-link {
	display: inline-flex;
	align-items: center;
	padding: 9px 14px;
	border: 1px solid var(--line);
	border-radius: 999px;
	background: var(--panel);
	font-size: 13px;
	font-weight: 600;
	text-decoration: none;
	color: var(--ink);
}

.content-grid {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 360px;
	gap: 20px;
}

.main-stack,
.side-stack {
	display: grid;
	gap: 18px;
	align-content: start;
}

.panel-inner {
	padding: 22px;
}

.panel-head {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	gap: 12px;
	margin-bottom: 14px;
}

.panel h2 {
	margin: 0;
	font-size: 20px;
}

.panel-note {
	color: var(--muted);
	font-size: 13px;
}

.summary {
	margin: 0;
	font-size: 15px;
	line-height: 1.9;
}

.facts-grid {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 12px;
	margin-top: 18px;
}

.mini-card {
	padding: 14px;
	background: var(--panel-soft);
	border: 1px solid var(--line);
	border-radius: 14px;
}

.mini-card .label {
	color: var(--muted);
	font-size: 12px;
	margin-bottom: 6px;
}

.mini-card .value {
	font-size: 18px;
	font-weight: 700;
}

.highlight-grid {
	display: grid;
	gap: 12px;
	margin-top: 18px;
}

.highlight-card {
	padding: 16px;
	background: var(--panel-soft);
	border: 1px solid var(--line);
	border-radius: 14px;
}

.highlight-label {
	margin-bottom: 8px;
	color: var(--brand);
	font-size: 13px;
	font-weight: 700;
}

.list {
	margin: 0;
	padding-left: 20px;
	line-height: 1.8;
}

.score-list {
	display: grid;
	gap: 14px;
}

.score-accordion {
	border: 1px solid var(--line);
	border-radius: 16px;
	background: var(--panel);
	overflow: hidden;
}

.score-item + .score-item {
	border-top: 1px solid var(--line);
}

.score-trigger {
	width: 100%;
	border: 0;
	background: transparent;
	color: inherit;
	padding: 16px 18px;
	text-align: left;
	cursor: pointer;
	display: flex;
	justify-content: space-between;
	gap: 16px;
	transition: background 0.2s ease;
}

.score-trigger:hover {
	background: #f7f9fc;
}

.score-trigger-main {
	flex: 1;
	min-width: 0;
	display: grid;
	gap: 6px;
}

.score-trigger-sub {
	color: var(--muted);
	font-size: 13px;
	line-height: 1.7;
	overflow: hidden;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
}

.score-trigger-meta {
	flex: 0 0 132px;
	display: grid;
	justify-items: end;
	gap: 8px;
}

.score-pill {
	padding: 6px 10px;
	border-radius: 999px;
	background: var(--brand-soft);
	color: var(--brand);
	font-size: 20px;
	font-weight: 700;
	white-space: nowrap;
}

.score-chevron {
	color: var(--muted);
	font-size: 12px;
	white-space: nowrap;
}

.score-body {
	display: none;
	padding: 0 18px 18px;
}

.score-item.is-open .score-body {
	display: block;
}

.score-detail-card {
	padding: 14px 16px 16px;
	border: 1px solid var(--line);
	border-radius: 14px;
	background: var(--panel-soft);
}

.score-detail-label {
	margin-bottom: 10px;
	color: var(--brand);
	font-size: 13px;
	font-weight: 700;
}

.score-card-title {
	font-size: 17px;
	font-weight: 700;
}

.tag-row {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
	margin-top: 12px;
}

.tag {
	padding: 5px 10px;
	border-radius: 999px;
	background: var(--brand-soft);
	color: var(--brand);
	font-size: 12px;
}

.subtle {
	color: var(--muted);
	font-size: 14px;
	line-height: 1.8;
}

.qa-list,
.support-list,
.report-block,
.citation-list {
	display: grid;
	gap: 12px;
}

.qa-card,
.support-item {
	padding: 16px;
	border: 1px solid var(--line);
	border-radius: 14px;
	background: var(--panel-soft);
}

.qa-question {
	font-size: 16px;
	font-weight: 700;
	margin-bottom: 10px;
}

.qa-answer {
	font-size: 14px;
	line-height: 1.8;
}

.citation {
	padding: 10px 12px;
	border-radius: 12px;
	background: #f5f8fb;
	border: 1px solid var(--line);
	font-size: 13px;
}

.fold {
	border: 1px solid var(--line);
	border-radius: 14px;
	background: var(--panel);
	overflow: hidden;
}

.fold summary {
	cursor: pointer;
	font-weight: 700;
	padding: 14px 16px;
	list-style: none;
	background: var(--panel-soft);
}

.fold-body {
	padding: 14px 16px 16px;
	display: grid;
	gap: 10px;
}

.empty {
	color: var(--muted);
	font-size: 14px;
}

.chat-shell {
	display: grid;
	gap: 12px;
}

.chat-form {
	display: grid;
	gap: 10px;
}

.chat-textarea {
	min-height: 96px;
	resize: vertical;
	width: 100%;
	border: 1px solid var(--line);
	border-radius: 12px;
	padding: 10px;
	font-size: 14px;
}

.chat-actions {
	display: flex;
	justify-content: space-between;
	align-items: center;
	gap: 12px;
}

.chat-suggestions {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
}

.chat-suggestion,
.chat-submit {
	border: 1px solid var(--line);
	border-radius: 10px;
	background: var(--panel);
	color: var(--ink);
	padding: 8px 12px;
	font-size: 12px;
	cursor: pointer;
}

.chat-submit {
	background: var(--brand);
	border-color: var(--brand);
	color: #fff;
	font-weight: 700;
}

.chat-status {
	color: var(--muted);
	font-size: 13px;
}

@media (max-width: 1320px) {
	.content-grid {
		grid-template-columns: 1fr;
	}
}

@media (max-width: 1120px) {
	.facts-grid {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}

@media (max-width: 760px) {
	.hero,
	.panel-inner {
		padding: 16px;
	}
	.hero-controls {
		display: grid;
		min-width: 0;
		width: 100%;
	}
	.score-card,
	.result-select-row {
		flex: none;
		max-width: none;
		width: 100%;
	}
	.facts-grid {
		grid-template-columns: 1fr;
	}
	.report-title {
		font-size: 22px;
	}
	.score-trigger {
		flex-direction: column;
		align-items: flex-start;
		gap: 10px;
	}
	.score-trigger-meta {
		flex: 0 0 auto;
		width: 100%;
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
}
</style>
