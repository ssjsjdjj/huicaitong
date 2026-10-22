# 第三方组件与参考

- 核心 Web 应用使用 Python 标准库与原创 HTML / CSS / JavaScript，没有打包第三方前端资源。
- 杭州官方政策资料的来源及整理范围见 `docs/SOURCES.md`；项目未冒充政府官方服务。
- 可选模型为 [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)，模型仓库标注 Apache-2.0。原模型权重不包含在源码压缩包中，使用和分发模型及适配器时应遵守上游许可证。
- 可选训练组件包括 PyTorch、Transformers、TRL、PEFT、Datasets 与 Accelerate，分别遵循其上游许可。依赖安装在独立实验环境，源码压缩包不分发这些库的二进制文件。
- 方法参考 [Search-R1](https://arxiv.org/abs/2503.09516) 与 [TRL GRPO 文档](https://huggingface.co/docs/trl/v0.29.1/en/grpo_trainer)。本项目首版是给定证据的结构化核验，不宣称实现或改进 Search-R1 的多轮搜索算法。

- 可选材料组件 pypdf 6.10.0 使用上游 BSD-3-Clause 许可，安装在独立环境，源码包不分发该库。合成 PDF 样例使用 ReportLab 制作，运行时不需要 ReportLab。
- 可选 Windows OCR 调用 Windows.Media.Ocr 本机 API，不涉及云识别；当前机器的脚本策略使该路径不可用，未改变系统设置。
# 随附许可文本

`docs/QWEN_LICENSE.txt` 为本次下载的 Qwen2.5-0.5B-Instruct 上游 Apache License 2.0 原文，适用于该上游模型的相关材料；本项目的 SFT / GRPO LoRA 适配器由合成弱监督任务训练产生，基础模型权重不包含在仓库中。本许可副本不为本项目的其他原创代码另行指定许可证。

