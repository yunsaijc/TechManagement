<script setup>
import { onMounted, ref } from 'vue';

const reportRoot = ref(null);

const navItems = [
  {
    id: 'g001',
    title: '#1',
    text: '在我国大力倡导智能制造引领工业制造的时代背景下，传统的以劳动密集手工模式制造过程，已成为严重制约产品制造效率和质量的瓶颈...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g002',
    title: '#2',
    text: '(1) 提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔耦合动 力学建模方法，结构化模型仍采用集中质...',
    meta: '相似度: 1.00 | 主来源: 74107418021a49ca911e9b285c56e431.docx',
  },
  {
    id: 'g003',
    title: '#3',
    extra: '2个来源',
    text: '一、项目所属领域发展现状及趋势 近年来，机器人技术在工业自动化领域得到了广泛应用，尤其是高性能工业机器人。随着机器人应用...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g004',
    title: '#4',
    text: '传统的柔性关节模型仅对驱动关节的扭转弹性进行建模，忽略了基座、轴承、臂杆结构柔性，末端工具变形对系统动力学特性的影响，已...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g005',
    title: '#5',
    extra: '2个来源',
    text: '考虑到影响机器人定位精度的误差因素复杂且相互耦合，必须研究不受机器人误差生成机理及作用规律限制的非参数建模方法，以充分表...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g006',
    title: '#6',
    text: '本课题首先基于自下而上的方式进行柔性关节模型的扩展，技术路线图参考附件。 在经典刚性多体动力学模型基础上，根据减速器的分...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g007',
    title: '#7',
    text: '影响机器人定位精度的因素多种多样，臂杆长度和装配误差、初始对准偏差及反复校准引入的零位偏移误差等几何相关误差是工业机器人...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g008',
    title: '#8',
    text: '设计基于期望运动伺服约束的模型动态逆前馈控制，结合干扰观测的自适应积分滑模反馈控制方法，以实现系统的高精度轨迹跟踪控制。...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g009',
    title: '#9',
    text: '(1)提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔 耦合动力学建模方法，结构化模型仍采用集中质量...',
    meta: '相似度: 1.00 | 主来源: 68738c4c63f7487e933245b25a6d1b69.docx',
  },
  {
    id: 'g010',
    title: '#10',
    text: '论文 在全局动力学建模、运动学误差标定等前沿领域预期在国际、国内核心刊物发表论 文 3 篇，其中被 SCI 检索 2 篇...',
    meta: '相似度: 0.92 | 主来源: 74107418021a49ca911e9b285c56e431.docx',
  },
];

const primaryHtml = `
<table class="docx-table"><tr><td colspan="13"><p class="docx-paragraph"><strong>项目立项背景及意义</strong></p></td></tr><tr><td colspan="13"><p class="docx-paragraph"><a id="lxbj"></a><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">在我国大力倡导智能制造引领工业制造的时代背景下，传统的以劳动密集手工模式制造过程，已成为严重制约产品制造效率和质量的瓶颈，发展和应用以</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">工业机器人</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">为代表的自动化设备平台，对于生产模式转型升级和装备先进制造能力提升</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">具有十分重要的战略意义和巨大价值</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">。随着现代工业制造的智能化、网络化发展，制造产品的尺寸大、载荷重、结构复杂，这对</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">现代工业机器人</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">的性能提出了更高的要求：为适应工业机器人多臂协同、人机协作等高度自主、柔性化、自动化生产的发展，必须着力提升工业机器人本体的高工作节拍(</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">高速</span></strong>、<strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">高带宽</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">)、</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">重载</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">(载荷/自重比大)极限工况条件下的</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">高精度</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">控制性能。如ABB公司的IRB7600机器人是典型代表之一，其有效载荷范围150-500kg，最大承重能力650kg，关节运动角速度最高可达190°/s，定位精度0.55-1.2mm。总体上，与国外先进技术有很大差距，相关研究瓶颈还亟待突破，作为新的经济增长点，</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">打破国外技术垄断</span></strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">，突破制约高速重载、高加速等极限工况下工业机器人运动控制精度的技术瓶颈，并</span><strong><span class="hit strong" data-match-id="g001" data-side="primary" data-match-type="exact" data-tone="strong">推动其在行业中的广泛应用</span></strong>。</p></td></tr><tr><td colspan="13"><p class="docx-paragraph"><strong>项目简介</strong></p></td></tr><tr><td colspan="13"><p class="docx-paragraph"><a id="xmjj"></a><span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">(1)</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔耦合动</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">范围（0-100Hz）内全面考虑了系统的复杂刚柔耦合影响，为高性能工业机器人控制系统设计奠</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">定了精准、合理的模型基础。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">(2)</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">提出一种基于切比雪夫基函数的机器人广义运动学误差建模方法，对各类几何和关节</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">依赖误差进行全面表征，其不受机器人误差生成机理及作用规律的限制，且能最大限度地避免陷</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">入局部最优或过拟合，基于最佳一致逼近估计的误差补偿算法有望对末端执行器位姿进行准确伺</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">服修正。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">(3)</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">针对高性能工业机器人这类刚柔耦合、复杂非线性系统，提出一种基于期望运动伺服约束的模型动态逆前馈控制结合自适应积分型滑模反馈控制的设计方法，以保证机器人系统的鲁</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">棒稳定和高动态响应，有望实现对全局刚柔耦合动力学模型的精准跟随和机器人系统的高精度控</span> <span class="hit strong" data-match-id="g002" data-side="primary" data-match-type="exact" data-tone="strong">制。</span></p></td></tr></table><p class="docx-paragraph"><strong>第一部分  项目背景</strong></p><p class="docx-paragraph"><a id="gnxz"></a><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">一、项目所属领域发展现状及趋势</span></p><p class="docx-paragraph"><a id="xmbj"></a><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">近年来，机器人技术在工业自动化领域得到了广泛应用，尤其是高性能工业机器人。随着机器人应用范围的不断扩大和工作环境的不断变异，机器人在运动过程中必须充分考虑刚柔耦合效应以及关节依赖，因此全局刚柔耦合动力学建模和关节依赖标定方法的研究变得越来越重要。国内外研究机构和企业广泛开展了相关研究工作。在全局刚柔耦合动力学建模方面，国外机构和学者较早开始研究，如德国的弗劳恩霍夫研究院等，他们利用柔性多体动力学模型，建立了机器人的全局刚柔耦合模型，并研究了模型的求解方法。国内也涌现出了一批研究机构和学者，如中国科学技术大学、哈尔滨工业大学等，他们基于深度学习等方法，提出了一些新的全局刚柔耦合动力学建模方法。在关节依赖标定方法方面，国外机构和企业也进行了一些研究，如英国的谢菲尔德大学等，他们利用加权最小二乘法对关节依赖进行标定。同时，国内的一些研究机构和企业也开始着手研究这一领域，如清华大学、上海交通大学等，他们提出了一些新的关节依赖标定方法，如基于深度神经网络等方法。总的来说，全局刚柔耦合动力学建模以及关节依赖标定方法的研究已经成为高性能工业机器人领域的研究热点。</span></p><p class="docx-paragraph"><strong><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">第二部分</span>  <span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">项目实施内容及目标</span></strong></p><p class="docx-paragraph"><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">一、项目实施内容与所在平台研究领域的关联性，对平台建设的带动性</span></p><p class="docx-paragraph"><a id="yjnr"></a><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">本项目与申报通知要求的关联性较大。首先，工业机器人的应用与制造领域</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g003" data-side="primary" data-match-type="exact" data-tone="strong">的现代化生产密切相关，提高其动态性能、精度、可靠性和灵活性有助于加速工业升级和提升制造业的核心竞争力。其次，机器人技术是推动中国式现代化河北场景建设的重要技术支撑之一，提高机器人性能和应用水平可以支持场景建设的多个领域，从而推进集约化、智能化的生产和服务形态的发展。最后，研究全局刚柔耦合动力学建模以及关节依赖标定方法等方面的技术创新，有助于提高我国在机器人领域的自主创新能力，促进产业发展和国际竞争力的提升。本项目的实施与申报通知要求及支持方向存在一定的关联性，有助于推动中国式现代化河北场景建设和产业升级发展。</span></p><p class="docx-paragraph">二、项目实施内容、研究方法及技术路线</p><p class="docx-paragraph">（一）项目的主要实施内容</p><p class="docx-paragraph"><a id="shxy"></a>（1）高性能工业机器人的全局刚柔耦合动力学建模方法研究 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g004" data-side="primary" data-match-type="exact" data-tone="strong">传统的柔性关节模型仅对驱动关节的扭转弹性进行建模，忽略了基座、轴承、臂杆结构柔性，末端工具变形对系统动力学特性的影响，已无法准确描述高速重载等极限工况条件下引发的复杂振动模态，有限元模型与假设模态法虽然可以精确建模，但因模型复杂而多用于机构强度分析，为此必须寻求高控制带宽（通常在</span> <span class="hit strong" data-match-id="g004" data-side="primary" data-match-type="exact" data-tone="strong">0-100Hz</span> <span class="hit strong" data-match-id="g004" data-side="primary" data-match-type="exact" data-tone="strong">范围）条件下，全面考虑复杂刚柔耦合影响的集中质量参数建模途径；此外，为提高全工作空间下模型参数估计精度，需进行非线性干扰的补偿与抑制，并通过全局优化实现模型参数的最优估计，为控制系统设计奠定精确、合理的模型基础。</span> </p><p class="docx-paragraph">（2）高性能工业机器人的广义运动学误差建模与补偿方法研究 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g005" data-side="primary" data-match-type="exact" data-tone="strong">考虑到影响机器人定位精度的误差因素复杂且相互耦合，必须研究不受机器人误差生成机理及作用规律限制的非参数建模方法，以充分表征臂杆长度、结构装配、传动装置、轴承变形等各类复杂非线性因素对机器人定位精度的影响。但常规的多项式拟合存在极易陷入局部最优或出现过拟合等不足，为此需综合分析测量误差数据累积对非参数模型的作用机理，以及各类几何误差和关节依赖误差特性的广义运动学误差特性，基于最佳一致逼近理论研究误差的建模及其参数辨识方法，据此设计关节运动指令补偿算法对末端执行器定位提供准确的伺服修正。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g005" data-side="primary" data-match-type="exact" data-tone="strong">(3)高精度控制技术方面。</span></p><p class="docx-paragraph"><span class="hit strong" data-match-id="g005" data-side="primary" data-match-type="exact" data-tone="strong">机器人全局刚柔耦合动力学模型是一类欠驱动、非线性、多体系统，此类模型通常微分非平坦且模型逆是动态的、内部动力学不稳定，驱动关节力矩与期望运动伺服约束流形非理想正交，必须寻求系统模型动态逆及其前馈控制的有效设计方法，以期提高系统的动态响应及轨迹跟踪性能。</span></p><p class="docx-paragraph">（二）项目拟采取的研究方法</p><p class="docx-paragraph"><a id="glgx"></a>（1）高性能工业机器人的全局刚柔耦合动力学建模方法研究 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">本课题首先基于自下而上的方式进行柔性关节模型的扩展，技术路线图参考附件。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">在经典刚性多体动力学模型基础上，根据减速器的分布情况添加驱动柔性关节，以描述扭转方向的柔性特征；进一步借助机器人</span> <span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">CAD</span> <span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">模型、部件数据等系统弹性分布先验知识及有限元模态分析数据来推测虚拟关节的数量、位置和方向，建立候选的扩展虚拟柔性关节集合。该集合包含了机器人各类构型下可能的弹性分布。最后基于</span> <span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">Lagrange</span> <span class="hit strong" data-match-id="g006" data-side="primary" data-match-type="exact" data-tone="strong">方法推导基于扩展虚拟柔性关节的工业机器人动力学模型，由此获得充分考虑各类刚柔耦合影响的机器人非线性灰箱模型。扩展柔性关节的动力学模型采用集中质量参数的描述方式，可以在较小模型规模的前提下描述机器人全方位的弹性特征。此外，集中质量法利用弹性元件连接各刚体构成连续运动链，因此非常适合采用大数据压缩的频域辨识方法获得模型参数的最优估计。待估计的模型参数可分为刚体参数、弹性参数（刚度和阻尼）和库伦摩擦参数，为提高弹性参数的估计精度，减小候选模型结构辨识的工作量，采用可分离最小二乘法辨识库伦摩擦和刚体参数，在此基础上进行非线性灰箱模型的频域辨识。</span> </p><p class="docx-paragraph">（2）高性能工业机器人的广义运动学误差建模与补偿方法研究 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g007" data-side="primary" data-match-type="exact" data-tone="strong">影响机器人定位精度的因素多种多样，臂杆长度和装配误差、初始对准偏差及反复校准引入的零位偏移误差等几何相关误差是工业机器人定位误差主要来源，但是轴承与谐波齿轮的不均匀性、臂杆弹性变形等也会产生显着的误差。这些误差均与关节运动相关，且参数间耦合关系复杂，因此无法获得各类误差与运动状态的解析表达。但各类误差对于机器人末端而言可以表征为平动及转动误差的高阶累积，因此本研究拟采用形式精简的多项式拟合方式建立包含该类几何相关误差、关节依赖误差的广义运动学误差模型，其中切比雪夫基函数各阶之间存在明晰的递进依赖关系，能很好表征串联关节间的误差累积特性，特别是其具备的正交性、奇偶性、有界性、完备性等优异特征，在全工作空间海量数据拟合中可以最大限度地避免陷入局部最优或出现过拟合现象，获得最佳一致逼近。总之，采用切比雪夫基函数的高阶广义运动学误差模型有望为关节依赖误差的补偿提供一种精简且有效的表达形式。</span> </p><p class="docx-paragraph">（3）基于模型动态逆的高性能工业机器人控制方法研究 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g008" data-side="primary" data-match-type="exact" data-tone="strong">设计基于期望运动伺服约束的模型动态逆前馈控制，结合干扰观测的自适应积分滑模反馈控制方法，以实现系统的高精度轨迹跟踪控制。在前馈控制器的设计过程中，为获取模型的非线性输入-输出正规型表达，拟采用非线性坐标变换的方式，其中涉及系统输出</span> <span class="hit strong" data-match-id="g008" data-side="primary" data-match-type="exact" data-tone="strong">Lie</span> <span class="hit strong" data-match-id="g008" data-side="primary" data-match-type="exact" data-tone="strong">导数的状态空间表达和符号运算，为此，基于微分几何非线性控制理论，通过微分同胚坐标变换将其转化为包括系列微分器、驱动内部动力学以及几何项的非线性输入输出正规型形式，为前馈控制器的设计奠定分析模型基础。显而易见，系统内部零动力学的稳定性分析十分复杂，且其不仅与系统的输入输出有关，而且还与系统的几何和质量分布的特性相关，对于工业机器人系统而言，由于需在全工作空间内工作，很难通过优化输入轨迹和运动构型的传统手段以保证系统模型的最小相位特性，因此，必须充分考虑系统非最小相位特性进行模型逆的求解。自适应滑模反馈控制器的设计方法是建立在系统动力学模型基础上，为此，在全局动力学模型的基础上考虑未知时变扰动及未建模动态项的影响，并充分利用机器人模型中惯性系数矩阵正定、系统的状态和信号一致有界的特性，通过局部线性化、线性变换、</span> <span class="hit strong" data-match-id="g008" data-side="primary" data-match-type="exact" data-tone="strong">Schur</span> <span class="hit strong" data-match-id="g008" data-side="primary" data-match-type="exact" data-tone="strong">分解等一系列数学运算，将欠驱动非线性全局动力学方程转化成级联形式，以便于控制器的设计。</span></p><p class="docx-paragraph">三、项目预期的主要创新点</p><p class="docx-paragraph"><a id="xmmb"></a><span class="hit strong" data-match-id="g009" data-side="primary" data-match-type="exact" data-tone="strong">(1)提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔</span> <span class="hit strong" data-match-id="g009" data-side="primary" data-match-type="exact" data-tone="strong">耦合动力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽范围（0-100Hz）内全面考虑了系统的复杂刚柔耦合影响，为高性能工业机器人控制系统设计奠定了精准、合理的模型基础。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g009" data-side="primary" data-match-type="exact" data-tone="strong">(2)提出一种基于切比雪夫基函数的机器人广义运动学误差建模方法，对各类几何和关节依赖误差进行全面表征，其不受机器人误差生成机理及作用规律的限制，且能最大限度地避免陷入局部最优或过拟合，基于最佳一致逼近估计的误差补偿算法有望对末端执行器位姿进行准确伺服修正。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g009" data-side="primary" data-match-type="exact" data-tone="strong">(3)针对高性能工业机器人这类刚柔耦合、复杂非线性系统，提出一种基于期望运动伺服约束的模型动态逆前馈控制结合自适应积分型滑模反馈控制的设计方法，以保证机器人系统的鲁棒稳定和高动态响应，有望实现对全局刚柔耦合动力学模型的精准跟随和机器人系统的高精度控制。</span></p><p class="docx-paragraph">四、项目实施的预期经济社会效益及对相关产业带动促进作用</p><p class="docx-paragraph"><a id="khmb"></a><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">论文</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">在全局动力学建模、运动学误差标定等前沿领域预期在国际、国内核心刊物发表论</span> 文 3 <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">篇，其中被</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">SCI</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">检索</span> 2 <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">篇。</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">专利</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">在全局动力学建模、运动学误差标定等前沿领域预期发表实用新型专利或软件著作</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">4~5</span> 个 </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">人才培养</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">培养青年人才</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">8-9</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">名。此外，培养高性能工业机器人技术应用人才</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">30-40</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">名，以促进成果应用与转化。</span></p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">国际交流</span> </p><p class="docx-paragraph"><span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">出国参加国际学术交流活动（6</span> <span class="hit strong" data-match-id="g010" data-side="primary" data-match-type="exact" data-tone="strong">人次以上），了解国际学术动态，宣传国内的研究成果。</span></p>
`;

const sourceCards = `
<div class="source-card" data-match-id="g001">
  <div class="source-card-title">#1 在我国大力倡导智能制造引领工业制造的时代背景下，传统的以劳动密集手工模式制造过程，已成为严重制约产品制造效率和质量的瓶颈，发展和应用以工业机器人为代表的自动化设备平台，对于生产模式...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L117 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g001">在我国大力倡导智能制造引领工业制造的时代背景下，传统的以劳动密集手工模式制造过程，已成为严重制约产品制造效率和质量的瓶颈，发展和应用以工业机器人为代表的自动化设备平台，对于生产模式转型升级和装备先进制造能力提升具有十分重要的战略意义和巨大价值。随着现代工业制造的智能化、网络化发展，制造产品的尺寸大、载荷重、结构复杂，这对现代工业机器人的性能提出了更高的要求：为适应工业机器人多臂协同、人机协作等高度自主、柔性化、自动化生产的发展，必须着力提升工业机器人本体的高工作节拍(高速、高带宽)、重载(载荷/自重比大)极限工况条件下的高精度控制性能。如ABB公司的IRB7600机器人是典型代表之一，其有效载荷范围150-500kg，最大承重能力650kg，关节运动角速度最高可达190°/s，定位精度0.55-1.2mm。总体上，与国外先进技术有很大差距，相关研究瓶颈还亟待突破，作为新的经济增长点，打破国外技术垄断，突破制约高速重载、高加速等极限工况下工业机器人运动控制精度的技术瓶颈，并推动其在行业中的广泛应用。</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g002">
  <div class="source-card-title">#2 (1) 提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔耦合动 力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽 范围（0-...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">74107418021a49ca911e9b285c56e431.docx L111 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g002">(1) 提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔耦合动力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽 范围（0-100Hz）内全面考虑了系统的复杂刚柔耦合影响，为高性能工业机器人控制系统设计奠定了精准、合理的模型基础。 (2) 提出一种基于切比雪夫基函数的机器人广义运动学误差建模方法，对各类几何和关节依赖误差进行全面表征，其不受机器人误差生成机理及作用规律的限制，且能最大限度地避免陷入局部最优或过拟合，基于最佳一致逼近估计的误差补偿算法有望对末端执行器位姿进行准确伺服修正。 (3) 针对高性能工业机器人这类刚柔耦合、复杂非线性系统，提出一种基于期望运动伺服约束的模型动态逆前馈控制结合自适应积分型滑模反馈控制的设计方法，以保证机器人系统的鲁棒稳定和高动态响应，有望实现对全局刚柔耦合动力学模型的精准跟随和机器人系统的高精度控制。</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g003">
  <div class="source-card-title">#3 一、项目所属领域发展现状及趋势 近年来，机器人技术在工业自动化领域得到了广泛应用，尤其是高性能工业机器人。随着机器人应用范围的不断扩大和工作环境的不断变异，机器人在运动过程中必须充...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L123 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g003">一、项目所属领域发展现状及趋势 近年来，机器人技术在工业自动化领域得到了广泛应用，尤其是高性能工业机器人。随着机器人应用范围的不断扩大和工作环境的不断变异，机器人在运动过程中必须充分考虑刚柔耦合效应以及关节依赖，因此全局刚柔耦合动力学建模和关节依赖标定方法的研究变得越来越重要。国内外研究机构和企业广泛开展了相关研究工作。在全局刚柔耦合动力学建模方面，国外机构和学者较早开始研究，如德国的弗劳恩霍夫研究院等，他们利用柔性多体动力学模型，建立了机器人的全局刚柔耦合模型，并研究了模型的求解方法。国内也涌现出了一批研究机构和学者，如中国科学技术大学、哈尔滨工业大学等，他们基于深度学习等方法，提出了一些新的全局刚柔耦合动力学建模方法。在关节依赖标定方法方面，国外机构和企业也进行了一些研究，如英国的谢菲尔德大学等，他们利用加权最小二乘法对关节依赖进行标定。同时，国内的一些研究机构和企业也开始着手研究这一领域，如清华大学、上海交通大学等，他们提出了一些新的关节依赖标定方法，如基于深度神经网络等方法。总的来说，全局刚柔耦合动力学建模以及关节依赖标定方法的研究已经成为高性能工业机器人领域的研究热点。</span></div>
    </div>
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L126 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g003">一、项目实施内容与所在平台研究领域的关联性，对平台建设的带动性 本项目与申报通知要求的关联性较大。首先，工业机器人的应用与制造领域 的现代化生产密切相关，提高其动态性能、精度、可靠性和灵活性有助于加速工业升级和提升制造业的核心竞争力。其次，机器人技术是推动中国式现代化河北场景建设的重要技术支撑之一，提高机器人性能和应用水平可以支持场景建设的多个领域，从而推进集约化、智能化的生产和服务形态的发展。最后，研究全局刚柔耦合动力学建模以及关节依赖标定方法等方面的技术创新，有助于提高我国在机器人领域的自主创新能力，促进产业发展和国际竞争力的提升。本项目的实施与申报通知要求及支持方向存在一定的关联性，有助于推动中国式现代化河北场景建设和产业升级发展。</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g004">
  <div class="source-card-title">#4 传统的柔性关节模型仅对驱动关节的扭转弹性进行建模，忽略了基座、轴承、臂杆结构柔性，末端工具变形对系统动力学特性的影响，已...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L132 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g004">传统的柔性关节模型仅对驱动关节的扭转弹性进行建模，忽略了基座、轴承、臂杆结构柔性，末端工具变形对系统动力学特性的影响，已无法准确描述高速重载等极限工况条件下引发的复杂振动模态，有限元模型与假设模态法虽然可以精确建模，但因模型复杂而多用于机构强度分析，为此必须寻求高控制带宽（通常在 0-100Hz 范围）条件下，全面考虑复杂刚柔耦合影响的集中质量参数建模途径；此外，为提高全工作空间下模型参数估计精度，需进行非线性干扰的补偿与抑制，并通过全局优化实现模型参数的最优估计，为控制系统设计奠定精确、合理的模型基础</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g005">
  <div class="source-card-title">#5 考虑到影响机器人定位精度的误差因素复杂且相互耦合，必须研究不受机器人误差生成机理及作用规律限制的非参数建模方法，以充分表征臂杆长度、结构装配、传动装置、轴承变形等各类复杂非线性因素...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L134 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g005">考虑到影响机器人定位精度的误差因素复杂且相互耦合，必须研究不受机器人误差生成机理及作用规律限制的非参数建模方法，以充分表征臂杆长度、结构装配、传动装置、轴承变形等各类复杂非线性因素对机器人定位精度的影响。但常规的多项式拟合存在极易陷入局部最优或出现过拟合等不足，为此需综合分析测量误差数据累积对非参数模型的作用机理，以及各类几何误差和关节依赖误差特性的广义运动学误差特性，基于最佳一致逼近理论研究误差的建模及其参数辨识方法，据此设计关节运动指令补偿算法对末端执行器定位提供准确的伺服修正</span></div>
    </div>
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L136 · 相似度 0.99</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g005">机器人全局刚柔耦合动力学模型是一类欠驱动、非线性、多体系统，此类模型通常微分非平坦且模型逆是动态的、内部动力学不稳定，驱动关节力矩与期望运动伺服约束流形非理想正交，必须寻求系统模型动态逆及其前馈控制的有效设计方法，以期提高系统的动态响应及轨迹跟踪性能</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g006">
  <div class="source-card-title">#6 本课题首先基于自下而上的方式进行柔性关节模型的扩展，技术路线图参考附件。 在经典刚性多体动力学模型基础上，根据减速器的分布情况添加驱动柔性关节，以描述扭转方向的柔性特征；进一步借助...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L139 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g006">本课题首先基于自下而上的方式进行柔性关节模型的扩展，技术路线图参考附件。 在经典刚性多体动力学模型基础上，根据减速器的分布情况添加驱动柔性关节，以描述扭转方向的柔性特征；进一步借助机器人 CAD 模型、部件数据等系统弹性分布先验知识及有限元模态分析数据来推测虚拟关节的数量、位置和方向，建立候选的扩展虚拟柔性关节集合。该集合包含了机器人各类构型下可能的弹性分布。最后基于 Lagrange 方法推导基于扩展虚拟柔性关节的工业机器人动力学模型，由此获得充分考虑各类刚柔耦合影响的机器人非线性灰箱模型。扩展柔性关节的动力学模型采用集中质量参数的描述方式，可以在较小模型规模的前提下描述机器人全方位的弹性特征。此外，集中质量法利用弹性元件连接各刚体构成连续运动链，因此非常适合采用大数据压缩的频域辨识方法获得模型参数的最优估计。待估计的模型参数可分为刚体参数、弹性参数（刚度和阻尼）和库伦摩擦参数，为提高弹性参数的估计精度，减小候选模型结构辨识的工作量，采用可分离最小二乘法辨识库伦摩擦和刚体参数，在此基础上进行非线性灰箱模型的频域辨识</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g007">
  <div class="source-card-title">#7 影响机器人定位精度的因素多种多样，臂杆长度和装配误差、初始对准偏差及反复校准引入的零位偏移误差等几何相关误差是工业机器人定位误差主要来源，但是轴承与谐波齿轮的不均匀性、臂杆弹性变形...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L142 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g007">影响机器人定位精度的因素多种多样，臂杆长度和装配误差、初始对准偏差及反复校准引入的零位偏移误差等几何相关误差是工业机器人定位误差主要来源，但是轴承与谐波齿轮的不均匀性、臂杆弹性变形等也会产生显着的误差。这些误差均与关节运动相关，且参数间耦合关系复杂，因此无法获得各类误差与运动状态的解析表达。但各类误差对于机器人末端而言可以表征为平动及转动误差的高阶累积，因此本研究拟采用形式精简的多项式拟合方式建立包含该类几何相关误差、关节依赖误差的广义运动学误差模型，其中切比雪夫基函数各阶之间存在明晰的递进依赖关系，能很好表征串联关节间的误差累积特性，特别是其具备的正交性、奇偶性、有界性、完备性等优异特征，在全工作空间海量数据拟合中可以最大限度地避免陷入局部最优或出现过拟合现象，获得最佳一致逼近。总之，采用切比雪夫基函数的高阶广义运动学误差模型有望为关节依赖误差的补偿提供一种精简且有效的表达形式</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g008">
  <div class="source-card-title">#8 设计基于期望运动伺服约束的模型动态逆前馈控制，结合干扰观测的自适应积分滑模反馈控制方法，以实现系统的高精度轨迹跟踪控制。在前馈控制器的设计过程中，为获取模型的非线性输入-输出正规型...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L144 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g008">设计基于期望运动伺服约束的模型动态逆前馈控制，结合干扰观测的自适应积分滑模反馈控制方法，以实现系统的高精度轨迹跟踪控制。在前馈控制器的设计过程中，为获取模型的非线性输入-输出正规型表达，拟采用非线性坐标变换的方式，其中涉及系统输出 Lie 导数的状态空间表达和符号运算，为此，基于微分几何非线性控制理论，通过微分同胚坐标变换将其转化为包括系列微分器、驱动内部动力学以及几何项的非线性输入输出正规型形式，为前馈控制器的设计奠定分析模型基础。显而易见，系统内部零动力学的稳定性分析十分复杂，且其不仅与系统的输入输出有关，而且还与系统的几何和质量分布的特性相关，对于工业机器人系统而言，由于需在全工作空间内工作，很难通过优化输入轨迹和运动构型的传统手段以保证系统模型的最小相位特性，因此，必须充分考虑系统非最小相位特性进行模型逆的求解。自适应滑模反馈控制器的设计方法是建立在系统动力学模型基础上，为此，在全局动力学模型的基础上考虑未知时变扰动及未建模动态项的影响，并充分利用机器人模型中惯性系数矩阵正定、系统的状态和信号一致有界的特性，通过局部线性化、线性变换、 Schur 分解等一系列数学运算，将欠驱动非线性全局动力学方程转化成级联形式，以便于控制器的设计</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g009">
  <div class="source-card-title">#9 (1)提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔 耦合动力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽范围（0-10...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">68738c4c63f7487e933245b25a6d1b69.docx L119 · 相似度 1.00</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g009">(1) 提出一种基于扩展虚拟柔性关节结构化模型结合频域灰箱参数辨识的全局刚柔耦合动 力学建模方法，结构化模型仍采用集中质量参数表达，形式简洁、规范；且在感兴趣的控制带宽 范围（0-100Hz）内全面考虑了系统的复杂刚柔耦合影响，为高性能工业机器人控制系统设计奠 定了精准、合理的模型基础。 (2) 提出一种基于切比雪夫基函数的机器人广义运动学误差建模方法，对各类几何和关节 依赖误差进行全面表征，其不受机器人误差生成机理及作用规律的限制，且能最大限度地避免陷 入局部最优或过拟合，基于最佳一致逼近估计的误差补偿算法有望对末端执行器位姿进行准确伺 服修正。 (3) 针对高性能工业机器人这类刚柔耦合、复杂非线性系统，提出一种基于期望运动伺服约束的模型动态逆前馈控制结合自适应积分型滑模反馈控制的设计方法，以保证机器人系统的鲁 棒稳定和高动态响应，有望实现对全局刚柔耦合动力学模型的精准跟随和机器人系统的高精度控 制。</span></div>
    </div>
  </div>
</div>
<div class="source-card" data-match-id="g010">
  <div class="source-card-title">#10 论文 在全局动力学建模、运动学误差标定等前沿领域预期在国际、国内核心刊物发表论 文 3 篇，其中被 SCI 检索 2 篇。 专利 在全局动力学建模、运动学误差标定等前沿领域预期发表...</div>
  <div class="source-list">
    <div class="source-item">
      <div class="source-meta">74107418021a49ca911e9b285c56e431.docx L218 · 相似度 0.92</div>
      <div class="source-text"><span class="hit soft" data-side="source" data-match-id="g010">3）论文 在全局动力学建模、运动学误差标定等前沿领域预期在国际、国内核心刊物发表论文3篇，其中被 SCI检索2篇。 4）专利 在全局动力学建模、运动学误差标定等前沿领域预期发表实用新型专利或软件著作4~5个 5）人才培养 培养青年人才8-9名。此外，培养高性能工业机器人技术应用人才30-40 名，以促进成果应用与转化。 6）国际交流 出国参加国际学术交流活动（6人次以上），了解国际学术动态，宣传国内的研究成果。</span></div>
    </div>
  </div>
</div>
`;

const reportMarkup = `
<div class="page">
  <div class="toolbar">
    <div>
      <div class="title">查重可视化报告</div>
      <div class="toolbar-subtitle">左侧主文档：相似组1-A.docx ｜ 右侧来源片段：2 个文档</div>
      <div class="stats">
        <div class="stat-card"><div class="stat-label">有效重复率</div><div class="stat-value" style="color: #dc2626;">94.14%</div></div>
        <div class="stat-card"><div class="stat-label">总重复率</div><div class="stat-value">96.63%</div></div>
        <div class="stat-card"><div class="stat-label">有效/总字数</div><div class="stat-value" style="font-size: 16px;">4,354 / 4,625</div></div>
      </div>
    </div>
    <div class="meta">
      <div class="pill">有效重复段：10</div>
      <div class="pill">已高亮：10</div>
      <div class="pill">未定位：0</div>
      <div class="pill">模板段：1</div>
      <div class="pill">有效字符：4354</div>
    </div>
  </div>
  <div class="main">
    <aside class="sidebar">
      <div class="nav-title">重复片段导航</div>
      ${navItems.map((item) => `
        <button class="nav-item" data-match-id="${item.id}">
          <div class="nav-header">${item.title}${item.extra ? ` <span class="pill pill-small">${item.extra}</span>` : ''}</div>
          <div class="nav-text">${item.text}</div>
          <small>${item.meta}</small>
        </button>
      `).join('')}
    </aside>
    <section class="content">
      <div class="panel">
        <div class="panel-header"><span>Primary</span><span>相似组1-A.docx</span></div>
        <div id="primary-panel" class="panel-body">
          <div class="docx-content">${primaryHtml}</div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><span>Sources</span><span>2 docs</span></div>
        <div id="source-panel" class="panel-body">
          ${sourceCards}
        </div>
      </div>
    </section>
  </div>
</div>
`;

function activateMatch(matchId) {
  const root = reportRoot.value;
  if (!root) return;
  root.querySelectorAll('.hit.active').forEach((el) => el.classList.remove('active'));
  root.querySelectorAll('.nav-item.active').forEach((el) => el.classList.remove('active'));
  const hits = Array.from(root.querySelectorAll(`.hit[data-match-id="${matchId}"]`));
  hits.forEach((el) => el.classList.add('active'));
  const navItem = root.querySelector(`.nav-item[data-match-id="${matchId}"]`);
  if (navItem) navItem.classList.add('active');
  if (hits.length) {
    const primaryHit = hits.find((el) => el.dataset.side === 'primary') || hits[0];
    const sourceHit = hits.find((el) => el.dataset.side === 'source');
    primaryHit?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    sourceHit?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

onMounted(() => {
  const root = reportRoot.value;
  if (!root) return;
  root.addEventListener('click', (event) => {
    const target = event.target.closest('.hit, .nav-item');
    if (!target) return;
    const matchId = target.dataset.matchId;
    if (!matchId) return;
    event.preventDefault();
    activateMatch(matchId);
  });
  const first = root.querySelector('.nav-item[data-match-id="g001"]');
  first?.classList.add('active');
});
</script>

<template>
  <div ref="reportRoot" class="report-root" v-html="reportMarkup" />
</template>

<style scoped>
.report-root {
  height: 100%;
  min-height: 0;
}

:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  background: #f5f7fb;
  color: #1f2937;
}

:global(.page) {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

:global(.toolbar) {
  position: sticky;
  top: 0;
  z-index: 20;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

:global(.title) {
  font-size: 18px;
  font-weight: 700;
}

:global(.toolbar-subtitle) {
  font-size: 13px;
  color: #6b7280;
  margin-top: 4px;
}

:global(.meta) {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

:global(.pill) {
  background: #eef2ff;
  color: #3730a3;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}

:global(.pill-small) {
  padding: 2px 6px;
  font-size: 10px;
}

:global(.main) {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 12px;
  padding: 12px;
}

:global(.sidebar) {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px;
  overflow: auto;
}

:global(.content) {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-height: 0;
}

:global(.panel) {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

:global(.panel-header) {
  padding: 12px 14px;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 700;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  background: #f8fafc;
}

:global(.panel-body) {
  padding: 16px;
  overflow: auto;
  scroll-behavior: smooth;
}

:global(.nav-title) {
  font-weight: 700;
  margin-bottom: 10px;
  font-size: 14px;
}

:global(.nav-item) {
  width: 100%;
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  font-size: 13px;
}

:global(.nav-item:hover) {
  border-color: #fca5a5;
  background: #fff5f5;
}

:global(.nav-item.active) {
  border-color: #ef4444;
  background: #fef2f2;
}

:global(.nav-header) {
  font-weight: 600;
  margin-bottom: 4px;
}

:global(.nav-text) {
  color: #374151;
  margin-bottom: 4px;
}

:global(.nav-item small) {
  display: block;
  color: #6b7280;
  font-size: 11px;
}

:global(.source-card) {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 10px;
  background: #ffffff;
}

:global(.source-card-title) {
  font-size: 12px;
  color: #0f172a;
  font-weight: 600;
  margin-bottom: 8px;
}

:global(.source-item) {
  border-top: 1px dashed #e2e8f0;
  padding-top: 8px;
  margin-top: 8px;
}

:global(.source-item:first-child) {
  border-top: 0;
  padding-top: 0;
  margin-top: 0;
}

:global(.source-meta) {
  font-size: 11px;
  color: #475569;
  margin-bottom: 4px;
}

:global(.source-text) {
  font-size: 13px;
  line-height: 1.6;
  color: #1f2937;
}

:global(.hit) {
  color: inherit !important;
  border-radius: 3px;
  padding: 0 1px;
  transition: background .12s ease;
}

:global(.hit.strong) {
  background: rgba(220, 38, 38, 0.34) !important;
}

:global(.hit.strong:hover) {
  background: rgba(220, 38, 38, 0.42) !important;
}

:global(.hit.soft) {
  background: rgba(248, 113, 113, 0.20) !important;
}

:global(.hit.soft:hover) {
  background: rgba(248, 113, 113, 0.28) !important;
}

:global(.hit.active) {
  box-shadow: 0 0 0 2px rgba(153, 27, 27, 0.35) !important;
  outline: 1px solid rgba(127, 29, 29, 0.65);
  background-image: linear-gradient(rgba(253, 224, 71, 0.72), rgba(253, 224, 71, 0.72)) !important;
  background-blend-mode: multiply;
}

:global(.empty) {
  color: #9ca3af;
  font-size: 13px;
  padding: 20px;
  text-align: center;
}

:global(.stats) {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
  width: 100%;
}

:global(.stat-card) {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
}

:global(.stat-label) {
  font-size: 12px;
  color: #64748b;
}

:global(.stat-value) {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

:global(.docx-content) {
  line-height: 1.6;
  font-size: 14px;
  color: #333;
}

:global(.docx-content p) {
  margin: 0.5em 0;
}

:global(.docx-content h1),
:global(.docx-content h2),
:global(.docx-content h3),
:global(.docx-content h4),
:global(.docx-content h5),
:global(.docx-content h6) {
  margin: 1em 0 0.5em;
  font-weight: bold;
  color: #1a1a1a;
}

:global(.docx-content h1) { font-size: 1.5em; }
:global(.docx-content h2) { font-size: 1.3em; }
:global(.docx-content h3) { font-size: 1.15em; }

:global(.docx-content table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
}

:global(.docx-content table td),
:global(.docx-content table th) {
  border: 1px solid #ddd;
  padding: 8px;
  text-align: left;
}

:global(.docx-content table th) {
  background: #f5f5f5;
  font-weight: bold;
}

:global(.docx-content ul),
:global(.docx-content ol) {
  margin: 0.5em 0;
  padding-left: 2em;
}

:global(.docx-content li) {
  margin: 0.25em 0;
}

:global(.docx-content img) {
  max-width: 100%;
  height: auto;
}

:global(.docx-content strong) {
  font-weight: bold;
}

:global(.docx-content em) {
  font-style: italic;
}

@media (max-width: 1100px) {
  :global(.main) {
    grid-template-columns: 1fr;
  }

  :global(.content) {
    grid-template-columns: 1fr;
  }
}
</style>
