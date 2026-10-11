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

### 2026-10-13

#### **批次 1：抽出留白构件 `create_spacer`**

> 待提交（内容已在暂存区）。本次提交的内容简述如下。

**新增构件**

- `LayoutEngine.py` 新增 `create_spacer(name, height, parent=None, layer=0)` ——
  创建纯留白对象（垂直间距）。等价于 `width=0`、`align_x=CENTER`、`align_y=FLOW` 的
  `LayoutObject`；`parent` 非空时自动挂载（走 `add_child`，缓存失效正确触发）。
- 刻意**不暴露** `color` / `padding` / `align_y` 三个参数，依据是实测：
  `LayoutObject.render()` 在 `is_fill=False` 时不绘制内容，留白的颜色对输出无影响；
  留白 `_height > 0` 时 `get_effective_height()` 走 `min(_height, avail_h)` 分支，
  padding 不参与计算（实测 `Padding.all(0)` 与 `Padding.all(10)` 的有效高/宽/绝对 y 完全相同）。

**替换**

- `ResumeCore.py` 的 **14 处** `Lead_*` 留白字面量全部改为 `create_spacer(...)` 调用，
  每处从 11 行缩到 4 行；替换后文件中已无裸的留白对象字面量。
- 抽取前这 14 处的 `color` 用了 `White`/`Black`/`Blue`/`Green`/`Yellow` 五种、
  `padding` 在 `all(0)` 与 `all(10)` 之间摇摆，都是复制粘贴残留，现已一并消除。

**澄清了一处文档中的存疑推断**

- 技术文档 8.2 原先推测"`Padding.all(10)` 会让 FLOW 间距变成 `10 + height`"。
  **实测证明该推断不成立**，padding 不参与有效高度计算。文档已更正。

**测试**

- `LayoutEngine.py` 测试入口新增 `create_spacer` 构件契约断言：构造高度、`align` 取值、
  自动挂载与父指针、游离态，以及"padding 不影响有效高度"。
- 三个入口退出码 0。
- **规范化比对：三个产物全部逐字节一致**（`19316` / `61370` / `68478` 字节）。
  批次 1 是纯粹的等价重构，只抽构件、不改行为，这正是它追求的结果。

### 2026-10-14

#### **批次 4 的前置分析（矩形包围内容）**

> 待提交（内容已在暂存区），与技术文档同批。本次提交的内容简述如下。

- 实测确认 `wrap_height=True` 会让高度**塌缩为 padding**（同一结构 49.00 → 4.00），
  根因是父子高度的循环依赖：子元素有效高度被父可用高度裁剪，而父可用高度又来自父的有效高度。
  此项记为缺陷 7.19。
- 实测确认 `invalidate_wrap_cache()` 不清 `_height`，导致 wrap 结果一旦算错便永久卡死，
  连 `wrap_content(force=True)` 也无法重算。此项记为缺陷 7.20。
- 实测确认 `wrap_width` 三条路径全部返回 0，原理上自相矛盾（收窄要求子宽自主，
  而 `_width == 0` 的语义是"撑满父宽"）。此项记为缺陷 7.21。
- 结论：**"矩形包围内容"不单独占一批，与"几何属性改 property"合并为批次 4，并排在其最前面。**
  两者是同一件事的两半 —— property 化解决"何时知道要重算"，
  修 7.19/7.20 解决"重算能不能算对"。批次表已拆出 4a（包围固定高度内容）与
  4b（修 `wrap_width`）；包围自动换行的长文本依赖批次 5 的真实行数测量。
- 技术文档新增 8.11 节完整记录该分析。

**Git 远端访问**

- 本轮实测：GitHub 只读操作恢复正常（`ls-remote` 2.97s、`fetch --dry-run` 1.43s，退出码 0），
  `f718518` 已推送成功，本地与 `origin/master` 零分叉。

> ⚠️ **日期需核对**：上面的 `2026-10-12` ~ `2026-10-14` 是为满足
> "每一个四级标题都是时间"这条规则而填的占位日期（`2026-10-11` 之外的日期我无法确知）。
> 提交前请改为实际日期；若某几次修改在同一提交内完成，可合并为一个四级标题。

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

`f718518` 已提交并推送。在其之上，**批次 1** 产生了以下待提交内容：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `M` | `LayoutEngine.py` | 新增 `create_spacer` 构件 + 其构件契约断言 |
| `M` | `TECHNICAL.md` | 8.2 标完成、`create_spacer` API 条目、缺陷 7.19~7.21、8.11 矩形包围分析、批次表更新 |
| `M` | `README.md` | 本文件 |

暂存区之外、**留给功能分支**的内容（自 `f718518` 起一律未跟踪，符合分层归属）：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `??` | `ResumeTemplate.py` | 顶层：简历版式词汇 |
| `??` | `ResumeCore.py` | 顶层：简历领域模型与生成流程（已改用 `create_spacer`） |

两者互相依赖（`ResumeCore` 依赖 `ResumeTemplate`），必须同分支落地，
且 `ResumeCore.py` 当前已修到可运行（退出码 0）。

> ⚠️ **批次 1 让底层与顶层暂时不同步**：`ResumeCore.py` 现在调用
> `LayoutEngine.create_spacer`，但 `ResumeCore.py` 自身未入库。
> 这不构成问题 —— 依赖方向是顶层依赖底层，
> `master` 上的 `LayoutEngine.py` 只是多了一个暂时无人使用的构件。

生成物一律不入库：`test_layout_engine_cached.pdf`、`resume_template_v2_test.pdf`、
`output/` —— 它们随代码变化，提交后会让每次功能分支合并都产生冲突。

### 待决事项

1. **功能分支尚未建立**：`master` 目前只有引擎与文档。等到批次 2、3 把中层设施
   （`layout_band`、`create_text_block`、`Style`）也下沉完毕后，即可从 `master` 签出
   功能分支，把 `ResumeTemplate.py` / `ResumeCore.py` 作为首个提交放进去。
2. **`main.py` 的归属**：内容仅为占位（`print("Hello,world!")`），
   已在 `f718518` 中入库。若认为 `master` 只该留引擎，可在功能分支里替换为真正的入口。
3. **`TECHNICAL.md` 与 `master` 内容存在时间差**：文档第 4、5 章描述的是
   `ResumeTemplate.py` / `ResumeCore.py`，而这两个文件不在 `master` 上。
   目前将其整体归为底层文档（它们描述的是引擎的既有消费方，对引擎的约束仍然有效）；
   若日后 `master` 需要独立自洽，可把这两章拆到功能分支的文档里。
   注意第 3.4 节的 `create_spacer` 条目**属于底层**，不受此影响。
4. **`PythonPDFLayoutSystem.pyproj` / `.slnx` 仍引用已删除的旧入口**：

   ```xml
   <StartupFile>PythonPDFLayoutSystem.py</StartupFile>
   <Compile Include="PythonPDFLayoutSystem.py" />
   ```

   这两处需改为指向 `LayoutEngine.py`（并补上其它源文件），否则在 Visual Studio
   中打开该项目会看到失联的启动文件。
5. **建议把生成物写进 `.gitignore`**：追加 `*.pdf` 与 `output/`，
   以免日后误提交。
6. **`Resources/` 是否入库仍未定**：内含 6 个霞鹜文楷 TTF，单个 18–21 MB、合计约 117 MB。
   完全不入库则新克隆的仓库缺字体、中文静默降级为空白；全量入库则仓库显著变重。
   可选：全部入库 / 只入 Regular+Bold / Git LFS / 只写下载说明。
   目前没有任何 `.gitignore` 规则覆盖它，**将来一定会被误提交**。

---