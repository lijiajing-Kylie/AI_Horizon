/**
 * Paper category mapping: raw categories (arXiv codes / OpenAlex topics) →
 * unified category IDs (for filtering) + Chinese display names.
 *
 * This is a pure frontend lookup table — no backend changes needed.
 * New raw categories that appear from upstream can be added here as they arise.
 */

// ── Unified category IDs ───────────────────────────────────────────────────

export const UNIFIED_CATEGORY_IDS = [
  // Visible in the two-level hierarchy filter
  'machine-learning',
  'deep-learning',
  'reinforcement-learning',
  'nlp-llm',
  'computer-vision',
  'multimodal',
  'speech-audio',
  'llm',
  'image-video-generation',
  'agent-multi-agent',
  'ai-systems',
  'embodied-robotics',

  // Kept for backward compatibility with existing data — hidden from filter UI
  'generative-models',
  'robotics-control',
  'graph-learning',
  'interdisciplinary',
  'other',
] as const

export type UnifiedCategoryId = (typeof UNIFIED_CATEGORY_IDS)[number]

export const UNIFIED_LABELS_ZH: Record<UnifiedCategoryId, string> = {
  'machine-learning': '机器学习',
  'deep-learning': '深度学习',
  'reinforcement-learning': '强化学习',
  'nlp-llm': '自然语言处理',
  'computer-vision': '计算机视觉',
  'multimodal': '多模态',
  'speech-audio': '语音与音频',
  'llm': '大语言模型',
  'image-video-generation': '图像与视频生成',
  'agent-multi-agent': 'Agent 与多智能体',
  'ai-systems': 'AI 系统与模型优化',
  'embodied-robotics': '机器人与具身智能',

  // Legacy IDs — kept for backward-compatible display of existing paper data
  'generative-models': '生成模型',
  'robotics-control': '机器人与控制',
  'graph-learning': '图学习',
  'interdisciplinary': '跨学科',
  'other': '其他',
}

// ── Raw category → unified category ID ────────────────────────────────────

const RAW_TO_UNIFIED: Record<string, UnifiedCategoryId> = {
  // ── arXiv category codes (HuggingFace) ──
  'cs.CV': 'computer-vision',
  'cs.CL': 'nlp-llm',
  'cs.LG': 'machine-learning',
  'cs.AI': 'machine-learning',
  'cs.RO': 'embodied-robotics',
  'cs.MA': 'agent-multi-agent',
  'cs.HC': 'interdisciplinary',
  'cs.MM': 'multimodal',

  // ── OpenAlex topics ──

  // machine-learning
  'Advanced Bandit Algorithms Research': 'machine-learning',
  'Machine Learning and Algorithms': 'machine-learning',
  'Machine Learning and Data Classification': 'machine-learning',
  'Machine Learning and ELM': 'machine-learning',
  'Gaussian Processes and Bayesian Inference': 'machine-learning',
  'Bayesian Methods and Mixture Models': 'machine-learning',
  'Domain Adaptation and Few-Shot Learning': 'machine-learning',
  'Stochastic Gradient Optimization Techniques': 'machine-learning',
  'Data Mining Algorithms and Applications': 'machine-learning',
  'Adversarial Robustness in Machine Learning': 'machine-learning',
  'Optimization and Search Problems': 'machine-learning',
  'Time Series Analysis and Forecasting': 'machine-learning',

  // deep-learning
  'Neural Networks and Applications': 'deep-learning',
  'Advanced Neural Network Applications': 'deep-learning',
  'Neural Networks and Reservoir Computing': 'deep-learning',
  'Model Reduction and Neural Networks': 'deep-learning',
  'Advanced Memory and Neural Computing': 'deep-learning',
  'Memory and Neural Mechanisms': 'deep-learning',

  // computer-vision
  'Advanced Image Processing Techniques': 'computer-vision',
  'Advanced Image and Video Retrieval Techniques': 'computer-vision',
  'Face and Expression Recognition': 'computer-vision',
  'Image Processing and 3D Reconstruction': 'computer-vision',
  'Image Processing Techniques and Applications': 'computer-vision',
  'Handwritten Text Recognition Techniques': 'computer-vision',
  'Industrial Vision Systems and Defect Detection': 'computer-vision',
  'Advanced X-ray and CT Imaging': 'computer-vision',
  'Cell Image Analysis Techniques': 'computer-vision',
  'Medical Imaging Techniques and Applications': 'computer-vision',
  'Blind Source Separation Techniques': 'computer-vision',

  // nlp-llm
  'Natural Language Processing Techniques': 'nlp-llm',
  'Topic Modeling': 'nlp-llm',
  'Text and Document Classification Technologies': 'nlp-llm',
  'Text Readability and Simplification': 'nlp-llm',

  // image-video-generation (was generative-models)
  'Generative Adversarial Networks and Image Synthesis': 'image-video-generation',

  // reinforcement-learning
  'Reinforcement Learning in Robotics': 'reinforcement-learning',

  // graph-learning
  'Advanced Graph Neural Networks': 'graph-learning',

  // ai-systems
  'Parallel Computing and Optimization Techniques': 'ai-systems',
  'Advanced Data Storage Technologies': 'ai-systems',
  'Ferroelectric and Negative Capacitance Devices': 'ai-systems',
  'Auction Theory and Applications': 'ai-systems',

  // speech-audio
  'Speech Recognition and Synthesis': 'speech-audio',
  'Speech and Audio Processing': 'speech-audio',
  'Music and Audio Processing': 'speech-audio',

  // agent-multi-agent (was part of robotics-control)
  'Artificial Intelligence in Games': 'agent-multi-agent',

  // embodied-robotics (was part of robotics-control)
  'Control Systems and Identification': 'embodied-robotics',

  // multimodal (was interdisciplinary)
  'Multimodal Machine Learning Applications': 'multimodal',

  // interdisciplinary
  'Bioinformatics and Genomic Networks': 'interdisciplinary',
  'Computational Drug Discovery Methods': 'interdisciplinary',
  'Machine Learning in Healthcare': 'interdisciplinary',
  'Machine Learning in Materials Science': 'interdisciplinary',
  'Protein Structure and Dynamics': 'interdisciplinary',
  'Computational Physics and Python Applications': 'interdisciplinary',
  'Sports Analytics and Performance': 'interdisciplinary',
  'Educational Games and Gamification': 'interdisciplinary',
  'Neural dynamics and brain function': 'interdisciplinary',
  'Neural and Behavioral Psychology Studies': 'interdisciplinary',
  'Fibroblast Growth Factor Research': 'interdisciplinary',
}

// ── Raw category → Chinese display name ───────────────────────────────────

const RAW_TO_ZH: Record<string, string> = {
  // arXiv
  'cs.CV': '计算机视觉',
  'cs.CL': '自然语言处理',
  'cs.LG': '机器学习',
  'cs.AI': '人工智能',
  'cs.RO': '机器人学',
  'cs.MA': '多智能体系统',
  'cs.HC': '人机交互',
  'cs.MM': '多模态',

  // machine-learning
  'Advanced Bandit Algorithms Research': '高级赌博机算法',
  'Machine Learning and Algorithms': '机器学习与算法',
  'Machine Learning and Data Classification': '机器学习与数据分类',
  'Machine Learning and ELM': '机器学习与极限学习机',
  'Gaussian Processes and Bayesian Inference': '高斯过程与贝叶斯推断',
  'Bayesian Methods and Mixture Models': '贝叶斯方法与混合模型',
  'Domain Adaptation and Few-Shot Learning': '域适应与小样本学习',
  'Stochastic Gradient Optimization Techniques': '随机梯度优化技术',
  'Data Mining Algorithms and Applications': '数据挖掘算法与应用',
  'Adversarial Robustness in Machine Learning': '机器学习对抗鲁棒性',
  'Optimization and Search Problems': '优化与搜索问题',
  'Time Series Analysis and Forecasting': '时间序列分析与预测',

  // deep-learning
  'Neural Networks and Applications': '神经网络与应用',
  'Advanced Neural Network Applications': '高级神经网络应用',
  'Neural Networks and Reservoir Computing': '神经网络与储层计算',
  'Model Reduction and Neural Networks': '模型降阶与神经网络',
  'Advanced Memory and Neural Computing': '高级记忆与神经计算',
  'Memory and Neural Mechanisms': '记忆与神经机制',

  // computer-vision
  'Advanced Image Processing Techniques': '高级图像处理技术',
  'Advanced Image and Video Retrieval Techniques': '高级图像视频检索技术',
  'Face and Expression Recognition': '人脸与表情识别',
  'Image Processing and 3D Reconstruction': '图像处理与三维重建',
  'Image Processing Techniques and Applications': '图像处理技术与应用',
  'Handwritten Text Recognition Techniques': '手写文本识别技术',
  'Industrial Vision Systems and Defect Detection': '工业视觉系统与缺陷检测',
  'Advanced X-ray and CT Imaging': '先进 X 射线与 CT 成像',
  'Cell Image Analysis Techniques': '细胞图像分析技术',
  'Medical Imaging Techniques and Applications': '医学成像技术与应用',
  'Blind Source Separation Techniques': '盲源分离技术',

  // nlp-llm
  'Natural Language Processing Techniques': '自然语言处理技术',
  'Topic Modeling': '主题建模',
  'Text and Document Classification Technologies': '文本与文档分类技术',
  'Text Readability and Simplification': '文本可读性与简化',

  // image-video-generation
  'Generative Adversarial Networks and Image Synthesis': '生成对抗网络与图像合成',

  // reinforcement-learning
  'Reinforcement Learning in Robotics': '机器人强化学习',

  // graph-learning
  'Advanced Graph Neural Networks': '高级图神经网络',

  // ai-systems
  'Parallel Computing and Optimization Techniques': '并行计算与优化技术',
  'Advanced Data Storage Technologies': '高级数据存储技术',
  'Ferroelectric and Negative Capacitance Devices': '铁电与负电容器件',
  'Auction Theory and Applications': '拍卖理论及应用',

  // speech-audio
  'Speech Recognition and Synthesis': '语音识别与合成',
  'Speech and Audio Processing': '语音与音频处理',
  'Music and Audio Processing': '音乐与音频处理',

  // agent-multi-agent
  'Artificial Intelligence in Games': '游戏人工智能',

  // embodied-robotics
  'Control Systems and Identification': '控制系统与辨识',

  // multimodal
  'Multimodal Machine Learning Applications': '多模态机器学习应用',

  // interdisciplinary
  'Bioinformatics and Genomic Networks': '生物信息学与基因组网络',
  'Computational Drug Discovery Methods': '计算药物发现方法',
  'Machine Learning in Healthcare': '医疗健康机器学习',
  'Machine Learning in Materials Science': '材料科学机器学习',
  'Protein Structure and Dynamics': '蛋白质结构与动力学',
  'Computational Physics and Python Applications': '计算物理与 Python 应用',
  'Sports Analytics and Performance': '体育分析与表现',
  'Educational Games and Gamification': '教育游戏与游戏化',
  'Neural dynamics and brain function': '神经动力学与脑功能',
  'Neural and Behavioral Psychology Studies': '神经与行为心理学研究',
  'Fibroblast Growth Factor Research': '成纤维细胞生长因子研究',
}

// ── Unified → seed category (OpenAlex classic library) ────────────────────
// Maps unified category IDs to the seed category names used in the classic
// library's `category` column. New IDs without seed mapping yield undefined,
// meaning they rely on client-side filtering only.

export const UNIFIED_TO_SEED_CATEGORY: Partial<Record<UnifiedCategoryId, string>> = {
  'machine-learning': 'Machine Learning',
  'deep-learning': 'Deep Learning',
  'computer-vision': 'Computer Vision',
  'nlp-llm': 'NLP & LLM',
  'reinforcement-learning': 'Reinforcement Learning',
  'image-video-generation': 'Generative Models',
  'graph-learning': 'Graph Learning & Retrieval',
  'ai-systems': 'AI Systems',
}

// ── Public helpers ─────────────────────────────────────────────────────────

/** Get Chinese display name for a raw category code/name. */
export function categoryNameZh(raw: string): string {
  return RAW_TO_ZH[raw] ?? raw
}

/** Map a raw category to its unified category ID. */
export function unifiedCategoryId(raw: string): UnifiedCategoryId {
  return RAW_TO_UNIFIED[raw] ?? 'interdisciplinary'
}

/** Map multiple raw categories to deduplicated unified category IDs. */
export function unifiedCategoryIds(raws: string[]): UnifiedCategoryId[] {
  return [...new Set(raws.map(unifiedCategoryId))]
}

/** Get the Chinese label for a unified category ID. */
export function unifiedLabelZh(id: UnifiedCategoryId): string {
  return UNIFIED_LABELS_ZH[id] ?? id
}
