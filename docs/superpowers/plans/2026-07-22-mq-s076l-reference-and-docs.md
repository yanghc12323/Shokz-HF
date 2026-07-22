# MQ_S076L 固定参考耳与文档校正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将正式固定参考耳从 `MQ_S068L` 统一校正为 `MQ_S076L`，并让可执行文档与历史记录清楚分界。

**Architecture:** 默认目录令牌集中在 `ear_param.run_artifacts`，CLI 和桌面端仅显示该业务规则。现行使用文档采用相同的命令和目录示例；旧数据集 `T076_L` 的结果保留，并添加历史验证语境。

**Tech Stack:** Python 3、pytest、PySide6、Markdown、Git。

## Global Constraints

- 当前正式固定参考耳为 `MQ_S076L`。
- 固定参考耳命令必须使用 `--alignment-mode fixed-reference --reference-sample MQ_S076L`。
- GPA 路线不传 `--reference-sample`。
- 不改动刚性配准算法、MQ/T 输入匹配或并行 Remesh/QC 逻辑。
- 不提交本地 PLY 删除、PPT、输出目录或 `modules/`。

---

### Task 1: 默认参考耳令牌与界面/CLI 提示

**Files:**
- Modify: `tests/test_run_artifacts.py:63-64`
- Modify: `ear_param/run_artifacts.py:11`
- Modify: `scripts/run_full_pipeline.py:77-79`
- Modify: `desktop_app/ui/project_wizard.py:303-305`

**Interfaces:**
- Consumes: `PipelineOutputLayout.from_output_root(root, reference_sample=None)`。
- Produces: 默认目录 `aligned_reference_MQ_S076L` 与 `pca_reference_MQ_S076L_r24`；CLI/UI 显示当前参考耳。

- [ ] **Step 1: 写入失败测试**

将 `tests/test_run_artifacts.py` 中默认目录断言改为：

```python
assert layout.reference_aligned_dir == root / "whole_ear_r24" / "aligned_reference_MQ_S076L"
assert layout.reference_pca_dir == root / "pca_reference_MQ_S076L_r24"
```

- [ ] **Step 2: 验证测试失败**

运行：

```powershell
pytest -q tests/test_run_artifacts.py
```

预期：`test_pipeline_output_layout_maps_every_stage_under_one_root` 因仍输出 `MQ_S068L` 失败。

- [ ] **Step 3: 最小实现**

将 `ear_param/run_artifacts.py` 中的常量改为：

```python
_DEFAULT_REFERENCE_SAMPLE = "MQ_S076L"
```

同步将 CLI help 改为：

```python
help="Fixed-reference ear tag; the current designated reference is MQ_S076L."
```

并把桌面端占位文本更新为：

```python
self.reference_sample.setPlaceholderText("例如 MQ_S076L（当前固定参考耳）")
```

- [ ] **Step 4: 验证通过**

运行：

```powershell
pytest -q tests/test_run_artifacts.py
$env:QT_QPA_PLATFORM='offscreen'; pytest -q tests/test_desktop_ui_flow.py
python scripts\run_full_pipeline.py --help
```

预期：测试全部通过；帮助文本包含 `MQ_S076L`。

- [ ] **Step 5: 提交代码和测试**

```powershell
git add tests/test_run_artifacts.py ear_param/run_artifacts.py scripts/run_full_pipeline.py desktop_app/ui/project_wizard.py
git commit -m "fix: set MQ_S076L as fixed reference"
```

### Task 2: 现行操作文档与历史说明

**Files:**
- Modify: `README.md:426-545`
- Modify: `docs/W2 Remesh 使用说明.md:60-95`
- Modify: `docs/W3 PCA 与平均耳技术路线.md:11-221`
- Modify: `docs/整耳全局模板、边界焊接与刚体统一坐标系.md:30-101`
- Modify: `docs/桌面工程软件使用说明.md:156,266`
- Modify: `docs/GPA与T076固定参考耳PCA对比.md:1-14`

**Interfaces:**
- Consumes: 当前 CLI 参数与 Task 1 的默认目录命名。
- Produces: 可复制的 `MQ_S076L` 正式命令；标明 `T076_L` 是历史验证数据。

- [ ] **Step 1: 写入文档验收检查**

使用全文检索作为可重复检查：

```powershell
rg -n "MQ_S068L" README.md docs ear_param scripts desktop_app tests -g "!docs/archive/**" -g "!docs/superpowers/**"
```

预期：修改前仍能找到现行规则中的 `MQ_S068L`。

- [ ] **Step 2: 更新现行命令和目录**

将每份现行文档中的固定参考耳命令统一为：

```powershell
--parallel-workers 4 --alignment-mode fixed-reference --reference-sample MQ_S076L
```

将目录示例统一为：

```text
aligned_reference_MQ_S076L/
pca_reference_MQ_S076L_r24/
```

README 同时保留 GPA 使用说明：`--alignment-mode gpa` 且不传 `--reference-sample`。

- [ ] **Step 3: 标注历史记录**

在旧 `T076_L` PCA 对比文档和仍保留的旧结果段落前加上明确说明：

```markdown
> 历史验证记录：本节使用旧数据集标签 `T076_L`，仅用于保留当时的对齐/PCA 证据；不代表当前正式固定参考耳。
```

- [ ] **Step 4: 验证文档一致性**

运行：

```powershell
rg -n "MQ_S068L" README.md docs ear_param scripts desktop_app tests -g "!docs/archive/**" -g "!docs/superpowers/**"
rg -n "当前正式参考耳|当前正式全流程|当前固定参考耳" README.md docs -g "!docs/archive/**" -g "!docs/superpowers/**"
git diff --check
```

预期：第一条无输出；第二条仅展示 `MQ_S076L` 规则；格式检查退出码为 0。

- [ ] **Step 5: 提交文档**

```powershell
git add README.md "docs/W2 Remesh 使用说明.md" "docs/W3 PCA 与平均耳技术路线.md" "docs/整耳全局模板、边界焊接与刚体统一坐标系.md" "docs/桌面工程软件使用说明.md" "docs/GPA与T076固定参考耳PCA对比.md"
git commit -m "docs: refresh MQ_S076L operating guidance"
```

### Task 3: 集成验证与发布

**Files:**
- Verify only: `tests/test_run_artifacts.py`
- Verify only: `tests/test_pipeline.py`
- Verify only: `tests/test_run_manifest.py`
- Verify only: `tests/test_desktop_ui_flow.py`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的已提交改动。
- Produces: 已验证、可推送的 `master`。

- [ ] **Step 1: 验证 CLI 配置构造**

运行：

```powershell
@'
from scripts.run_full_pipeline import build_parser, build_pipeline_config
args = build_parser().parse_args([
    '--parallel-workers', '4', '--alignment-mode', 'fixed-reference',
    '--reference-sample', 'MQ_S076L', '--output-root', 'C:/Temp/shokz_cli_check',
])
config, _, _ = build_pipeline_config(args)
assert config.parallel_workers == 4
assert config.alignment_mode == 'fixed-reference'
assert config.reference_sample == 'MQ_S076L'
print('CLI_CONFIG_OK')
'@ | python -
```

预期：输出 `CLI_CONFIG_OK`。

- [ ] **Step 2: 运行定向回归测试**

运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest -q tests/test_run_artifacts.py tests/test_run_manifest.py tests/test_desktop_ui_flow.py
pytest -q tests/test_pipeline.py -k "full_pipeline_output_root_scopes_every_stage"
```

预期：全部通过。

- [ ] **Step 3: 检查提交范围并推送**

运行：

```powershell
git status --short
git log --oneline -4
git push origin master
```

预期：仅保留先前存在的本地无关变更；`master` 推送成功。
