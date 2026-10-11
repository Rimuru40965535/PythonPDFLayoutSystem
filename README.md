# PythonPDFLayoutSystem

利用 fpdf2 库实现 PDF 文件的排版喵~  

是对已有库的重构喵~  

---
---

## 如何使用？

现在项目处于开发阶段，预期的使用方式有两种：

- 开发者将这个库下载下来，并在源文件中import
- 源文件读取排版文档组和 .md 文件（或者其它通用格式）的文本文档，自动排版

---
---

## 开发日志

### 2026-10-11

#### **20：52** 

第一次提交

- 建立 main 并测试 fpdf2 库引用
- 建立资源和模块文件夹

---

### 2026-10-12

#### **批次 0：修复阻断性缺陷 + 建立技术文档**

> 待提交（内容已在暂存区）。本次提交的内容简述如下。

**新增技术文档**

- `TECHNICAL.md`：完整 API 参考（函数签名 / 参数 / 返回值）、分层结构、依赖图、
  坐标系与三层缓存机制、命名约定、**18 条已知缺陷**、10 个重构方向与 6 个批次划分、
  测试入口说明。
- 顺带记录：`Resources/` 实际只有 6 个字体文件，代码引用的 11 个图标/照片**全部不存在**；
  图片缺失时引擎静默降级，所以 PDF 能生成但看不到图标 —— 排查视觉问题前必须先确认这一点。

**修复的缺陷**（`ResumeCore.py`）

- **导入断裂（阻断级）**：`from ResumeTemplateV2` → `from ResumeTemplate`。
  该导入此前直接抛 `ModuleNotFoundError`，`Resume.Generate` 完全不可用。
- **`SkillsAwards.get_char_*` 末尾多余换行**：三个方法的 `if i < len(...)` 恒为真，
  改为 `'\n'.join(...)`。
- **联系方式模板重复挂载**：`generate_profile_template` 内部已挂载，
  外层循环又调了一次 `root.add_child(a)`，导致每条联系方式占两段纵向空间。
  左栏内容高度由约 108mm 回落到 90mm。
- **联系方式末尾多一个间距**：`if i == len(contacts_text)` 恒为假（死代码），
  改为 `len(contacts_text) - 1`，去掉末条下方多余的 5mm 间距。

**清理**

- 删除死目录 `Module_PythonPDFLayoutSystem/`（仅含已无源码的历史 `.pyc`）。

**测试**

- 三个测试入口（`LayoutEngine.py` / `ResumeTemplate.py` / `ResumeCore.py`）均加入回归契约断言，
  全部退出码 0。
- 建立 PDF 规范化比对基线：剥离 `CreationDate` / `ModDate` / `ID` / `Producer` 后，
  `test_layout_engine_cached.pdf` 与 `resume_template_v2_test.pdf` **逐字节未变**，
  `output/利姆露_*.pdf` 仅因上述两处修复变化 5 字节。

**本次提交的分层归属**

- 入 `master`（底层）：`LayoutEngine.py`、`TECHNICAL.md`、`README.md`、`SKILLS.md`，
  以及删除旧入口 `PythonPDFLayoutSystem.py`。
- 留在功能分支（顶层）：`ResumeTemplate.py`、`ResumeCore.py` —— 见下节"分支策略"。

---

## 分支策略

项目按"底层稳定、上层多分支"组织：

- **`master`** —— 只承载**最底层**：排版引擎与引擎自身的文档。
  这一层要被所有功能分支复用，所以必须尽量稳定、尽量不含领域词汇。
- **功能分支** —— 从 `master` 签出，承载中层快捷调用与顶层功能。
  同一份引擎可以在不同分支上实现不同功能（简历、报告、文档流……）。

### 分层归属

| 层 | 文件 | 归属 |
| --- | --- | --- |
| 底层 · 构件 | `LayoutEngine.py` | `master` |
| 底层 · 文档 | `TECHNICAL.md`、`SKILLS.md`、`README.md` | `master` |
| 中层 · 快捷调用 | `create_columns` / `split_column_advanced` 等分栏设施 | `master`（待批次 2 下沉） |
| 顶层 · 版式词汇 | `ResumeTemplate.py`（`Style`、`STYLES`、`generate_*`、`fill_*`） | 功能分支 |
| 顶层 · 领域模型 | `ResumeCore.py`（`Profiles`、`Section`、`Resume`） | 功能分支 |

> **为什么 `Style` 也属于顶层**：`Style` 与"样式→对象"的翻译被计划下沉进引擎
> （见 `TECHNICAL.md` 8.4），但**当前它住在 `ResumeTemplate.py` 里**，
> 所以现在它随功能分支走。下沉完成之后它才转为底层内容。

### 本次整理：`master` 的暂存内容

以下内容已进入暂存区，属于底层，可在审阅后提交：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `A` | `LayoutEngine.py` | 排版引擎本体（含批次 0 的回归契约断言） |
| `A` | `TECHNICAL.md` | 技术文档 |
| `A`（改） | `SKILLS.md` | 协作规则 |
| `M` | `README.md` | 本文件 |
| `D` | `PythonPDFLayoutSystem.py` | 旧入口占位文件，删除 |

暂存区之外、**留给功能分支**的内容：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `??` | `ResumeTemplate.py` | 顶层：简历版式词汇 |
| `??` | `ResumeCore.py` | 顶层：简历领域模型与生成流程 |

两者互相依赖（`ResumeCore` 依赖 `ResumeTemplate`），必须同分支落地，
且 `ResumeCore.py` 当前已修到可运行（退出码 0）。

生成物一律不入库：`test_layout_engine_cached.pdf`、`resume_template_v2_test.pdf`、
`output/` —— 它们随代码变化，提交后会让每次功能分支合并都产生冲突。

### 待决事项

1. **`main.py` 的归属**：内容仅为占位（`print("Hello,world!")`），
   但当前在暂存区内。如果 `master` 只保留引擎，可考虑移到功能分支。
2. **`TECHNICAL.md` 与 `master` 内容存在时间差**：文档第 4、5 章描述的是
   `ResumeTemplate.py` / `ResumeCore.py`，而这两个文件不在 `master` 上。
   目前将其整体归为底层文档（它们描述的是引擎的既有消费方，对引擎的约束仍然有效）；
   若日后 `master` 需要独立自洽，可把这两章拆到功能分支的文档里。
3. **`PythonPDFLayoutSystem.pyproj` / `.slnx` 仍引用已删除的旧入口**：

   ```xml
   <StartupFile>PythonPDFLayoutSystem.py</StartupFile>
   <Compile Include="PythonPDFLayoutSystem.py" />
   ```

   这两处需改为指向 `LayoutEngine.py`（并补上其它源文件），否则在 Visual Studio
   中打开该项目会看到失联的启动文件。
4. **建议把生成物写进 `.gitignore`**：追加 `*.pdf` 与 `output/`，
   以免日后误提交。
5. **`SKILLS.md` 的新增规则已一并暂存**，内容为：

   > 一并在 README 中简要描述本次修改。
   > 　修改的描述跟着 Git 提交，一个四级标题下的修改应该描述接下来的提交项中有什么修改，
   > 　每一个四级标题都是时间。

   本文档的"开发日志"一节已按该规则组织：四级标题为时间（日期），
   标题下的内容描述紧随其后的那次提交。

---