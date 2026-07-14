---
layout: default
title: "Horizon Summary: 2026-07-14 (EN)"
date: 2026-07-14
lang: en
---

> From 16 items, 1 important content pieces were selected

---

1. [Apple's SpeechAnalyzer API beats Whisper Small in benchmark](#item-1) ⭐️ 9.0/10

---

<a id="item-1"></a>
## [Apple's SpeechAnalyzer API beats Whisper Small in benchmark](https://get-inscribe.com/blog/apple-speech-api-benchmark.html) ⭐️ 9.0/10

Apple's new SpeechAnalyzer API achieved a word error rate (WER) of 2.12% on LibriSpeech test-clean and 4.56% on test-other, outperforming both Whisper Small (8.9% and 10.16%) and the legacy SFSpeechRecognizer (9.02% and 16.25%), while running about three times faster than Whisper Small. This is the first independent benchmark comparing Apple's new on-device speech API with Whisper, revealing that Apple's engine is now the most accurate and fastest option for English transcription on Apple hardware. It directly impacts iOS/macOS developers deciding whether to migrate and changes the competitive landscape for on-device ASR. The benchmark used the LibriSpeech dataset (test-clean and test-other) on an Apple M2 Pro (32GB, macOS 26.5.1), running all engines fully on-device. The Whisper results reproduced OpenAI's published WER with a small offset due to stricter text normalization and CoreML quantization. SpeechAnalyzer is part of iOS 26/macOS 26, replacing SFSpeechRecognizer, and currently supports around 30 locales.
> **Reason**: 首个独立基准测试，对比了苹果新API、Whisper和旧API，提供了详细的WER和速度数据，对开发者选择有重要参考价值，Hacker News上讨论热烈。

hackernews · get-inscribe · Jul 13, 16:06 · [Discussion](https://news.ycombinator.com/item?id=48894752)

---