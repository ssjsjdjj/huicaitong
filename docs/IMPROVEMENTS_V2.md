# 第二轮改进记录

日期：2026-10-21。研究设备沿用 RTX 4060 8GB。本轮没有接入新的政策来源，也没有把规则结论传给独立模型。

## 应用变化

- 将待补充字段跨事项合并，按影响的事项数量排序。点击字段可打开对应折叠区并定位输入框。已存在明确不满足条件或已超出自动覆盖范围的事项不再重复追问。
- 增加申请时间轴：毕业两年边界、按所填连续参保起算月推算的月末节点与首笔申领月份。未知或不支持的学历范围不直接显示自动期限。推算日期不代表实际已缴满、获批或发放。
- 独立模型返回后，对结论、决定性引用、缺失字段与准备清单进行显式对照。差异与原始输出并列保留，规则参考不覆盖模型输出；此对照不校验解释文字，也不等于官方资格核验。
- 修改表单后，旧结果标记为过期，暂时禁用模型调用和导出。重新初筛后恢复。模型结果及对照记录纳入当前报告导出，不写入服务器数据库。

## 先诊断，再训练

原平衡 GRPO 模型在完整 92 条开发验证上，与程序弱标签一致 61 条，结构字段完全一致 35 条。模型判为 eligible 的 36 条中，只有 12 条与程序参考一致；第一笔事项为 18/46，第二笔为 43/46。只看早先 12 条样本的 9/12 会高估效果。

新的评测脚本保存逐类精确率、召回率、混淆矩阵、按政策结果、错误类型和逐条诊断。缺失预测及无效结构保留为错误。结构完全一致只比较结论、引用、缺失字段与准备清单，不评价解释文字。

## 训练集内单字段对照

仅从原生活补贴训练分割构造候选样本：在条件满足的申请人上改变一个字段，例如社保月数、当前参保、领取记录或单位条件。标签仍由规则生成，解释指出可见的核对条件和引用，不提供隐藏推理过程。

每个政策、每个结论类别抽取 64 条，共 384 条，包含 302 条不同政策任务。少数类重复抽样已明确记录，不能把 384 条当成 384 个独立申请人。按人物条件排除与原开发验证相同的样本，重叠为 0。租房文件族不进入训练。清单与散列在 `data/generated/counterfactual_manifest.json`。

SFT 使用 500 步，随后从同一 SFT 权重进行 20 步 GRPO。它与旧版本同时改变了样本、解释目标、随机种子和训练步数，因此版本间改善不能单独归因于其中某一项；判断 GRPO 额外收益应比较本轮 SFT 与本轮 GRPO。

## 预先固定后续检查

从 240 条租房弱标签任务中排除首轮已预测的 12 条，在余下 228 条中按 `sha256('huicaitong-v2-freeze:'+case_id)` 排序，取前 48 条。抽样只看编号，不按标签挑选，文件与散列在 `test_v2_unseen_grpo.manifest.json`。

默认模型按全部 92 条开发集的结构完全一致率选择，其次比较结论一致率，完全相同时优先 SFT。先冻结模型权重散列，再预测上述 48 条，不根据这次结果继续调参。这仍是少量同程序弱标签的诊断，不是人工政策基准，也不是完整 240 条测试集结果。

## 复现

先安装并启用 README 中的独立训练环境，将 `--model` 替换为已校验的本地基础模型目录：

```powershell
python -m training.build_counterfactual
python -m training.train sft --config training/config-counterfactual.json --data data/generated/train_counterfactual_sft.jsonl --model 本地基础模型目录 --output checkpoints/sft-counterfactual --max-steps 500
python -m training.train grpo --config training/config-counterfactual.json --data data/generated/train_counterfactual_grpo.jsonl --model 本地基础模型目录 --sft-adapter checkpoints/sft-counterfactual --output checkpoints/grpo-counterfactual --max-steps 20
python -m training.predict --data data/generated/validation_grpo.jsonl --model 本地基础模型目录 --adapter checkpoints/sft-counterfactual --output training-runs/sft-counterfactual-development.jsonl
python -m training.evaluate --gold training-runs/sft-counterfactual-development.gold.jsonl --predictions training-runs/sft-counterfactual-development.jsonl --output training-runs/sft-counterfactual-development-evaluation.json
```

GRPO 的预测与评测同理，更换适配器和输出文件名即可。实际预测、参考任务、范围元数据、权重和输入散列会随源码保存。选择记录为 `checkpoints/selection.json`，启动器会核对权重散列；文件缺失或不匹配时可继续运行规则版。

## 实际结果与默认版本

| 模型 | 全部开发集结论一致 | 结构完全一致 | 有效结构 |
|---|---:|---:|---:|
| 原平衡 GRPO | 61/92 | 35/92 | 91/92 |
| 本轮单字段对照 SFT 500 步 | 35/92 | 13/92 | 92/92 |
| 本轮 SFT 后 GRPO 20 步 | 35/92 | 13/92 | 92/92 |

本轮候选未带来改善，GRPO 也未增加本轮 SFT 的结论或结构完全一致数量。默认保留原平衡 GRPO，名称为 `huicaitong-grpo-balanced-v1`。训练步数增加、训练损失下降和非零奖励信号均不能替代评测。新候选权重和负面结果完整保留，不覆盖原模型。

默认模型先冻结，再运行预先选定的 48 条租房任务：结论一致 **22/48**、结构完全一致 **1/48**、有效结构 **48/48**。其中 7 条弱标签通过样本均未被正确识别，15 条信息不足样本仅正确识别 1 条。跨政策能力明显不足；没有根据这次结果继续调参。这与首轮 5/12 是不同子集，不能直接当成提升对照。

本轮 SFT 实际峰值已分配显存 2.938 GiB、500 步均有非零梯度；GRPO 为 1.328 GiB，20 步中 9 步有非零梯度与组内奖励差异。

## 应用核对验证

59 项 Python 自动测试通过，JavaScript 语法检查通过。浏览器验证了缺失信息定位、修改后禁用旧报告、时间轴、训练诊断表及真实模型冲突提示。

真实本机模型调用使用合成“本次学历已领取首笔”的案例：规则参考为不满足，原模型仍输出 eligible。网关保留原始结果，另返回 needs_review 和结论冲突、引用与准备清单差异，界面显示“需复核”。原始请求条件与响应保存在 `training-runs/runtime-audit-example.json`。这是与本地规则的对照演示，不是独立政策正确率验证。

第二轮增加了核对闭环和可追溯诊断，没有宣称训练改善了政策判断能力。当前适合比赛原型演示与实验分析，模型不能替代受理系统判断资格。
