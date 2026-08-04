"""Fixed v1 seed list for the classic AI papers library.

Deliberately hardcoded, not configurable and not auto-discovered: v1 is a
human-curated list of ~50 papers, grouped into 8 categories. The pipeline's
only job is to look each of these up against OpenAlex (falling back to other
sources for missing fields, see `src.papers.enrichment`) — never to expand,
re-rank, or otherwise decide what belongs on this list. Auto-discovery is
explicitly out of scope for v1.

``expected_year`` is the canonical publication year of the work we are
curating. When a seed also has ``openalex_id_override``, the override is used
to identify the OpenAlex record, but the seed's ``canonical_*`` fields always
take precedence over whatever OpenAlex returns — so e.g. AlexNet is displayed
as NIPS 2012 even when the OpenAlex record points to the 2017 CACM reprint.

``canonical_doi`` is the DOI of the *original* canonical version.
``reprint_doi`` is the DOI of a later reprint (e.g. CACM 2017 for AlexNet)
which is recorded for provenance but never displayed as the primary identifier.
"""

from typing import List, Optional

from pydantic import BaseModel

CATEGORY_MACHINE_LEARNING = "Machine Learning"
CATEGORY_DEEP_LEARNING = "Deep Learning"
CATEGORY_COMPUTER_VISION = "Computer Vision"
CATEGORY_NLP_LLM = "NLP & LLM"
CATEGORY_GENERATIVE_MODELS = "Generative Models"
CATEGORY_REINFORCEMENT_LEARNING = "Reinforcement Learning"
CATEGORY_GRAPH_LEARNING_RETRIEVAL = "Graph Learning & Retrieval"
CATEGORY_AI_SYSTEMS = "AI Systems"

CATEGORIES = [
    CATEGORY_MACHINE_LEARNING,
    CATEGORY_DEEP_LEARNING,
    CATEGORY_COMPUTER_VISION,
    CATEGORY_NLP_LLM,
    CATEGORY_GENERATIVE_MODELS,
    CATEGORY_REINFORCEMENT_LEARNING,
    CATEGORY_GRAPH_LEARNING_RETRIEVAL,
    CATEGORY_AI_SYSTEMS,
]


class SeedPaper(BaseModel):
    """One entry on the fixed v1 seed list.

    Matching fields (used to locate the right OpenAlex record):

    * ``openalex_id_override`` — pin to a specific OpenAlex work id
    * ``doi`` — DOI for OpenAlex lookup (may be canonical or reprint)
    * ``arxiv_id`` — arXiv identifier for lookup

    Canonical fields (human-curated; override OpenAlex metadata):

    * ``canonical_title`` — the canonical display title
    * ``canonical_year`` — the canonical publication year
    * ``canonical_venue`` — the canonical venue/journal/conference name
    * ``canonical_doi`` — DOI of the original canonical version
    * ``canonical_authors`` — canonical author list (ordered)
    * ``reprint_doi`` — DOI of a later reprint version (never the primary DOI)
    * ``source_version_type`` — "original" | "journal_version" | "reprint" | "preprint"
    """

    category: str
    title: str
    expected_year: int
    # Matching identifiers
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    openalex_id_override: Optional[str] = None
    # Canonical metadata — when set, always wins over API-fetched values
    canonical_title: Optional[str] = None
    canonical_year: Optional[int] = None
    canonical_venue: Optional[str] = None
    canonical_doi: Optional[str] = None
    canonical_authors: Optional[List[str]] = None
    reprint_doi: Optional[str] = None
    source_version_type: Optional[str] = None  # "original" | "journal_version" | "reprint" | "preprint"


SEED_PAPERS: List[SeedPaper] = [
    # -- Machine Learning ---------------------------------------------------
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="Support-Vector Networks",
        expected_year=1995,
        canonical_venue="Machine Learning",
    ),
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="Bagging Predictors",
        expected_year=1996,
        canonical_venue="Machine Learning",
    ),
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting",
        expected_year=1997,
        openalex_id_override="W1988790447",
        doi="10.1006/jcss.1997.1504",
        canonical_year=1997,
        canonical_venue="Journal of Computer and System Sciences",
        canonical_doi="10.1006/jcss.1997.1504",
        canonical_authors=["Yoav Freund", "Robert E. Schapire"],
        source_version_type="original",
    ),
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="Random Forests",
        expected_year=2001,
        openalex_id_override="W2911964244",
        doi="10.1023/A:1010933404324",
        canonical_year=2001,
        canonical_venue="Machine Learning",
        canonical_doi="10.1023/A:1010933404324",
        canonical_authors=["Leo Breiman"],
        source_version_type="original",
    ),
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="Adam: A Method for Stochastic Optimization",
        expected_year=2015,
        arxiv_id="1412.6980",
        canonical_venue="International Conference on Learning Representations (ICLR 2015)",
    ),
    SeedPaper(
        category=CATEGORY_MACHINE_LEARNING,
        title="XGBoost: A Scalable Tree Boosting System",
        expected_year=2016,
        doi="10.1145/2939672.2939785",
        arxiv_id="1603.02754",
        canonical_venue="Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD 2016)",
    ),
    # -- Deep Learning --------------------------------------------------------
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Learning representations by back-propagating errors",
        expected_year=1986,
        openalex_id_override="W1498436455",
        doi="10.1038/323533a0",
        canonical_title="Learning representations by back-propagating errors",
        canonical_year=1986,
        canonical_venue="Nature",
        canonical_doi="10.1038/323533a0",
        canonical_authors=["David E. Rumelhart", "Geoffrey E. Hinton", "Ronald J. Williams"],
        source_version_type="original",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Long Short-Term Memory",
        expected_year=1997,
        openalex_id_override="W2064675550",
        doi="10.1162/neco.1997.9.8.1735",
        canonical_year=1997,
        canonical_venue="Neural Computation",
        canonical_doi="10.1162/neco.1997.9.8.1735",
        canonical_authors=["Sepp Hochreiter", "Jürgen Schmidhuber"],
        source_version_type="original",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Gradient-Based Learning Applied to Document Recognition",
        expected_year=1998,
        openalex_id_override="W2112796928",
        doi="10.1109/5.726791",
        canonical_year=1998,
        canonical_venue="Proceedings of the IEEE",
        canonical_doi="10.1109/5.726791",
        canonical_authors=["Yann LeCun", "Léon Bottou", "Yoshua Bengio", "Patrick Haffner"],
        source_version_type="original",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="A Fast Learning Algorithm for Deep Belief Nets",
        expected_year=2006,
        canonical_venue="Neural Computation",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Understanding the difficulty of training deep feedforward neural networks",
        expected_year=2010,
        canonical_venue="Proceedings of the Thirteenth International Conference on Artificial Intelligence and Statistics (AISTATS 2010)",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Deep Sparse Rectifier Neural Networks",
        expected_year=2011,
        canonical_venue="Proceedings of the Fourteenth International Conference on Artificial Intelligence and Statistics (AISTATS 2011)",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Dropout: A Simple Way to Prevent Neural Networks from Overfitting",
        expected_year=2014,
        arxiv_id="1207.0580",
        canonical_venue="Journal of Machine Learning Research (JMLR)",
    ),
    SeedPaper(
        category=CATEGORY_DEEP_LEARNING,
        title="Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift",
        expected_year=2015,
        arxiv_id="1502.03167",
        canonical_venue="International Conference on Machine Learning (ICML 2015)",
    ),
    # -- Computer Vision --------------------------------------------------
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="ImageNet Classification with Deep Convolutional Neural Networks",
        expected_year=2012,
        openalex_id_override="W2163605009",
        # The OpenAlex record W2163605009 is the 2017 CACM reprint of the NIPS 2012
        # original. The canonical metadata reflects the NIPS 2012 version.
        # 10.1145/3065386 is the reprint DOI — it is stored as reprint_doi, not
        # canonical_doi, so it is never used as the primary identifier.
        canonical_year=2012,
        canonical_venue="Advances in Neural Information Processing Systems 25 (NIPS 2012)",
        canonical_authors=["Alex Krizhevsky", "Ilya Sutskever", "Geoffrey E. Hinton"],
        reprint_doi="10.1145/3065386",
        source_version_type="reprint",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="Rich Feature Hierarchies for Accurate Object Detection and Semantic Segmentation",
        expected_year=2014,
        arxiv_id="1311.2524",
        canonical_venue="Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR 2014)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="Fully Convolutional Networks for Semantic Segmentation",
        expected_year=2015,
        arxiv_id="1411.4038",
        canonical_venue="Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR 2015)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks",
        expected_year=2015,
        arxiv_id="1506.01497",
        canonical_venue="Advances in Neural Information Processing Systems 28 (NIPS 2015)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="U-Net: Convolutional Networks for Biomedical Image Segmentation",
        expected_year=2015,
        arxiv_id="1505.04597",
        canonical_venue="International Conference on Medical Image Computing and Computer-Assisted Intervention (MICCAI 2015)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="Deep Residual Learning for Image Recognition",
        expected_year=2015,
        arxiv_id="1512.03385",
        canonical_venue="Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR 2016)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="You Only Look Once: Unified, Real-Time Object Detection",
        expected_year=2016,
        arxiv_id="1506.02640",
        canonical_venue="Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR 2016)",
    ),
    SeedPaper(
        category=CATEGORY_COMPUTER_VISION,
        title="An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        expected_year=2020,
        arxiv_id="2010.11929",
        canonical_venue="International Conference on Learning Representations (ICLR 2021)",
    ),
    # -- NLP & Large Language Models ---------------------------------------
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Efficient Estimation of Word Representations in Vector Space",
        expected_year=2013,
        arxiv_id="1301.3781",
        canonical_venue="International Conference on Learning Representations (ICLR 2013)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="GloVe: Global Vectors for Word Representation",
        expected_year=2014,
        canonical_venue="Proceedings of the 2014 Conference on Empirical Methods in Natural Language Processing (EMNLP 2014)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Sequence to Sequence Learning with Neural Networks",
        expected_year=2014,
        arxiv_id="1409.3215",
        canonical_venue="Advances in Neural Information Processing Systems 27 (NIPS 2014)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Neural Machine Translation by Jointly Learning to Align and Translate",
        expected_year=2014,
        arxiv_id="1409.0473",
        canonical_venue="International Conference on Learning Representations (ICLR 2015)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Attention Is All You Need",
        expected_year=2017,
        arxiv_id="1706.03762",
        canonical_venue="Advances in Neural Information Processing Systems 30 (NIPS 2017)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        expected_year=2018,
        arxiv_id="1810.04805",
        canonical_venue="Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (NAACL-HLT 2019)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer",
        expected_year=2019,
        arxiv_id="1910.10683",
        canonical_venue="Journal of Machine Learning Research (JMLR)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Language Models are Few-Shot Learners",
        expected_year=2020,
        arxiv_id="2005.14165",
        canonical_venue="Advances in Neural Information Processing Systems 33 (NeurIPS 2020)",
    ),
    # -- Generative Models --------------------------------------------------
    SeedPaper(
        category=CATEGORY_GENERATIVE_MODELS,
        title="Auto-Encoding Variational Bayes",
        expected_year=2013,
        arxiv_id="1312.6114",
        canonical_venue="International Conference on Learning Representations (ICLR 2014)",
    ),
    SeedPaper(
        category=CATEGORY_GENERATIVE_MODELS,
        title="Generative Adversarial Nets",
        expected_year=2014,
        arxiv_id="1406.2661",
        canonical_venue="Advances in Neural Information Processing Systems 27 (NIPS 2014)",
    ),
    SeedPaper(
        category=CATEGORY_GENERATIVE_MODELS,
        title="Wasserstein GAN",
        expected_year=2017,
        arxiv_id="1701.07875",
        canonical_venue="International Conference on Machine Learning (ICML 2017)",
    ),
    SeedPaper(
        category=CATEGORY_GENERATIVE_MODELS,
        title="Neural Discrete Representation Learning",
        expected_year=2017,
        arxiv_id="1711.00937",
        canonical_venue="Advances in Neural Information Processing Systems 30 (NIPS 2017)",
    ),
    SeedPaper(
        category=CATEGORY_GENERATIVE_MODELS,
        title="Denoising Diffusion Probabilistic Models",
        expected_year=2020,
        arxiv_id="2006.11239",
        canonical_venue="Advances in Neural Information Processing Systems 33 (NeurIPS 2020)",
    ),
    # -- Reinforcement Learning ----------------------------------------------
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Human-level control through deep reinforcement learning",
        expected_year=2015,
        canonical_venue="Nature",
    ),
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Trust Region Policy Optimization",
        expected_year=2015,
        arxiv_id="1502.05477",
        canonical_venue="International Conference on Machine Learning (ICML 2015)",
    ),
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Asynchronous Methods for Deep Reinforcement Learning",
        expected_year=2016,
        arxiv_id="1602.01783",
        canonical_venue="International Conference on Machine Learning (ICML 2016)",
    ),
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Mastering the game of Go with deep neural networks and tree search",
        expected_year=2016,
        canonical_venue="Nature",
    ),
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Proximal Policy Optimization Algorithms",
        expected_year=2017,
        arxiv_id="1707.06347",
    ),
    SeedPaper(
        category=CATEGORY_REINFORCEMENT_LEARNING,
        title="Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor",
        expected_year=2018,
        arxiv_id="1801.01290",
        canonical_venue="International Conference on Machine Learning (ICML 2018)",
    ),
    # -- Graph Learning & Retrieval -------------------------------------------
    SeedPaper(
        category=CATEGORY_GRAPH_LEARNING_RETRIEVAL,
        title="DeepWalk",
        expected_year=2014,
        canonical_venue="Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD 2014)",
    ),
    SeedPaper(
        category=CATEGORY_GRAPH_LEARNING_RETRIEVAL,
        title="node2vec",
        expected_year=2016,
        canonical_venue="Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD 2016)",
    ),
    SeedPaper(
        category=CATEGORY_GRAPH_LEARNING_RETRIEVAL,
        title="Semi-Supervised Classification with Graph Convolutional Networks",
        expected_year=2016,
        arxiv_id="1609.02907",
        canonical_venue="International Conference on Learning Representations (ICLR 2017)",
    ),
    SeedPaper(
        category=CATEGORY_GRAPH_LEARNING_RETRIEVAL,
        title="Dense Passage Retrieval for Open-Domain Question Answering",
        expected_year=2020,
        arxiv_id="2004.04906",
        canonical_venue="Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing (EMNLP 2020)",
    ),
    # -- AI Systems ------------------------------------------------------------
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="Distilling the Knowledge in a Neural Network",
        expected_year=2015,
        arxiv_id="1503.02531",
        canonical_venue="Deep Learning and Representation Learning Workshop: NIPS 2014",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="TensorFlow: A System for Large-Scale Machine Learning",
        expected_year=2016,
        arxiv_id="1605.08695",
        canonical_venue="Proceedings of the 12th USENIX Symposium on Operating Systems Design and Implementation (OSDI 2016)",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="TVM: An Automated End-to-End Optimizing Compiler for Deep Learning",
        expected_year=2018,
        arxiv_id="1802.04799",
        canonical_venue="Proceedings of the 13th USENIX Symposium on Operating Systems Design and Implementation (OSDI 2018)",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism",
        expected_year=2019,
        arxiv_id="1909.08053",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="ZeRO: Memory Optimizations Toward Training Trillion Parameter Models",
        expected_year=2020,
        arxiv_id="1910.02054",
        canonical_venue="Proceedings of the International Conference for High Performance Computing, Networking, Storage and Analysis (SC 2020)",
    ),
    # -- LLM 时代（2022–2025）-------------------------------------------
    # v2 增补：LLM 基础模型、推理与智能体方法、训练与评估系统。
    # 有正式会议接收的论文带 canonical_venue；纯 arXiv 论文不设，由
    # OpenAlex 返回 arXiv 作为 venue。
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="ReAct: Synergizing Reasoning and Acting in Language Models",
        expected_year=2022,
        arxiv_id="2210.03629",
        canonical_venue="International Conference on Learning Representations (ICLR 2023)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="LLaMA: Open and Efficient Foundation Language Models",
        expected_year=2023,
        arxiv_id="2302.13971",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Tree of Thoughts: Deliberate Problem Solving with Large Language Models",
        expected_year=2023,
        arxiv_id="2305.10601",
        canonical_venue="Advances in Neural Information Processing Systems 36 (NeurIPS 2023)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Let's Verify Step by Step: Step-Level Verification of LLMs",
        expected_year=2023,
        arxiv_id="2305.20050",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        expected_year=2023,
        arxiv_id="2310.11511",
        canonical_venue="International Conference on Learning Representations (ICLR 2024)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Visual Instruction Tuning",
        expected_year=2023,
        arxiv_id="2304.08485",
        canonical_venue="Advances in Neural Information Processing Systems 36 (NeurIPS 2023)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Generative Agents: Interactive Simulacra of Human Behavior",
        expected_year=2023,
        arxiv_id="2304.03442",
        canonical_venue="Proceedings of the 36th Annual ACM Symposium on User Interface Software and Technology (UIST 2023)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Llama 2: Open Foundation and Fine-Tuned Chat Models",
        expected_year=2023,
        arxiv_id="2307.09288",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Mistral 7B",
        expected_year=2023,
        arxiv_id="2310.06825",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="QLoRA: Efficient Finetuning of Quantized Large Language Models",
        expected_year=2023,
        arxiv_id="2305.14314",
        canonical_venue="Advances in Neural Information Processing Systems 36 (NeurIPS 2023)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="Mixtral of Experts",
        expected_year=2024,
        arxiv_id="2401.04088",
    ),
    SeedPaper(
        category=CATEGORY_AI_SYSTEMS,
        title="SWE-bench: Can Language Models Resolve Real-World GitHub Issues?",
        expected_year=2024,
        arxiv_id="2310.06770",
        canonical_venue="International Conference on Learning Representations (ICLR 2024)",
    ),
    SeedPaper(
        category=CATEGORY_NLP_LLM,
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        expected_year=2025,
        # OpenAlex has no usable arXiv-DOI record for 2501.12948, but it does
        # index the Nature 2025 published version — pin to that, canonical fields
        # keep the arXiv-era title as the display title.
        openalex_id_override="W4414281281",
        arxiv_id="2501.12948",
        canonical_title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        canonical_venue="Nature",
    ),
]
