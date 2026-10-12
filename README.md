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

## 资源获取

### 字体（必需）

`Resources/` 下的字体文件**不入库**（约 117 MB），需要自行下载。
缺少字体会导致中文渲染为空白，且**不会报错** —— 引擎会静默降级到内置的 helvetica。

需要的是**霞鹜文楷（LXGW WenKai）**，作者 LXGW，采用 SIL Open Font License 1.1，可免费商用。

- 项目主页：<https://github.com/lxgw/LxgwWenKai>
- 发布页（选最新 Release）：<https://github.com/lxgw/LxgwWenKai/releases>
- 等宽版本（可选，`LXGWWenKaiMono*`）：<https://github.com/lxgw/LxgwWenKaiMono>

下载后按下列**文件名**放入 `Resources/`（代码按这些名字引用）：

| 文件名 | 用途 |
| --- | --- |
| `LXGWWenKai-Regular.ttf` | 正文（注册为 `LXGW` 的常规体） |
| `LXGWWenKai-Bold.ttf` | 粗体（注册为 `LXGW` 的 `B` 风格） |
| `LXGWWenKai-Light.ttf` | 可选 |
| `LXGWWenKaiMono-Regular.ttf` | 可选，等宽 |
| `LXGWWenKaiMono-Bold.ttf` | 可选，等宽 |
| `LXGWWenKaiMono-Light.ttf` | 可选，等宽 |

> 最少只需要 `Regular` 与 `Bold` 两个，其余四个可以不下。
> 若解压后的文件名与上表不同，请重命名。

### 图标与照片（中层/顶层使用，可选）

`ResumeCore.py` / `ResumeTemplate.py` 引用了若干图标与照片，**这些资源尚未入库**。
它们只在中层与顶层使用，底层排版引擎不依赖它们。涉及的文件名：

```
icon.png  icon_Education_History.png  icon_Project_History.png
woman_student.png  photo_1.png
telephone.png  email.png  locate.png
social_media.png  contact_address.png  website.png
```

**这些文件缺失不会导致报错** —— `ImageObject` 会静默跳过绘制，
所以生成的 PDF 里看不到图标，但其余内容排版正常。
排查「图标不见了」一类问题时，先确认这些文件是否存在。

---

---

## 开发日志

### 2026-10-11

#### **20：52** 

第一次提交

- 建立 main 并测试 fpdf2 库引用
- 建立资源和模块文件夹

#### **批次 0：修复阻断性缺陷 + 建立技术文档**


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


#### **批次 1：抽出留白构件 `create_spacer`**


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

#### **基础设施：仓库卫生与程序入口**

- **生成物不入库**：`.gitignore` 追加 `*.pdf`（测试 PDF）与 `output/`（简历输出目录）。
  两者都可由测试入口复现。
- **字体不入库**：`.gitignore` 追加 `Resources/*.ttf`（约 117 MB）。
  只忽略字体本身，未来补充的图标/照片仍应正常入库。
- **README 新增「资源获取」章节**：写明霞鹜文楷（LXGW WenKai）的下载来源、
  许可（SIL OFL 1.1，可免费商用）、所需文件名与放置路径；
  并列出中层/顶层引用但尚未入库的图标与照片。
- **程序入口改指 `LayoutEngine.py`**：`PythonPDFLayoutSystem.pyproj` 的
  `<StartupFile>` 与 `<Compile Include>` 此前指向已删除的 `PythonPDFLayoutSystem.py`，
  在 Visual Studio 中打开会看到失联的启动文件。

### 2026-10-12

#### **批次 2：抽出横向带构件 `create_band`**

- `LayoutEngine.py` 新增 `create_band(parent, cells, gap, padding, height, names, colors, layer, container_name)` ——
  横向布局的基础构件。`cells` 元素既可以是比例权重（`float`，新建空格子），
  也可以是已构造对象（`LayoutObject`，直接复用并保留其自身宽度）。
- `create_band` **只做严格按比例**；`create_columns` 的"宽度不足时把剩余量按栏数均分"
  是它独有的语义，留在 `create_columns` 里（两趟实现：先算宽度，再交给 `create_band` 排放）。
- `split_column_advanced` **从 `ResumeTemplate.py` 移入引擎**，改为 `create_band` 的包装。
  分层违规消除：`ResumeCore.py` 此前为了分栏必须 `import ResumeTemplate`。

**顺带修掉的两个缺陷**

- **缺陷 7.4**：`create_columns` 里 `parent.children = []` 会静默丢弃父元素既有子元素，
  且绕过 `remove_child` 使被丢弃子元素的父指针悬空。已删除该行。
  测试入口的断言从"固化现状"**反转**为"既有子元素被保留"。
- **缺陷 7.3**：`split_column_advanced` 绕过 `add_child` 直接改 `children` 列表，
  不触发缓存失效（几何缓存尤其没失效）。移入引擎后统一走 `add_child`。

**返回值变更（需注意）**

`create_columns` 与 `create_columns_balanced` 现在返回**新建的带容器**，
此前返回传入的 `parent`。仓库内无调用方依赖该返回值，但这是破坏性变更，已写入技术文档。
`split_column_advanced` 为保持链式调用兼容，**仍返回 `parent`**。

**测试**

- 引擎测试入口新增 `create_band` 断言 11 项：比例分宽、`gap` 累加 x、
  `height=0` 取父内容区高、复用已构造对象（保留宽度、接管位置与高度）、
  4 条错误路径、包装函数返回值、`split_column_advanced` 包装。
- 三个入口退出码 0；**规范化比对：三个产物全部逐字节一致**。

**过程中的一次真实踩坑（值得记住）**

`create_columns` 改为走 `create_band` 后，各栏从"`parent` 的直接子元素"变成
"带容器的子元素"，多出一层。而引擎测试入口原先用 `container.get_child("Column_0")` 取栏，
`get_child` 只看直接子元素，于是拿到 `None`，两段文本根本没被创建 ——
引擎 PDF 从 `19316` 字节掉到 `18071`。

**这不是引擎的问题，是测试的假设失效了。** 改用 `find_by_name`（深度优先）后恢复一致。
结论：**包装层会改变树形，所有按名字取对象的地方都要检查该用 `get_child` 还是 `find_by_name`。**
逐字节比对把这个错误挡在了提交之前。

#### **缺陷 7.11(a)：`render_debug()` 补齐返回值**

起因：把测试入口的 `root.render(...)` 换成 `root.render_debug(...)` 后，
返回值断言以 `AssertionError: ... 实际返回 NoneType` 炸掉。

- **根因**：四个 `render_debug` 实现（`LayoutObject` / `TextObject` / `ImageObject` /
  `RectangleObject`）末尾**都没有 `return` 语句**，一律隐式返回 `None`。
  它们内部明明有子元素递归，却不冒泡任何值。这个报错与 `render()` 的契约毫无关系，
  极易误判为回归。
- **修复**：四个实现补上返回值，语义与各自的 `render()` 对齐 ——
  `LayoutObject` / `TextObject` 返回值 y；`ImageObject` / `RectangleObject` 返回 `(宽, 高)`；
  `pdf=None` 或有效尺寸非正时显式返回 `None`。
- **顺带修掉一个被掩盖的崩溃**：`ImageObject` / `RectangleObject` 的 `eff_w` / `eff_h`
  原先只在 `if show_name:` 分支内赋值。因为末尾没有 `return`，这两变量在
  `show_name=False` 时从未被读取，问题一直没暴露；补返回值后直接引用就会
  `UnboundLocalError`。已把取尺寸提到分支之外。
- 测试入口的断言相应放宽为「接受数值 y 或 `(宽, 高)` 二元组，但**拒绝 `None`**」，
  这样能同时守住 `render` 与 `render_debug` 两条路径。
- 验证：`show_name=True/False`、`is_fill=True` 三种调试配置端到端均无异常；
  三个入口退出码 0；**三个产物恢复逐字节一致**（`19316` / `61370` / `68478`）。

> 排查中还确认了一件事：调试渲染的产物与正式渲染**本就不同** ——
> `render_debug` 会用 helvetica 画边框与名称/尺寸标签，
> 所以产物里会多出 `Helvetica` 字体，而 LXGW 子集反而变小
> （只画标签、不画正文，用到的字形更少）。
> 基线 19316 字节 → 调试产物 6098 字节，是预期差异而非回归。

技术文档 7.11 已拆成 (a) 已修 / (b) 待批次 4 两节。

#### **批次 4 的前置分析（矩形包围内容）**

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
| 中层 · 快捷调用 | `create_band` / `create_columns` / `split_column_advanced` / `create_spacer` | `master`（批次 1、2 已下沉） |
| 顶层 · 版式词汇 | `ResumeTemplate.py`（`Style`、`STYLES`、`generate_*`、`fill_*`） | 功能分支 |
| 顶层 · 领域模型 | `ResumeCore.py`（`Profiles`、`Section`、`Resume`） | 功能分支 |

> **为什么 `Style` 也属于顶层**：`Style` 与"样式→对象"的翻译被计划下沉进引擎
> （见 `TECHNICAL.md` 8.4，属**批次 3**），但**当前它住在 `ResumeTemplate.py` 里**，
> 所以现在它随功能分支走。下沉完成之后它才转为底层内容。

### 本次整理：`master` 的暂存内容

`8af9962`（新增构件 spacer）已提交。在其之上，**基础设施**与**批次 2** 产生了以下待提交内容：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `M` | `.gitignore` | 追加 `*.pdf`、`output/`、`Resources/*.ttf` |
| `M` | `README.md` | 新增「资源获取」章节 + 上述日志 |
| `M` | `PythonPDFLayoutSystem.pyproj` | 入口与编译项改指 `LayoutEngine.py` |
| `M` | `LayoutEngine.py` | 新增 `create_band` + `split_column_advanced` 移入 + 修 7.3/7.4 + 断言 |
| `M` | `TECHNICAL.md` | 3.4 节重写、8.1 标完成、7.3/7.4 标修复、批次表更新、新增批次 2 踩坑记录 |

暂存区之外、**留给功能分支**的内容（自 `f718518` 起一律未跟踪，符合分层归属）：

| 状态 | 文件 | 说明 |
| --- | --- | --- |
| `??` | `ResumeTemplate.py` | 顶层：简历版式词汇 |
| `??` | `ResumeCore.py` | 顶层：简历领域模型与生成流程（已改用 `create_spacer`） |

两者互相依赖（`ResumeCore` 依赖 `ResumeTemplate`），必须同分支落地，
且 `ResumeCore.py` 当前已修到可运行（退出码 0）。

> ✅ **已验证底层与顶层暂时不同步不构成问题**：批次 1、2 让
> `ResumeCore.py` / `ResumeTemplate.py` 用上了新增的 `create_spacer`、`create_band`，
> 而这两个文件未入库。依赖方向是顶层依赖底层，所以 `master` 上的 `LayoutEngine.py`
> 只是多了两个暂时无人使用的构件。在包含这两个文件的工作树中，三个入口均实测退出码 0。

生成物已由 `.gitignore` 排除：`test_layout_engine_cached.pdf`、`resume_template_v2_test.pdf`、
`output/` —— 它们随代码变化且可由测试入口复现。

### 待决事项

1. **功能分支尚未建立**：`master` 目前只有引擎与文档。等批次 3 把中层设施
   （`create_text_block`、`Style`）也下沉完毕后，即可从 `master` 签出
   功能分支，把 `ResumeTemplate.py` / `ResumeCore.py` 作为首个提交放进去。
2. **`main.py` 的归属**：内容仅为占位（`print("Hello,world!")`），已在 `f718518` 中入库。
   程序入口已按决定指向 `LayoutEngine.py`（`.pyproj` 的 `StartupFile`），
   `main.py` 可留作占位，或在功能分支里替换为真正的入口。
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