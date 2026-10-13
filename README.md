# 分支：feature_resume_sub_templates

这个分支基于主分支，面向简历自动化排版对主分支实现的功能做一些封装喵~  

`ResumeTemplate.py` 是本分支的**中层**（对底层构件的调用与便捷封装），
`ResumeCore.py` 是**顶层**（面向使用者与开发人员的领域模型与流程编排）。

---

---

## 中层 API 速览

子模板一律以**方法**形式挂在任意节点上调用，返回**结果句柄**：

```python
basic   = root.add_basic(ratio=[1.0, 2.5], right_padding=Padding.left(8))
left, right = basic.left, basic.right          # 直接拿到两栏，不再按名字查

profile = left.add_profile(index=0, icon_width=6).fill("韩 梅 梅", icon_path)
title   = right.add_section_title(index=0).fill("教育背景", icon_path)

detail  = right.add_details(index=0, key="...", during_time="...",
                            tags="...", description="...")   # 建好即填好
detail.description.set_text("改一下")           # 句柄随时可取子部件

right.add_details_list(section.details)         # 列表入口：同一蓝图复用 N 次
right.add_section(section)                      # 组合模板：节标题 + 该节全部详情
left.add_text_row(name="...", text="...")       # 一行文本（技能/证书/荣誉共用）
```

| 方法 | 返回句柄 | 主要部件 |
| --- | --- | --- |
| `add_basic` | `BasicHandle` | `node` / `left` / `right` |
| `add_profile` | `ProfileHandle` | `icon` / `text` / `split` / `icon_range` / `text_range` |
| `add_profile_photo` | `PhotoHandle` | `photo` |
| `add_section_title` | `TitleHandle` | `icon` / `text` / `divider` |
| `add_details` | `DetailsHandle` | `key` / `during_time` / `tags` / `description` / `brief` / 三个 col |
| `add_summary` | `SummaryHandle` | `description` |
| `add_section` | `SectionHandle` | `title` + `details`（句柄列表） |
| `add_details_list` | `List[DetailsHandle]` | 与传入数据一一对应 |
| `add_text_row` | `TextObject` | 容器可按 `{name}_content` 查找 |
| `add_spacer` | `LayoutObject` | 流式留白 |

句柄都带 `fill(...)` / `apply(data)`（就地填充，返回 self 以便链式），
`apply` 同时接受 dict 与 dataclass。

### 尺寸与高度

容器高度交给引擎的 `SizeY.CONTENT` **自动结算**，本层不再手算 `_height`。
若某个部件需要固定高度，显式传 `description_height=12` / `content_height=13` 即可。

---

---

## 开发日志

### 2026-10-13

#### **10：35 中层重构：子模板方法风格化 + 句柄化 + 高度自动结算**

**一、新 API：子模板成为节点上的方法**

旧接口 `generate_*` / `fill_*` 共 11 个符号**全部移除**，改为挂在 `LayoutObject`
上的 10 个方法：

| 旧写法 | 新写法 |
| --- | --- |
| `generate_section_details_template(root=col, index=2)` + `fill_section_details_data(...)` | `col.add_details(index=2, key=..., description=...)` |
| `root.find_by_name(f"{col.name}_section_details_2_key")` | 句柄属性 `handle.key` |
| 循环调用 `generate_*` 造多条详情 | `col.add_details_list(items)` |
| 顶层手写"节标题 + N 条详情"循环 | `col.add_section(section)` |
| 顶层手抄 6 份技能/证书/荣誉构造代码 | `col.add_text_row(name, text, style)` |

方法之所以不定义在 `LayoutEngine.py`，是因为模板必须知道 `Style` / `STYLES` /
章节 / 详情这些**简历词汇**，而引擎对领域词汇保持零知识；方法在导入
`ResumeTemplate` 时挂载，并由断言守住"不覆盖既有成员"。

**二、高度：手动调参 → 引擎自动结算**

| 项 | 旧 | 新 |
| --- | --- | --- |
| 详情描述 | 构造时 `height=50`，再由填充函数回写 `content._height` 与 `description._height` | `SizeY.CONTENT`，按真实行数结算 |
| 个人总结 | 同上 | 同上 |
| 详情容器 | `fill` + 手算总高 | `SizeY.CONTENT` |

**三、行高：改用引擎默认**

旧代码两处传 `line_height=font_size * 0.6`。实测该参数是**死参数**
（只被写入 `_line_height`，全库从不读取），实际行高一律走 `line_height_ratio=1.2`。
因此这一项是**零产出差异**的清理；顺手改正了 `create_text_block` 文档里
"`None` 表示 `font_size * 0.6`"的错误说明（引擎侧，属底层）。

**四、新发现并修复的缺陷**

| # | 缺陷 |
| --- | --- |
| 1 | 中层自检有 5 个查询名漏写 `_right_column` 前缀，一直打印"未找到"却仍退出码 0 |
| 2 | 证件照模板与姓名模板**撞名**（`profile_photo_0_content` vs `profile_0_content`），前者注册表条目被覆盖 |
| 3 | `dividing_line` 名字不含 index，多个节标题互相覆盖注册表 |
| 4 | 个人总结与节详情**共用** `section_details_{i}` 前缀，迫使调用方手工错开编号 |
| 5 | `profile.photo` 的 `image_path=""` 使 `photo` 被判定为空，证件照整段被跳过 |
| 6 | 技能/证书/荣誉三段在顶层手抄约 200 行 |
| 7 | 微信行填的是 **QQ 号**（`f"微信：{profile.social_media_qq}"`） |
| 8 | 联系方式编号从 0 起算，与姓名模板撞名 |

**五、结构级验收**

改动前代码从未入库，无法用 git 取回，因此改用**独立重建**做比对：把旧 API 的语义
单独重实现一份，跑同一份数据，再与新版逐节点对照。

结果（135 节点）：

- 共有节点 120 个，其中 **24 个有实质差异，全部落在上面 4 项有意变更内**；
- 右栏从节标题到总结之间**每个元素的 y 坐标完全未变** —— 说明"自动结算出的详情高度"
  与原固定值逐项等值，是等价替换而非尺寸变化；
- 左栏整齐下移 9mm 一项，唯一来源是个人信息行默认高度：从硬编码 `20mm`
  改为按"字号一半 / 图标高 + 留白"推算（22pt 姓名行 → 11mm）。

生成物基线（`%TEMP%\resume_pre_refactor`）与 `verify_pdfs.py` 仍可用于后续回归。

#### **批次 7：文本落点与盒内对齐（两处缺陷，详见 TECHNICAL.md 3.4d）**

**一、传给 `pdf.cell` 的格子高漏了单位换算（主因）**

`render()` 用 `pdf.cell(_w, own_h, txt)` 画字，其中
`own_h = 字号 × line_height_ratio`。但 fpdf 的 `cell(w, h)` 的 `w/h` 是
**用户空间单位（mm）**，而字号是 **pt** —— pt 当 mm 用，格子高虚高 **2.8346 倍**。
fpdf 又把文字**垂直居中**在格子里，于是基线落到格子中央：

```
22pt 的文字 -> own_h = 26.4（当 mm）-> 基线相对盒顶下移 15.53mm
而节标题的盒子只有 14.5mm 高        -> 文字基线直接跑到盒外
```

修法：`pdf.cell(_w, own_h * PT_TO_MM, txt)`，新增常量 `PT_TO_MM = 25.4 / 72.0`。

> 注意区分：`py = cy + line_top + (line_h - own_h)` **不需要换算** ——
> `line_top` / `line_h` 与 `own_h` 同为 pt 数值，相减得到的行内偏移自洽。

**二、`align_y` 从未被渲染读取**

`_place()` 用 `align_y` 决定"盒子摆在哪"，`render()` 却完全不读它，
文字一律贴内容区顶边 —— `VCENTER` / `BOTTOM` 对文字落点毫无作用。
修法：在 `render()` 里按同一条对齐规则分配盒内剩余空间。

**三、标定与验收**

受控实验（固定格子高 10mm，取 8/12/16/24/32/40pt）拟合得：

```
基线偏移 = 0.10584 × 字号 + 4.99968        截距恰为 h/2
```

证明 fpdf 按 mm 正确解释了格子高，问题只在调用方传错了单位。据此得到落点公式：

```
文字基线 = 盒顶 + padding.top + dy_align
           + (字号 × line_height_ratio × PT_TO_MM) / 2 + 0.10583 × 字号
  其中 dy_align = VCENTER → (盒内高 − 文字实高)/2
                  BOTTOM  →  盒内高 − 文字实高
                  TOP / NONE / FLOW → 0
```

实测影响面：节标题、姓名行等 22pt 文本的基线相对盒顶 **15.53mm**，
**超出 14.5mm 高的盒子**；9 个文本块合计 **45.82mm** 的纵向虚位移。

**四、自检入口新增第 13 节断言**

这个缺陷能长期存活，正是因为引擎自检里没有"文字必须落在盒内"的断言。
新增的第 13 节直接观测"文字画到哪"（包住 `pdf.set_xy` 记录落点）：

- 三种对齐（`TOP` / `VCENTER` / `BOTTOM`）的落点必须两两不同 —— 旧实现下三者相同；
- 落点顺序必须是 `TOP < VCENTER < BOTTOM`；
- 相邻间距必须等于 `(盒内高 − 文字实高)/2`（实测 12.46mm，与公式一致）；
- 落点偏移必须落在盒内、且不超过合理上界。

**五、升级须知**

所有载体的**文字位置都会变**。任何"为了抓住偏低文字"而调过的盒高，
都需要按上面的公式重新校一遍。中层（`ResumeTemplate.py`）的参数表见
功能分支文档的「中层调参手册」。

---

#### **11：18 资源策略与分支卫生：`Resources/` 全部素材不入库**

- `.gitignore` 从 `Resources/*.ttf` 改为 `Resources/*` + `!Resources/.gitkeep`，
  目录本身用 `.gitkeep` 保留，并在其中写明素材的获取方式；
- 决定理由：素材体积小但数量持续变动、随时可能被换成自己的素材，需要时未来再补齐；
- 后果是**静默降级**而非崩溃 —— 缺字体则中文变空白（退回内置 helvetica），
  缺图标则该位置留空，两个测试入口在没有素材时仍退出码 0；
- 补 `TECHNICAL.md` 4.8「资源清单」：逐个列出文件名与引用它的地方；
- `SKILLS.md` 的 A1 标为**已完成**（`.pyproj` 早已含 `ResumeTemplate.py`，
  且**刻意不含** `ResumeCore.py`，符合分支策略）；A2 由"应入库"改为"不入库"，
  附完整说明；E 节补一行结论。

> 核实结论：**中层不依赖任何图标文件**。`ResumeTemplate.py` 里 5 处图片引用
> 全在 `__main__` 内，`add_profile` / `add_section_title` 只收参数，
> `STYLES` 的 `image_path` 都是空串 —— 素材是顶层与测试的事。

#### **11：25 修正失效的图标引用**

- `ResumeTemplate.py` 测试入口引用的 `icon.png` 并不存在，
  改为实际存在的 `icon_Profile_Name.png`（169KB 的主图标）。

#### **11：26 修正 `.pyproj` 的过期注释**

- 注释原先写"入口与启动文件均指向 LayoutEngine"，与实际的
  `StartupFile=ResumeTemplate.py` 不符；已改正并注明顶层文件为何不列入。

> `.pyproj` 的实质修改（补 `ResumeTemplate.py` 编译项、切换启动文件）
> 已随提交 `cfc2ea5` 入库，本次只剩注释行。

---

---
