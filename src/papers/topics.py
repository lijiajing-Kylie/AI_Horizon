"""Paper topic classification via arXiv category mapping.

Zero-AI-cost, deterministic: reads a paper's ``categories`` list (arXiv
classification codes populated by ``_enrich_with_arxiv``, or OpenAlex topic
names) and assigns unified category IDs matching the classic library's 4-group
taxonomy defined in ``frontend/src/utils/paperCategories.ts``.

Topic seed data is also defined here so the paper pipeline can idempotently
ensure the ``topics`` table contains the paper-specific rows without depending
on ``src/seed_topics.py``.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import Paper

logger = logging.getLogger(__name__)

# ── arXiv category → unified category ID ────────────────────────────────
# Aligned with RAW_TO_UNIFIED in frontend/src/utils/paperCategoryMap.ts
_ARXIV_TO_UNIFIED: Dict[str, str] = {
    "cs.CV": "computer-vision",
    "cs.CL": "nlp-llm",
    "cs.LG": "machine-learning",
    "cs.AI": "machine-learning",
    "cs.RO": "embodied-robotics",
    "cs.MA": "agent-multi-agent",
    "cs.HC": "interdisciplinary",
    "cs.MM": "multimodal",
    "cs.IR": "interdisciplinary",
    "cs.NE": "machine-learning",
    "cs.SE": "ai-systems",
    "cs.DC": "ai-systems",
    "cs.AR": "ai-systems",
    "cs.PF": "ai-systems",
    "cs.CE": "interdisciplinary",
    "cs.CR": "interdisciplinary",
    "cs.SD": "speech-audio",
    "cs.GR": "computer-vision",
    "stat.ML": "machine-learning",
    "eess.AS": "speech-audio",
    "eess.IV": "computer-vision",
    "eess.SP": "speech-audio",
}

# ── Title/abstract keyword → unified category ID ────────────────────────
_TITLE_KEYWORDS: Dict[str, List[str]] = {
    "machine-learning": [
        "machine learning", "supervised learning", "unsupervised learning",
        "semi-supervised", "transfer learning", "federated learning",
        "representation learning", "self-supervised", "few-shot", "zero-shot",
        "meta-learning", "gradient descent", "ensemble method",
        "feature selection", "dimensionality reduction",
    ],
    "deep-learning": [
        "deep learning", "neural network", "convolutional neural",
        "recurrent neural", "transformer", "attention mechanism",
        "residual network", "batch normalization", "dropout",
        "activation function", "backpropagation",
    ],
    "reinforcement-learning": [
        "reinforcement learning", "policy gradient", "deep q-network",
        "dqn", "ppo", "reward function", "multi-armed bandit",
        "q-learning", "actor-critic", "markov decision", "mdp",
        "rlhf", "inverse reinforcement",
    ],
    "nlp-llm": [
        "language model", "natural language", "machine translation",
        "text generation", "text summarization", "question answering",
        "sentiment analysis", "named entity", "tokenizer",
        "large language model", "pretrained language", "llm",
        "dialogue system", "chatbot", "prompt engineering",
    ],
    "computer-vision": [
        "computer vision", "image recognition", "object detection",
        "image segmentation", "visual recognition", "scene understanding",
        "face recognition", "pose estimation", "image classification",
        "visual", "convolutional neural",
    ],
    "multimodal": [
        "multimodal", "vision-language", "visual question answering",
        "image captioning", "text-to-image", "cross-modal",
        "audio-visual", "video-language",
    ],
    "speech-audio": [
        "speech recognition", "automatic speech", "asr", "text-to-speech",
        "tts", "voice synthesis", "audio processing", "music generation",
        "speaker recognition", "acoustic", "phoneme",
    ],
    "llm": [
        "large language model", "llm", "gpt", "chatgpt",
        "instruction tuning", "in-context learning", "chain-of-thought",
        "reasoning", "scaling law",
    ],
    "image-video-generation": [
        "image generation", "video generation", "diffusion model",
        "gan", "generative adversarial", "vae", "variational autoencoder",
        "stable diffusion", "latent diffusion", "image synthesis",
        "text-to-image", "text-to-video",
    ],
    "agent-multi-agent": [
        "agent", "multi-agent", "tool use", "function calling",
        "planning", "reasoning agent", "autonomous agent",
        "agentic", "llm agent",
    ],
    "ai-systems": [
        "distributed training", "model parallelism", "pipeline parallelism",
        "inference optimization", "quantization", "pruning",
        "knowledge distillation", "mlsys", "compiler", "gpu",
        "accelerator", "serving", "deployment",
    ],
    "embodied-robotics": [
        "robot", "robotic", "manipulation", "grasping",
        "motion planning", "path planning", "autonomous navigation",
        "slam", "locomotion", "kinematics", "embodied",
        "sim-to-real", "end-effector",
    ],
}

# ── OpenAlex topic name keywords → unified category ID ──────────────────
# Aligned with RAW_TO_UNIFIED OpenAlex topic entries
_OPENALEX_TO_UNIFIED: Dict[str, str] = {
    # machine-learning
    "Advanced Bandit Algorithms Research": "machine-learning",
    "Machine Learning and Algorithms": "machine-learning",
    "Machine Learning and Data Classification": "machine-learning",
    "Machine Learning and ELM": "machine-learning",
    "Gaussian Processes and Bayesian Inference": "machine-learning",
    "Bayesian Methods and Mixture Models": "machine-learning",
    "Domain Adaptation and Few-Shot Learning": "machine-learning",
    "Stochastic Gradient Optimization Techniques": "machine-learning",
    "Data Mining Algorithms and Applications": "machine-learning",
    "Adversarial Robustness in Machine Learning": "machine-learning",
    "Optimization and Search Problems": "machine-learning",
    "Time Series Analysis and Forecasting": "machine-learning",
    # deep-learning
    "Neural Networks and Applications": "deep-learning",
    "Advanced Neural Network Applications": "deep-learning",
    "Neural Networks and Reservoir Computing": "deep-learning",
    "Model Reduction and Neural Networks": "deep-learning",
    "Advanced Memory and Neural Computing": "deep-learning",
    "Memory and Neural Mechanisms": "deep-learning",
    # computer-vision
    "Advanced Image Processing Techniques": "computer-vision",
    "Advanced Image and Video Retrieval Techniques": "computer-vision",
    "Face and Expression Recognition": "computer-vision",
    "Image Processing and 3D Reconstruction": "computer-vision",
    "Image Processing Techniques and Applications": "computer-vision",
    "Handwritten Text Recognition Techniques": "computer-vision",
    "Industrial Vision Systems and Defect Detection": "computer-vision",
    "Advanced X-ray and CT Imaging": "computer-vision",
    "Cell Image Analysis Techniques": "computer-vision",
    "Medical Imaging Techniques and Applications": "computer-vision",
    "Blind Source Separation Techniques": "computer-vision",
    # nlp-llm
    "Natural Language Processing Techniques": "nlp-llm",
    "Topic Modeling": "nlp-llm",
    "Text and Document Classification Technologies": "nlp-llm",
    "Text Readability and Simplification": "nlp-llm",
    # image-video-generation
    "Generative Adversarial Networks and Image Synthesis": "image-video-generation",
    # reinforcement-learning
    "Reinforcement Learning in Robotics": "reinforcement-learning",
    # graph-learning → interdisciplinary
    "Advanced Graph Neural Networks": "interdisciplinary",
    # ai-systems
    "Parallel Computing and Optimization Techniques": "ai-systems",
    "Advanced Data Storage Technologies": "ai-systems",
    "Ferroelectric and Negative Capacitance Devices": "ai-systems",
    "Auction Theory and Applications": "ai-systems",
    # speech-audio
    "Speech Recognition and Synthesis": "speech-audio",
    "Speech and Audio Processing": "speech-audio",
    "Music and Audio Processing": "speech-audio",
    # agent-multi-agent
    "Artificial Intelligence in Games": "agent-multi-agent",
    # embodied-robotics
    "Control Systems and Identification": "embodied-robotics",
    # multimodal
    "Multimodal Machine Learning Applications": "multimodal",
    # interdisciplinary
    "Bioinformatics and Genomic Networks": "interdisciplinary",
    "Computational Drug Discovery Methods": "interdisciplinary",
    "Machine Learning in Healthcare": "interdisciplinary",
    "Machine Learning in Materials Science": "interdisciplinary",
    "Protein Structure and Dynamics": "interdisciplinary",
    "Computational Physics and Python Applications": "interdisciplinary",
    "Sports Analytics and Performance": "interdisciplinary",
    "Educational Games and Gamification": "interdisciplinary",
    "Neural dynamics and brain function": "interdisciplinary",
    "Neural and Behavioral Psychology Studies": "interdisciplinary",
    "Fibroblast Growth Factor Research": "interdisciplinary",
}


# ── Seed data ───────────────────────────────────────────────────────────

def build_paper_topics() -> List[dict]:
    """Return paper-topic seed rows aligned with PAPER_CATEGORY_GROUPS.

    12 unified category IDs across 4 groups — identical to the classic
    library's two-level filter structure.
    """
    return [
        # ── 基础与模型 ──────────────────────────────────────────────────
        {
            "name": "机器学习",
            "slug": "machine-learning",
            "group_name": "基础与模型",
            "description": "监督学习、无监督学习、迁移学习、联邦学习等基础方法",
            "keywords": ["machine learning", "supervised", "unsupervised", "transfer learning"],
            "aliases": ["ml"],
            "sort_order": 10,
            "is_active": True,
        },
        {
            "name": "深度学习",
            "slug": "deep-learning",
            "group_name": "基础与模型",
            "description": "神经网络、CNN、RNN、Transformer 等深度学习架构",
            "keywords": ["deep learning", "neural network", "cnn", "rnn", "transformer"],
            "aliases": ["dl"],
            "sort_order": 20,
            "is_active": True,
        },
        {
            "name": "强化学习",
            "slug": "reinforcement-learning",
            "group_name": "基础与模型",
            "description": "策略梯度、Q-learning、多智能体、RLHF 等",
            "keywords": ["reinforcement learning", "rl", "policy gradient", "rlhf"],
            "aliases": ["rl"],
            "sort_order": 30,
            "is_active": True,
        },
        # ── 语言与视觉 ──────────────────────────────────────────────────
        {
            "name": "自然语言处理",
            "slug": "nlp-llm",
            "group_name": "语言与视觉",
            "description": "文本分类、机器翻译、对话系统、信息抽取等",
            "keywords": ["nlp", "natural language", "text", "translation"],
            "aliases": ["nlp"],
            "sort_order": 40,
            "is_active": True,
        },
        {
            "name": "计算机视觉",
            "slug": "computer-vision",
            "group_name": "语言与视觉",
            "description": "图像识别、目标检测、图像分割、视频理解等",
            "keywords": ["computer vision", "image", "object detection", "segmentation"],
            "aliases": ["cv", "视觉"],
            "sort_order": 50,
            "is_active": True,
        },
        {
            "name": "多模态",
            "slug": "multimodal",
            "group_name": "语言与视觉",
            "description": "视觉-语言模型、图文理解、跨模态学习等",
            "keywords": ["multimodal", "vision-language", "cross-modal"],
            "aliases": ["多模态"],
            "sort_order": 60,
            "is_active": True,
        },
        {
            "name": "语音与音频",
            "slug": "speech-audio",
            "group_name": "语言与视觉",
            "description": "语音识别、语音合成、音频处理、音乐生成等",
            "keywords": ["speech", "audio", "voice", "tts", "asr"],
            "aliases": ["speech"],
            "sort_order": 70,
            "is_active": True,
        },
        # ── 生成与智能体 ────────────────────────────────────────────────
        {
            "name": "大语言模型",
            "slug": "llm",
            "group_name": "生成与智能体",
            "description": "LLM 训练、推理、提示工程、思维链等",
            "keywords": ["llm", "large language model", "prompt", "reasoning"],
            "aliases": ["大模型"],
            "sort_order": 80,
            "is_active": True,
        },
        {
            "name": "图像与视频生成",
            "slug": "image-video-generation",
            "group_name": "生成与智能体",
            "description": "扩散模型、GAN、VAE、文生图、文生视频等",
            "keywords": ["diffusion", "gan", "image generation", "video generation"],
            "aliases": ["aigc", "生成"],
            "sort_order": 90,
            "is_active": True,
        },
        {
            "name": "Agent 与多智能体",
            "slug": "agent-multi-agent",
            "group_name": "生成与智能体",
            "description": "AI Agent、工具调用、规划、多智能体协作等",
            "keywords": ["agent", "multi-agent", "tool use", "planning"],
            "aliases": ["agent"],
            "sort_order": 100,
            "is_active": True,
        },
        # ── 系统与机器人 ────────────────────────────────────────────────
        {
            "name": "AI 系统与模型优化",
            "slug": "ai-systems",
            "group_name": "系统与机器人",
            "description": "分布式训练、推理优化、量化、剪枝、MLOps 等",
            "keywords": ["mlsys", "distributed", "inference", "quantization", "deployment"],
            "aliases": ["mlsys", "系统工程"],
            "sort_order": 110,
            "is_active": True,
        },
        {
            "name": "机器人与具身智能",
            "slug": "embodied-robotics",
            "group_name": "系统与机器人",
            "description": "机器人控制、运动规划、操作、导航、具身 AI 等",
            "keywords": ["robot", "robotic", "embodied", "manipulation", "navigation"],
            "aliases": ["robotics"],
            "sort_order": 120,
            "is_active": True,
        },
        # ── Hidden (backward-compatible, not in filter menu) ────────────
        {
            "name": "跨学科",
            "slug": "interdisciplinary",
            "group_name": "其他",
            "description": "AI 在生物、医疗、材料、物理等跨学科领域的应用",
            "keywords": ["bioinformatics", "drug discovery", "healthcare", "materials"],
            "aliases": [],
            "sort_order": 200,
            "is_active": True,
        },
        {
            "name": "其他",
            "slug": "other",
            "group_name": "其他",
            "description": "未匹配到专项分类的论文",
            "keywords": [],
            "aliases": [],
            "sort_order": 300,
            "is_active": True,
        },
    ]


# ── Classification ──────────────────────────────────────────────────────

def classify_paper_topics(paper: Paper) -> List[dict]:
    """Assign unified category IDs to *paper*.

    Matching order (first match wins per topic):
    1. OpenAlex topic name exact match (``_OPENALEX_TO_UNIFIED``)
    2. arXiv category code mapping (``_ARXIV_TO_UNIFIED``)
    3. Title/abstract keyword matching (``_TITLE_KEYWORDS``)

    Returns a list of dicts ``{slug, confidence, reason}``.
    """
    assigned: Dict[str, dict] = {}

    cats = paper.categories or []
    title_abs = " ".join(
        x for x in (paper.title, paper.abstract) if x
    ).lower()

    # ── Step 1: OpenAlex topic name exact match ─────────────────────────
    for cat in cats:
        unified = _OPENALEX_TO_UNIFIED.get(cat)
        if unified:
            assigned[unified] = {
                "slug": unified,
                "confidence": 0.85,
                "reason": f"OpenAlex topic: {cat}",
            }

    # ── Step 2: arXiv category mapping ──────────────────────────────────
    for cat in cats:
        unified = _ARXIV_TO_UNIFIED.get(cat)
        if unified and unified not in assigned:
            assigned[unified] = {
                "slug": unified,
                "confidence": 0.85,
                "reason": f"arXiv category: {cat}",
            }

    # ── Step 3: title/abstract keyword matching ─────────────────────────
    for unified_id, keywords in _TITLE_KEYWORDS.items():
        if unified_id in assigned:
            continue
        for kw in keywords:
            if kw in title_abs:
                assigned[unified_id] = {
                    "slug": unified_id,
                    "confidence": 0.7,
                    "reason": f"keyword: {kw}",
                }
                break

    # ── Fallback: no topics matched → "其他"
    if not assigned:
        assigned["other"] = {
            "slug": "other",
            "confidence": 0.5,
            "reason": "兜底分类：未命中任何专项分类",
        }

    return list(assigned.values())
