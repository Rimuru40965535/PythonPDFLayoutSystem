"""
================================================================================
简历模板层  (Resume Template Layer)
================================================================================
定位：本项目的**中层** —— 把引擎（底层）的基本构件封装成"简历版式词汇"，
       供顶层（ResumeCore.py 的领域模型与流程编排）直接调用。

核心设计（三层结构）
--------------------------------------------------------------------------------
    文档 (add_basic)
      └─ 左栏 / 右栏
           └─ 节 (add_section) = 节标题 + N × 节详情
                └─ 原子模板 (add_profile / add_section_title / add_details / …)

每个生成函数都**建好、挂好、填好**，并返回一个**结果句柄**（Handle）。

句柄代替字符串查询
--------------------------------------------------------------------------------
    旧写法（字符串是唯一身份，错一个字符就静默失败）：
        generate_section_details_template(root=col, index=2)
        fill_section_details_data(root=col, index=2, key=..., ...)
        obj = root.find_by_name("col_section_details_2_key")     # 容易写错

    新写法（返回值就是句柄，IDE 可补全，写错立刻报 AttributeError）：
        d = col.add_details(index=2, key=..., description=...)
        d.key.set_text("新的学校名")                              # 直接取用

数量与数据的复用
--------------------------------------------------------------------------------
    模板 = 一份蓝图；数据 = 一批内容。蓝图复用 N 次即得 N 个实例：
        col.add_details_list(section.details)      # 列表入口，循环收在层内
        col.add_section(section)                   # 组合模板：标题 + 该节全部详情

尺寸与高度
--------------------------------------------------------------------------------
    内容决定高度交给引擎的 `SizeY.CONTENT` **自动结算**，本层不再手算 `_height`。
    （旧写法 `content._height = description_height + brief_height` 是手工模拟
      CONTENT 语义，已删除。）

依赖：LayoutEngine.py（底层构件）。本层不依赖 ResumeCore.py。

================================================================================
"""

import contextlib
import io
import os
import dataclasses
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

from fpdf import FPDF

from LayoutEngine import (
    # 构件
    LayoutObject,
    TextObject,
    ImageObject,
    RectangleObject,
    # 样式与文本片段
    Style,
    TextRun,
    BreakPolicy,
    DEFAULT_BREAK_POLICY,
    parse_inline_markdown,
    measure_text,
    PT_TO_MM,
    # 枚举与常量
    AlignX,
    AlignY,
    SizeX,
    SizeY,
    Padding,
    Color,
    White,
    Black,
    RimuruBlue,
    # 中层构件（引擎已下沉的快捷调用）
    create_band,
    create_spacer,
)


# ============================================================================
# 1. 版式默认值
# ============================================================================
# 集中在此，避免常量散落在各模板函数里（旧版把 15 / 50 / 1.6 等写死在函数体内）。

DEFAULT_RATIO: List[float] = [1.0, 2.5]         # 基础模板左右分栏比例
DEFAULT_TITLE_HEIGHT: float = 15.0              # 节标题整体高
DEFAULT_DIVIDER_HEIGHT: float = 0.5             # 节标题下方分隔线粗细
DEFAULT_BRIEF_HEIGHT: float = 10.0              # 详情三栏（关键词/时间/标签）高
DEFAULT_BRIEF_RATIO: List[float] = [2.0, 1.0, 2.0]
DEFAULT_ICON_WIDTH: float = 4.0                 # 个人信息左格宽
DEFAULT_TITLE_ICON_WIDTH: float = 10.0          # 节标题左格宽
DEFAULT_PHOTO_WIDTH: float = 30.0               # 证件照宽
PHOTO_ASPECT: float = 1.6                       # 证件照高 = 宽 × 此值
DEFAULT_ROW_INSET: float = 3.0                  # 分栏行左缩进（旧 split 容器的左内边距）
DEFAULT_ROW_PAD_Y: float = 3.0                  # 行内图标上下的最低留白
DEFAULT_HIGHLIGHT_HEIGHT: float = 9.0           # 重点突出信息行默认高
DEFAULT_BULLET_SIZE: float = 3.2                # 分条目的正方形引导符边长
DEFAULT_BULLET_INDENT: float = 1.0              # 分条目整行的左缩进
DEFAULT_BULLET_GAP: float = 2.0                 # 引导符与文本之间的距离
DEFAULT_PARA_ICON_WIDTH: float = 4.0            # 图标段落：左栏宽 = 图标宽
DEFAULT_PARA_ICON_INDENT: float = 1.0           # 图标段落：整行左缩进
DEFAULT_PARA_ICON_PAD_TOP: float = 0.5          # 图标段落：左栏上内边距
# 图标段落（add_para）的缺省图标。
# ⚠️ 这是**可配置的占位值**：`Resources/` 里的图标都是语义化的（教育/项目/…），
#    目前没有通用的"重点标记"符号，所以这里先借一个方形图标顶上。
#    换图标只需改这一处（或每次调用显式给 icon=…）。
DEFAULT_PARA_ICON: str = ".\\Resources\\black_circle.png"


def profile_content_height(style: Optional[Style] = None,
                           icon_width: float = 0.0) -> float:
    """
    个人信息行默认高度：取"文本最小高度"与"图标占高 + 上下留白"的较大者。

    旧实现把这一行的高度写死为 20mm，与字号、图标尺寸都无关；
    改为按内容要素推算，容器尺寸仍可由 content_height 显式覆盖。
    """
    st = STYLES["profile_text"] if style is None else style
    text_min = st.font_size * 0.5
    icon_min = icon_width + DEFAULT_ROW_PAD_Y if icon_width > 0 else 0.0
    return max(text_min, icon_min)


def skills_row_height(style: Optional[Style] = None) -> float:
    """技能/证书/荣誉行默认高度。默认取字号的一半（与历史行为一致）。"""
    st = STYLES["skillsawards_title"] if style is None else style
    return st.font_size * 0.5


# ============================================================================
# 1b. 共享测量实例
# ============================================================================
# "高度由内容决定"必须先知道"文本按可用宽折几行"，而这需要 pdf 实例。
#
# ⚠️ **不要每次测量都新建 FPDF**。实测代价（30 次测量）：
#       复用同一实例  ：    23.56 ms
#       每次新建实例  ：30 559.00 ms（注册字体 345 ms/次），净增内存 2.5 GB
#   而且未注册字体的实例**测不了中文** —— fpdf 会抛
#   `FPDFUnicodeEncodingException`（内置 helvetica 不支持 CJK），
#   `measure_text` 内部不捕获该异常（`font_context` 的优雅降级只处理"变体缺失"）。
#
# 因此这里维护**一个惰性创建的共享测量实例**：只建一次，用于量字宽与折行，
# **从不 output()**。遍历深度与它无关 —— 任何层级的模板都用同一个。
#
# 注：这确实是一处模块级可变状态（与引擎的 layer_manager / objectRegister 同类，
#     见 TECHNICAL.md 7.14 / SKILLS.md D4）。为便于测试与确定性复现，提供
#     `reset_measure_pdf()`。

_MEASURE_PDF: Optional[FPDF] = None
_MEASURE_FONTS_LOADED: bool = False

# 测量实例用的小页面：只需能承载字体与 get_string_width，尺寸无关
_MEASURE_PAGE = (50.0, 50.0)


def reset_measure_pdf() -> None:
    """丢弃共享测量实例（下次调用会重建）。供测试与"同进程多份文档"场景使用。"""
    global _MEASURE_PDF, _MEASURE_FONTS_LOADED
    _MEASURE_PDF = None
    _MEASURE_FONTS_LOADED = False


def _register_measure_fonts(pdf: FPDF) -> bool:
    """
    在测量实例上注册正文字体。返回是否注册成功。

    失败时**明确告知**（静默降级是本项目的既有教训）：
    缺字体时中文测量会抛异常、英文会得到错误字宽。
    """
    global _MEASURE_FONTS_LOADED
    try:
        pdf.add_font("LXGW", "", ".\\Resources\\LXGWWenkai-Regular.ttf")
        pdf.add_font("LXGW", "B", ".\\Resources\\LXGWWenkai-Bold.ttf")
        _MEASURE_FONTS_LOADED = True
        return True
    except Exception as exc:
        _MEASURE_FONTS_LOADED = False
        print(f"  >>>⚠ 测量用字体注册失败（{exc}）。")
        print(f"       中文文本的高度测量将不可用 —— 请确认 "
              f"Resources/LXGWWenkai-Regular.ttf 存在。")
        return False


def measure_pdf() -> FPDF:
    """
    取得共享的测量用 FPDF 实例（惰性创建，只建一次）。

    该实例**只用于测量**，从不渲染、从不 output()。
    """
    global _MEASURE_PDF
    if _MEASURE_PDF is None:
        pdf = FPDF()
        pdf.add_page()
        _register_measure_fonts(pdf)
        _MEASURE_PDF = pdf
    return _MEASURE_PDF


def _build_runs(text: str, style: Style) -> List[TextRun]:
    """
    按 Style 构造测量用的 TextRun 列表。

    与 `TextObject(text=...)` 的行为一致：经内联 Markdown 解析，
    因此 `**加粗**` 之类的标记会改变测得的字宽与行数。
    """
    base = TextRun.from_style("", style)
    return parse_inline_markdown(text, base) if text else [base]


def wrapped_height(text: str,
                   style: Style,
                   available_width: float,
                   line_height_ratio: float = 1.2,
                   pdf: Optional[FPDF] = None) -> float:
    """
    文本在给定可用宽度下折行后的**实际高度（mm）**。

    这是"高度由内容决定"的基础工具：先量宽、再定高。

    Args:
        text: 文本内容（支持 \\n 硬换行与内联 Markdown）
        style: 样式（字号/字体/粗斜体参与测量）
        available_width: 文本可用宽度 (mm)。0 或负数表示不折行（量单行）
        line_height_ratio: 行高系数，与引擎默认一致
        pdf: 测量实例。None 表示用共享实例

    Returns:
        折行后的实际高度 (mm)，已换算到引擎的长度单位

    Raises:
        RuntimeError: 文本含 CJK 而测量实例没有可用字体（无法给出正确字宽）
    """
    engine_pdf = pdf if pdf is not None else measure_pdf()
    runs = _build_runs(text, style)
    if not any(r.text for r in runs):
        return 0.0
    try:
        m = measure_text(engine_pdf, runs,
                         available_width=max(available_width, 0.0),
                         line_height_ratio=line_height_ratio)
    except Exception as exc:
        raise RuntimeError(
            f"文本测量失败（{type(exc).__name__}: {exc}）。"
            f"若文本含中文，请确认 Resources/LXGWWenkai-Regular.ttf 已就位 —— "
            f"未注册字体时 fpdf 无法为 CJK 计算字宽。"
        ) from exc
    return m.total_height * PT_TO_MM


def wrapped_lines(text: str,
                  style: Style,
                  available_width: float,
                  line_height_ratio: float = 1.2,
                  pdf: Optional[FPDF] = None) -> int:
    """文本在给定可用宽度下折成的行数。参数语义同 wrapped_height。"""
    engine_pdf = pdf if pdf is not None else measure_pdf()
    runs = _build_runs(text, style)
    if not any(r.text for r in runs):
        return 0
    m = measure_text(engine_pdf, runs,
                     available_width=max(available_width, 0.0),
                     line_height_ratio=line_height_ratio)
    return m.line_count


# ============================================================================
# 2. 预定义样式实例 (STYLES)
# ============================================================================
# 注意：Style 现在**只有一份**，来自 LayoutEngine（批次 3 已下沉）。
#       旧版本在此重复定义了一份 class Style 并遮蔽引擎版本，两边会悄悄漂移。

STYLES = {
    # ---- 左栏样式 ----
    "left_column": Style(
        fill_color=RimuruBlue,
    ),

    # ---- 证件照样式 ----
    "profile_photo": Style(
        fit_mode="cover",
    ),

    # ---- 姓名相关样式 ----
    "name_image": Style(
        image_path="",  # 由用户填充
    ),
    "name_text": Style(
        font_name="LXGW",
        font_size=22,
        bold=True,
        color=Black,
    ),

    "profile_text": Style(
        font_name="LXGW",
        font_size=12,
        bold=True,
        color=Black,
    ),

    # ---- 联系方式样式 ----
    "contact_text": Style(
        font_name="LXGW",
        font_size=10,
        color=Color(60, 60, 60, 0),
    ),

    "skillsawards_title": Style(
        font_name="LXGW",
        font_size=14,
        color=Color(60, 60, 60, 0),
    ),

    "skillsawards_text": Style(
        font_name="LXGW",
        font_size=10,
        color=Color(60, 60, 60, 0),
    ),

    # ---- 右栏节标题样式 ----
    "section_title_image": Style(
        image_path="",  # 由用户填充
    ),
    "section_title_text": Style(
        font_name="LXGW",
        font_size=22,
        bold=True,
        color=Color(0, 80, 160, 0),
    ),

    # ---- 节详情样式组 1 (默认) ----
    "detail_key_1": Style(
        font_name="LXGW",
        font_size=13,
        bold=True,
        color=Black,
    ),
    "detail_time_1": Style(
        font_name="LXGW",
        font_size=7,
        color=Color(100, 100, 100, 0),
        padding=Padding.top(5),
    ),
    "detail_tags_1": Style(
        font_name="LXGW",
        font_size=8,
        color=Color(80, 80, 80, 0),
    ),

    # ---- 节详情样式组 2 (备选/紧凑) ----
    "detail_key_2": Style(
        font_name="LXGW",
        font_size=12,
        bold=True,
        color=Color(0, 50, 100, 0),
    ),
    "detail_time_2": Style(
        font_name="LXGW",
        font_size=8,
        color=Color(120, 120, 120, 0),
    ),
    "detail_tags_2": Style(
        font_name="LXGW",
        font_size=8,
        color=Color(100, 100, 100, 0),
    ),

    # ---- 节详情描述样式 ----
    "detail_description": Style(
        font_name="LXGW",
        font_size=10,
        color=Black,
    ),

    # ---- 个人总结样式 ----
    "summary_text": Style(
        font_name="LXGW",
        font_size=10,
        color=Black,
    ),

    # ---- 重点突出信息 ----
    # 一条显著突出的信息行（如「5 年后端开发经验」）：比正文大一档、加粗、深色底
    "highlight_text": Style(
        font_name="LXGW",
        font_size=13,
        bold=True,
        color=White,
        fill_color=Color(0, 80, 160, 0),
    ),

    # ---- 分条目：正文与引导符 ----
    "bullet_text": Style(
        font_name="LXGW",
        font_size=10,
        color=Black,
    ),
    "bullet_mark": Style(
        font_name="LXGW",
        font_size=10,
        color=Color(0, 80, 160, 0),
    ),
}


# ============================================================================
# 3. 结果句柄 (Handle)
# ============================================================================
# 每个句柄持有本模板实例的公开部件。部件名只用于调试/兼容查找，
# 正常取用一律走属性 —— 这是"不再靠字符串连接"的关键。


@dataclass
class SplitHandle:
    """
    纵向分栏子模板句柄。

    `cells` 是按顺序排列的各栏。左右两栏是它的特例（cell 数 = 2），
    为便于阅读保留了 `left` / `right` 两个便捷属性。
    """
    node: LayoutObject              # 分栏容器
    cells: List[LayoutObject]       # 各栏，按从左到右排列

    @property
    def content(self) -> LayoutObject:
        return self.node

    @property
    def left(self) -> LayoutObject:
        return self.cells[0]

    @property
    def right(self) -> LayoutObject:
        return self.cells[-1]

    def __len__(self) -> int:
        return len(self.cells)

    def __getitem__(self, i):
        return self.cells[i]


@dataclass
class ProfileHandle:
    """个人信息模板（图标 + 文本）句柄"""
    node: LayoutObject
    split: LayoutObject
    icon_range: LayoutObject
    icon: ImageObject
    text_range: LayoutObject
    text: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, text: str = "", image_path: str = "") -> 'ProfileHandle':
        """就地填充文本与图标。image_path 为空则不改动图标。"""
        self.text.set_text(text)
        if image_path:
            self.icon.set_image(image_path)
        return self


@dataclass
class PhotoHandle:
    """证件照模板句柄"""
    node: LayoutObject
    photo: ImageObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, image_path: str) -> 'PhotoHandle':
        self.photo.set_image(image_path)
        return self


@dataclass
class TitleHandle:
    """节标题模板（图标 + 标题 + 分隔线）句柄"""
    node: LayoutObject
    split: LayoutObject
    icon_range: LayoutObject
    icon: ImageObject
    text_range: LayoutObject
    text: TextObject
    divider: RectangleObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, title: str = "", image_path: str = "") -> 'TitleHandle':
        self.text.set_text(title)
        if image_path:
            self.icon.set_image(image_path)
        return self


@dataclass
class DetailHeadHandle:
    """详情·标题三栏子模板句柄（关键词 / 时间 / 标签）"""
    node: LayoutObject
    band: LayoutObject
    col_key: LayoutObject
    col_time: LayoutObject
    col_tags: LayoutObject
    key: TextObject
    during_time: TextObject
    tags: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, key: str = "", during_time: str = "",
             tags: str = "") -> 'DetailHeadHandle':
        self.key.set_text(key)
        self.during_time.set_text(during_time)
        self.tags.set_text(tags)
        return self


@dataclass
class DetailBodyHandle:
    """详情·描述子模板句柄"""
    node: LayoutObject
    description: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, description: str = "",
             description_height: Optional[float] = None) -> 'DetailBodyHandle':
        """
        就地填充描述。

        description_height 为 None（默认）时由内容自动结算
        （`SizeY.CONTENT` + 引擎真实文本测量）；给值则退回固定高度模式。
        """
        self.description.set_text(description)
        set_content_height(self.description, description_height)
        return self


@dataclass
class DetailsHandle:
    """节详情模板句柄（标题三栏 + 描述），由 head / body 两个子句柄组成"""
    node: LayoutObject
    head: DetailHeadHandle
    body: DetailBodyHandle

    # ---- 便捷转发：保持旧的属性访问方式可用 ----
    @property
    def content(self) -> LayoutObject:
        return self.node

    @property
    def brief(self) -> LayoutObject:
        return self.head.node

    @property
    def col_key(self) -> LayoutObject:
        return self.head.col_key

    @property
    def col_time(self) -> LayoutObject:
        return self.head.col_time

    @property
    def col_tags(self) -> LayoutObject:
        return self.head.col_tags

    @property
    def key(self) -> TextObject:
        return self.head.key

    @property
    def during_time(self) -> TextObject:
        return self.head.during_time

    @property
    def tags(self) -> TextObject:
        return self.head.tags

    @property
    def details(self) -> LayoutObject:
        return self.body.node

    @property
    def description(self) -> TextObject:
        return self.body.description

    def fill(self, key: str = "", during_time: str = "", tags: str = "",
             description: str = "",
             description_height: Optional[float] = None) -> 'DetailsHandle':
        """就地填充四段文字（转发给 head 与 body）。"""
        self.head.fill(key=key, during_time=during_time, tags=tags)
        self.body.fill(description=description,
                       description_height=description_height)
        return self

    def apply(self, data: Any) -> 'DetailsHandle':
        """
        用一条数据对象填充本实例。

        兼容带 `key` / `during_time` / `tags` / `description` /
        `description_height` 字段的 dict 或 dataclass（如 ResumeCore.Details）。
        """
        get = _field_getter(data)
        return self.fill(
            key=get("key", ""),
            during_time=get("during_time", ""),
            tags=get("tags", ""),
            description=get("description", ""),
            description_height=get("description_height", None),
        )


@dataclass
class SummaryHandle:
    """个人总结模板句柄"""
    node: LayoutObject
    details: LayoutObject
    description: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, description: str = "",
             description_height: Optional[float] = None) -> 'SummaryHandle':
        self.description.set_text(description)
        set_content_height(self.description, description_height)
        return self

    def apply(self, data: Any) -> 'SummaryHandle':
        get = _field_getter(data)
        return self.fill(
            description=get("description", ""),
            description_height=get("description_height", None),
        )


@dataclass
class ParaDeferredHandle(DetailsHandle):
    """
    `add_detail(desc_mode="para")` 专用的句柄。

    **为什么需要它**：`add_detail` 的 `description` 参数只是"顺手填入"的便利，
    真正的数据通路是 `add_detail(...).apply(item)` / `.fill(...)` ——
    也就是说建模板时正文往往还是空的。若在构造时就按 `description` 拆段，
    后到的 `apply` 只能改写那个占位文本对象，**一段都建不出来**。
    （实测症状：body 下只剩占位 `_description`，总高从 25.5 变成 46。）

    因此这里把"拆段建段落"延后到 `fill()`：谁先拿到正文谁来建，
    之后重复 fill 则就地更新已有段落。

    `body.description` 不再放一个空的占位文本对象，而是**指向第一段的正文**
    （没有段落时为 None）。这样"描述"这个语义仍指得到真实文字，
    也不会在树里多出一个高度为 0、会误导高度断言的空节点。
    """
    _body_node: Optional[LayoutObject] = None
    _para_gap: float = 1.0
    _para_kwargs: Optional[dict] = None
    _layer: int = 0
    _paras: List['ParaHandle'] = field(default_factory=list)
    _first_prefix: Optional[str] = None

    @property
    def description(self) -> Optional[TextObject]:
        return self._paras[0].text if self._paras else None

    def fill(self, key: str = "", during_time: str = "", tags: str = "",
             description: str = "",
             description_height: Optional[float] = None) -> 'ParaDeferredHandle':
        self.head.fill(key=key, during_time=during_time, tags=tags)
        self._build_paras(description or "")
        return self

    def _build_paras(self, description: str) -> None:
        lines = [s for s in description.split("\n") if s.strip()]
        if not lines:
            return
        # 数量一致就地更新（幂等），否则重建
        if len(lines) == len(self._paras):
            for h, ln in zip(self._paras, lines):
                h.fill(text=ln)
            return
        for h in self._paras:
            if h.node.parent is not None:
                h.node.parent.remove_child(h.node)
        self._paras = []
        gap_name = f"{self._body_node.name}_para_gap"
        for old in list(self._body_node.children):
            if old.name.startswith(gap_name):
                self._body_node.remove_child(old)
        for k, ln in enumerate(lines):
            # 第一段沿用 {prefix}_description（与 inline 模式的主描述节点同名），
            # 这样顶层的命名式断言在两种模式下都成立。
            if k == 0 and self._first_prefix:
                _nm, _sfx = self._first_prefix, "description"
            else:
                _nm, _sfx = f"{self._body_node.name}_para_{k}", "content"
            self._paras.append(
                self._body_node.add_para(text=ln, layer=self._layer, name=_nm,
                                         name_suffix=_sfx,
                                         **(self._para_kwargs or {})))
            if self._para_gap > 0 and k < len(lines) - 1:
                self._body_node.add_spacer(f"{gap_name}_{k}", self._para_gap)


@dataclass
class HighlightHandle:
    """
    重点突出信息行句柄。

    一条显著突出的单行信息（如「5 年后端开发经验」）：整行带底色、字号更大、加粗。
    """
    node: LayoutObject
    text: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, text: str = "") -> 'HighlightHandle':
        self.text.set_text(text)
        return self


@dataclass
class BulletHandle:
    """
    分条目句柄。

    `mark` 是正方形引导符位（可能是 ImageObject、TextObject 或空色块），
    `text` 是该条目的正文。行高由正文按可用宽折行后的实际高度决定。
    """
    node: LayoutObject            # 整行容器
    mark_cell: LayoutObject       # 引导符所占的正方形格
    text_cell: LayoutObject       # 正文格
    text: TextObject              # 正文
    mark: Optional[LayoutObject]  # 引导符对象（图片 / 文字 / None）

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, text: str = "") -> 'BulletHandle':
        self.text.set_text(text)
        return self


@dataclass
class BulletListHandle:
    """批量分条目句柄：一次挂出的所有条目"""
    node: LayoutObject                 # 条目们共同挂载的父节点
    rows: List[BulletHandle]           # 按传入顺序

    @property
    def content(self) -> LayoutObject:
        return self.node

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, i) -> BulletHandle:
        return self.rows[i]


@dataclass
class ParaHandle:
    """
    图标段落句柄（左栏图标 + 右栏文本）。

    与 `BulletHandle` 的区别：这里左栏是**满高的图标栏**（宽 = 图标宽），
    图标在其中按左栏内边距与自身对齐摆放；而 `BulletHandle` 的左栏是
    对准正文首行的正方形引导符。
    """
    node: LayoutObject              # 整行容器
    left: LayoutObject              # 左栏（图标栏，满高）
    icon: ImageObject               # 图标（正方形）
    right: LayoutObject             # 右栏（正文栏，占满剩余宽高）
    text: TextObject                # 正文

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, text: str = "", icon: str = "") -> 'ParaHandle':
        """就地替换正文与图标（图标留空表示不改）"""
        self.text.set_text(text)
        if icon:
            self.icon.set_image(icon)
        return self


@dataclass
class SectionHandle:
    """组合模板（节标题 + N 条详情）句柄"""
    node: Optional[LayoutObject]
    title: Optional[TitleHandle]
    details: List[DetailsHandle]

    @property
    def content(self) -> Optional[LayoutObject]:
        return self.node


# ============================================================================
# 3b. 文字呈现配置（对齐 / 行距 / 断行禁则）
# ============================================================================

@dataclass(frozen=True)
class TextConfig:
    """
    "这段文字在框里怎么摆"的配置。

    各模板已经给了**合理的默认值**（如详情三栏默认盒内垂直居中），
    本对象用于**按需覆盖**：字段为 None 表示"不改动模板的默认"。

    它只影响渲染与测量，**不影响布局几何** —— 对齐不参与 `measure`，
    所以调它不会挪动盒子，也就不会打乱版面。

    各模板里的参数名是 **`text_cfg=`**（不叫 `text=`，因为 `add_info` /
    `add_highlight` / `add_text_row` 已经有一个字符串参数叫 `text`）。

    字段：
        align_x: 文字水平对齐 (AlignX)
        align_y: 文字盒内垂直对齐 (AlignY)。⭐ 最常用：
                 `VCENTER` 让文字在框内垂直居中，`BOTTOM` 贴底
        line_height_ratio: 行高系数（行高 = 字号 × 此值，默认 1.2）
        break_policy: 断行禁则 (BreakPolicy)

    Example:
        >>> col.add_detail_body(prefix="p", description="……",
        ...                     text_cfg=TextConfig(line_height_ratio=1.5))
        >>> col.add_text_row(name="n", text="x",
        ...                  text_cfg=TextConfig(align_y=AlignY.BOTTOM))
        >>> col.add_detail(..., text_cfg=TextConfig(align_y=AlignY.VCENTER),
        ...                time_align=TextConfig(align_y=AlignY.TOP))  # 时间单独贴顶
    """
    align_x: Optional[AlignX] = None
    align_y: Optional[AlignY] = None
    line_height_ratio: Optional[float] = None
    break_policy: Optional[BreakPolicy] = None

    def apply(self, obj) -> None:
        """
        把非 None 的字段写进对象；None 的字段保持对象原样。

        只写**对象确实拥有**的属性 —— 因此对 ImageObject（没有
        line_height_ratio / break_policy）或 None 调用都是安全的。
        """
        if obj is None:
            return
        for name in ("align_x", "align_y", "line_height_ratio", "break_policy"):
            val = getattr(self, name)
            if val is not None and hasattr(obj, name):
                setattr(obj, name, val)


# ============================================================================
# 3c. 留白（纵向间距）集中定义
# ============================================================================

@dataclass(frozen=True)
class Spacing:
    """
    简历的**全部纵向留白**集中在一处，像宏一样可改、可整体缩放。

    **为什么需要它**：留白此前散在三处 ——
      · 各模板的参数（`title_detail_gap` / `between_details_gap` / `para_gap` / `gap`）
      · 顶层的 `Lead` 字典
      · 以及若干"谁都没加"的缺口（如节标题与直挂内容之间实测 0.00mm）
    同一概念两处命名，改一处不知道另一处要不要改。

    现在：**这里定义，各层取用**。

    命名规则：`<区域>_<上元素>_<下元素>`，或 `between_<同类>`。
    单位一律 mm；**0 表示不留白**（模板会跳过 spacer 的创建）。

    ## 整体缩放（对应"内容多少"的宏观取舍）

        Spacing().scaled(0.8)     # 全部留白 × 0.8 —— 内容多时塞得下
        Spacing().scaled(1.3)     # 内容少时排布更均匀
        Spacing.compact()/loose() # 常用档位（0.7 / 1.3）

    例：
        >>> res = Resume(..., spacing=Spacing.loose())
        >>> res.Generate(spacing=Spacing().scaled(0.85))
    """

    # ---- 左栏 ----
    left_top: float = 10.0                  # 左栏顶部
    photo_name: float = 5.0                 # 证件照 ↔ 姓名
    name_contacts: float = 5.0              # 姓名 ↔ 联系方式
    between_contacts: float = 5.0           # 联系方式之间
    contacts_skills: float = 5.0            # 联系方式 ↔ 技能/证书/荣誉
    between_skills: float = 5.0             # 技能/证书/荣誉三块之间
    left_bottom: float = 5.0                # 左栏底部

    # ---- 右栏 ----
    right_top: float = 10.0                 # 右栏顶部
    section_title_to_body: float = 0.0      # 节标题 ↔ 该节首个内容。
                                            # 默认 0（2026-10-13 用户要求：其它留白默认 0）。
                                            # 需要留白的节**逐个指定** —— 传给
                                            # add_section_heading(gap_after=…) 或
                                            # add_section(title_detail_gap=…)。
                                            # 直挂内容时必须显式给，否则实测 0.00mm
    between_paras: float = 1.0              # 图标段落之间
    detail_head_to_body: float = 0.0        # 详情三栏（关键词/时间/标签）↔ 描述体
    between_details: float = 5.0            # 节内相邻详情之间
    between_sections: float = 5.0           # 节之间
    right_bottom: float = 5.0               # 右栏底部

    # ---- 分条目 ----
    between_bullets: float = 0.0            # 分条目之间（0 = 紧贴）

    # ---- 派生值 ----
    def scaled(self, factor: float) -> 'Spacing':
        """全部留白乘以 factor —— 用于按内容多少整体调松紧"""
        return dataclasses.replace(
            self, **{f.name: getattr(self, f.name) * factor
                     for f in dataclasses.fields(self)})

    @classmethod
    def compact(cls) -> 'Spacing':
        """紧凑档：内容多、要往一页里塞"""
        return cls().scaled(0.7)

    @classmethod
    def loose(cls) -> 'Spacing':
        """宽松档：内容少、要排布均匀"""
        return cls().scaled(1.3)

    def as_lead(self) -> Dict[str, float]:
        """
        导出为顶层 `Lead` 字典的键（历史命名）。

        用途：`Resume` 的间距设置仍以 `Lead` 为对外形式（已入库的调用点不动），
        内部改由本对象供值，从而"一处定义、整体可缩放"。
        """
        return {
            "Left_Column_Above_All": self.left_top,
            "Left_Column_Below_Photo_Avove_Name": self.photo_name,
            "Left_Column_Below_Name_Above_Contacts": self.name_contacts,
            "Left_Column_Between_Contacs": self.between_contacts,
            "Left_Column_Below_Contacts_Above_Skills&Awards": self.contacts_skills,
            "Left_Column_Between_Skills&Awards": self.between_skills,
            "Left_Column_Below_All": self.left_bottom,
            "Right_Column_Above_All": self.right_top,
            "Right_Column_Between_SectionTitle_SectionDetails":
                self.section_title_to_body,
            "Right_Column_Between_Sections": self.between_sections,
            "Right_Column_Between_Details": self.between_details,
            "Right_Column_Below_All": self.right_bottom,
        }

    def describe(self) -> str:
        """一行摘要，便于在日志里确认当前档位"""
        vals = [getattr(self, f.name) for f in dataclasses.fields(self)]
        return (f"Spacing(共 {len(vals)} 项，合计 {sum(vals):.1f}mm，"
                f"非零 {sum(1 for v in vals if v > 0)} 项)")


# ============================================================================
# 4. 内部工具
# ============================================================================

def _field_getter(data: Any):
    """
    生成一个取字段的函数，同时支持 dict 与 dataclass/普通对象。

    取不到时返回 default —— 数据类未必带 description_height 这类排版字段。
    """
    if isinstance(data, dict):
        def get(name, default=None):
            return data.get(name, default)
    else:
        def get(name, default=None):
            return getattr(data, name, default)
    return get


def set_content_height(obj: LayoutObject, height: Optional[float]) -> LayoutObject:
    """
    决定一个对象的纵向尺寸方式。

    height 为 None / 0  -> `SizeY.CONTENT`：高度由内容自动结算（推荐）
    height 为正值       -> `SizeY.FIXED`：使用给定高度

    注意必须写公开属性 `height`，直接写 `_height` 会绕过尺寸方式解析
    （见 TECHNICAL.md 3.4b 的迁移注意）。
    """
    if height is None or height <= 0:
        obj.size_y = SizeY.CONTENT
        # 尺寸方式已是 CONTENT，height setter 不会把它改回 FIXED
        obj.height = 0
    else:
        obj.height = float(height)
    return obj


def _resolve_ratio(ratio: Optional[Sequence[float]],
                   default: Sequence[float]) -> List[float]:
    """比例列表归一化：None 取默认值，并校验元素非负、总和为正。"""
    values = [float(r) for r in (ratio if ratio is not None else default)]
    if not values:
        raise ValueError("比例列表不能为空")
    if any(r < 0 for r in values):
        raise ValueError(f"比例不能为负数：{values}")
    if sum(values) <= 0:
        raise ValueError(f"比例之和必须大于 0：{values}")
    return values


# ============================================================================
# 5. 子模板：挂在任意节点上调用的方法
# ============================================================================
# 这些函数会在导入本模块时被挂到 LayoutObject 上（见第 8 节），
# 因此调用形式是 `节点.add_xxx(...)`，而不是 `add_xxx(节点, ...)`。


def add_split(self: LayoutObject,
              ratio: Optional[Sequence[float]] = None,
              widths: Optional[Sequence[float]] = None,
              colors: Optional[Sequence[Optional[Color]]] = None,
              paddings: Optional[Sequence[Optional[Padding]]] = None,
              insets: Optional[Sequence[float]] = None,
              layer: int = 0) -> SplitHandle:
    """
    纵向分栏子模板 —— 把挂载点的内容区横向切成 N 栏。

    结构：
        self
        └─ {self.name}_split_container
             ├─ {self.name}_cell_0   （给了 colors[0] 就是 RectangleObject，否则 LayoutObject）
             ├─ {self.name}_cell_1
             └─ ...

    宽度分配（三选一，优先级从高到低）：
        widths   —— 直接指定各栏宽度 (mm)，总和超出则等比缩小
        ratio    —— 按比例分配（默认 [1.0, 2.5]，即左右两栏）
        colors   —— 都不给时按 N 等宽

    Args:
        ratio: 各栏比例。与 widths 互斥
        widths: 各栏宽度 (mm)。与 ratio 互斥
        colors: 各栏填充色。某栏给 None 则该栏是透明容器（LayoutObject），
                给了颜色则是实心色块（RectangleObject）
        paddings: 各栏内边距
        insets: 各栏左缩进 (mm)。实现为"整栏右移 + 宽度同步收窄"，
                等价于在栏内左侧留白且不侵占右侧
        layer: 图层索引

    Returns:
        SplitHandle —— cells[0] 是最左栏；len(handle) 即栏数
    """
    if ratio is not None and widths is not None:
        raise ValueError("add_split: ratio 与 widths 互斥，只能给一个")

    _, _, content_w, content_h = self.get_content_area()
    if content_w <= 0:
        raise ValueError(f"add_split: 挂载点 '{self.name}' 没有可用宽度，无法分栏")

    # ---- 决定栏数与各栏宽度 ----
    if widths is not None:
        widths = [float(w) for w in widths]
        n = len(widths)
        if n == 0:
            raise ValueError("add_split: widths 不能为空")
        total = sum(widths)
        if total > content_w and total > 0:
            k = content_w / total
            widths = [w * k for w in widths]
    else:
        ratio = _resolve_ratio(ratio, DEFAULT_RATIO)
        n = len(ratio)
        total = sum(ratio)
        widths = [content_w * r / total for r in ratio]

    colors = list(colors) if colors is not None else [None] * n
    paddings = list(paddings) if paddings is not None else [None] * n
    insets = list(insets) if insets is not None else [0.0] * n
    for name, seq in (("colors", colors), ("paddings", paddings), ("insets", insets)):
        if len(seq) != n:
            raise ValueError(f"add_split: {name} 长度必须等于栏数 {n}")

    # ---- 造各栏 ----
    cells: List[LayoutObject] = []
    for i in range(n):
        pad = paddings[i]
        inset = float(insets[i] or 0.0)
        # 缩进做成内边距：栏内容区本身收窄，子元素不会溢出
        pad = Padding.all(0) if pad is None else pad
        if inset:
            pad = Padding(left=pad.left + inset, top=pad.top,
                          right=pad.right, bottom=pad.bottom)
        cls = RectangleObject if colors[i] is not None else LayoutObject
        cell = cls(
            name=f"{self.name}_cell_{i}",
            x=0, y=0, width=widths[i], height=0,
            color=colors[i] if colors[i] is not None else White,
            padding=pad,
            align_x=AlignX.NONE,
            align_y=AlignY.NONE,
            layer=layer,
        )
        cells.append(cell)

    band = create_band(
        parent=self,
        cells=cells,
        gap=0,
        padding=Padding.all(0),
        height=content_h,
        layer=layer,
        container_name=f"{self.name}_split_container",
    )
    return SplitHandle(node=band, cells=cells)


def add_basic(self: LayoutObject,
              ratio: Optional[Sequence[float]] = None,
              left_padding: Optional[Padding] = None,
              right_padding: Optional[Padding] = None,
              layer: int = 0) -> SplitHandle:
    """
    基础模板 —— 左右分栏（`add_split` 的双栏预设）。

    结构：
        self
        └─ {self.name}_split_container
             ├─ {self.name}_left_column   : RectangleObject（底色 = STYLES["left_column"]）
             └─ {self.name}_right_column  : LayoutObject

    Args:
        ratio: 左右比例，默认 [1.0, 2.5]
        left_padding: 左栏内边距，默认 Padding.all(0)
        right_padding: 右栏内边距，默认 Padding.left(5)
        layer: 图层索引

    Returns:
        SplitHandle —— left / right 是 cells 的便捷访问。
    """
    _, _, content_w, content_h = self.get_content_area()
    if content_w <= 0:
        raise ValueError(f"add_basic: 挂载点 '{self.name}' 没有可用宽度，无法分栏")

    ratio = _resolve_ratio(ratio, DEFAULT_RATIO)
    left_padding = Padding.all(0) if left_padding is None else left_padding
    right_padding = Padding.left(5) if right_padding is None else right_padding

    left_column = RectangleObject(
        name=f"{self.name}_left_column",
        x=0, y=0, width=0, height=0,
        color=STYLES["left_column"].fill_color,
        padding=left_padding,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    right_column = LayoutObject(
        name=f"{self.name}_right_column",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=right_padding,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )

    # 宽度按比例定死，再作为"已构造格子"交给 create_band 排放。
    total = sum(ratio)
    left_column.width = content_w * ratio[0] / total
    right_column.width = content_w * ratio[1] / total

    band = create_band(
        parent=self,
        cells=[left_column, right_column],
        gap=0,
        padding=Padding.all(0),
        height=content_h,
        layer=layer,
        container_name=f"{self.name}_split_container",
    )
    return SplitHandle(node=band, cells=[left_column, right_column])


def add_info(self: LayoutObject,
             index: int = 0,
             variant: str = "contact",
             text: str = "",
             image_path: str = "",
             icon_style: Optional[Style] = None,
             text_style: Optional[Style] = None,
             icon_width: Optional[float] = None,
             gap: float = 0,
             content_height: Optional[float] = None,
             row_inset: float = DEFAULT_ROW_INSET,
             text_cfg: Optional[TextConfig] = None,
             layer: int = 0) -> ProfileHandle:
    """
    个人信息行子模板（图标 + 文本），一行两格。

    **一套模板覆盖姓名行与基础信息行** —— 两者形状完全一致，差别只是默认样式：
    用 `variant` 选择预设，任何一项都能用显式参数覆盖。

    结构：
        self
        └─ {self.name}_info_{index}_content : LayoutObject（FLOW）
             └─ ..._split : LayoutObject（横带，左侧缩进）
                  ├─ ..._icon_range → ..._icon : ImageObject
                  └─ ..._text_range → ..._text : TextObject

    Args:
        index: 实例索引（同一挂载点上多个实例必须互不相同）
        variant: 预设。`"name"` 用姓名的字号与图标尺寸；`"contact"` 用基础信息的
        text: 文本内容。非空则在返回前直接填入（等价于再调一次 `.fill()`）
        image_path: 图标路径。非空则直接填入
        icon_style: 图标样式。None 时按 variant 取
        text_style: 文本样式。None 时按 variant 取（显式给值优先于 variant）
        icon_width: 左格宽 (mm)。None 时按 variant 取
        gap: 两格间距 (mm)
        content_height: 整行高度。None 表示按"文本最小高 / 图标占高"推算
        row_inset: 行左侧缩进 (mm)，横带宽度同步收窄
        layer: 图层索引

    Returns:
        ProfileHandle
    """
    if variant not in ("name", "contact"):
        raise ValueError(f"add_info: variant 只能是 'name' 或 'contact'，收到 {variant!r}")
    if variant == "name":
        default_text_style = STYLES["name_text"]
        default_icon_width = DEFAULT_ICON_WIDTH + 2.0      # 姓名行图标用 6mm
    else:
        default_text_style = STYLES["profile_text"]
        default_icon_width = DEFAULT_ICON_WIDTH

    # 显式参数优先于 variant 预设
    text_style = default_text_style if text_style is None else text_style
    if icon_width is None:
        icon_width = default_icon_width
    icon_style = STYLES["name_image"] if icon_style is None else icon_style
    if content_height is None:
        content_height = profile_content_height(text_style, icon_width)

    prefix = f"{self.name}_info_{index}"

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=content_height,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(content)

    icon = ImageObject.from_style(
        f"{prefix}_icon", icon_style,
        width=icon_width, height=icon_width,
        keep_aspect_ratio=True,
        fit_mode="cover",          # 与历史行为一致（旧版此处硬编码 cover）
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.VCENTER,
        layer=layer + 1,
    )
    text_obj = TextObject.from_style(
        f"{prefix}_text", text_style,
        text="",                   # 由 fill() 填充
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.LEFT,
        align_y=AlignY.VCENTER,
        multi_line=False,
        layer=layer + 1,
    )

    # 横带：左格定宽图标、右格占满剩余。
    #
    # 缩进**必须做成行容器的内边距**，不能靠"把横带右移 + 手动收窄"：
    # create_band 会按"父内容区宽"重算自己的宽度与各格位置，与手动定的值打架，
    # 结果是横带按住户外框宽 54.29 铺开、文本右溢出 23mm。
    # 做成内边距后，行内容区本身就是 51.29，"图标 4 + 文本 47.29" 自然落在界内，
    # 且与旧版（split 容器带 Padding.left(3)）的几何逐项一致。
    #
    # content_height 是 FIXED，给容器加内边距不会改变它的外框高，
    # 撑不住的是"内边距 + 内容"，而这里内容（图标 6mm / 文本 7mm）本来就够小。
    content.padding = Padding(left=row_inset)
    row_inner_w = max(content.get_content_area()[2], 0.0)
    cell_w = icon_width + gap
    ratio = [cell_w, row_inner_w - cell_w] if row_inner_w > cell_w > 0 else [1.0, 1.0]

    band = create_band(
        parent=content,
        cells=ratio,
        gap=0,
        padding=Padding.all(0),
        height=content_height,
        names=[f"{prefix}_icon_range", f"{prefix}_text_range"],
        layer=layer,
        container_name=f"{prefix}_split",
    )
    # 旧版 split 容器居中于 content，故横带 x 恒为 0
    band.x = 0

    icon_range, text_range = band.children[0], band.children[1]
    icon_range.add_child(icon)
    text_range.add_child(text_obj)

    handle = ProfileHandle(
        node=content, split=band,
        icon_range=icon_range, icon=icon,
        text_range=text_range, text=text_obj,
    )
    # 文字对齐/行距：模板已给默认（图标与文字均盒内居中），text_cfg 只在需要时覆盖
    if text_cfg is not None:
        text_cfg.apply(icon)
        text_cfg.apply(text_obj)

    # text / image_path 非空时直接填入，省掉调用方再写一次 .fill(...)
    if text or image_path:
        handle.fill(text=text, image_path=image_path)
    return handle


def add_photo(self: LayoutObject,
              index: int = 0,
              icon_style: Optional[Style] = None,
              photo_width: float = DEFAULT_PHOTO_WIDTH,
              image_path: str = "",
              layer: int = 0) -> PhotoHandle:
    """
    生成证件照模板。

    结构：
        self
        └─ {self.name}_photo_{index}_content
             └─ ..._photo : ImageObject（居中）

    ⚠️ 节点名前缀刻意用 `photo_` 而非 `profile_photo_`：后者会与
       add_profile 的 `{self.name}_profile_{index}_content` 撞名
       （`profile_photo_0_content` 与 `profile_0_content` 在旧的
        "profile_photo" 命名下曾互相覆盖注册表条目）。

    Returns:
        PhotoHandle
    """
    icon_style = STYLES["profile_photo"] if icon_style is None else icon_style
    prefix = f"{self.name}_photo_{index}"

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=photo_width * PHOTO_ASPECT,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(content)

    photo = ImageObject.from_style(
        f"{prefix}_photo", icon_style,
        width=photo_width, height=0,
        keep_aspect_ratio=True,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.VCENTER,
        layer=layer + 1,
    )
    # 直接挂到 content 下（旧版构造时传 parent=self，与真实父元素不一致，易误导）
    content.add_child(photo)

    handle = PhotoHandle(node=content, photo=photo)
    if image_path:
        handle.fill(image_path)
    return handle


def add_section_heading(self: LayoutObject,
                        index: int = 0,
                        icon_style: Optional[Style] = None,
                        text_style: Optional[Style] = None,
                        icon_width: float = DEFAULT_TITLE_ICON_WIDTH,
                        gap: float = 0,
                        height: float = DEFAULT_TITLE_HEIGHT,
                        title: str = "",
                        image_path: str = "",
                        text_cfg: Optional[TextConfig] = None,
                        gap_after: float = 0.0,
                        layer: int = 0) -> TitleHandle:
    """
    生成节标题模板（图标 + 标题 + 下方分隔线）。

    结构：
        self
        └─ {self.name}_section_title_{index}_content（高 height，FLOW）
             ├─ ..._split（高 height - 分隔线粗细）
             │    ├─ ..._icon_range → ..._icon : ImageObject（BOTTOM）
             │    └─ ..._text_range → ..._text : TextObject（BOTTOM）
             └─ ..._divider : RectangleObject（BOTTOM）

    分隔线的名字**带 index**（旧版不含 index，多个节标题会互相覆盖注册表）。

    Returns:
        TitleHandle
    """
    icon_style = STYLES["section_title_image"] if icon_style is None else icon_style
    text_style = STYLES["section_title_text"] if text_style is None else text_style

    prefix = f"{self.name}_section_title_{index}"
    body_h = height - DEFAULT_DIVIDER_HEIGHT

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=height,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(content)

    icon = ImageObject.from_style(
        f"{prefix}_icon", icon_style,
        width=icon_width, height=icon_width,
        keep_aspect_ratio=True,
        fit_mode="contain",        # 与历史行为一致
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.BOTTOM,
        layer=layer + 1,
    )
    text = TextObject.from_style(
        f"{prefix}_text", text_style,
        text="",
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.LEFT,
        align_y=AlignY.BOTTOM,
        multi_line=False,
        layer=layer + 1,
    )

    split_w = content.get_content_area()[2]
    ratio = [icon_width, split_w - icon_width] \
        if split_w > icon_width > 0 else [1.0, 1.0]

    band = create_band(
        parent=content,
        cells=ratio,
        gap=gap,
        padding=Padding.all(0),
        height=body_h,
        names=[f"{prefix}_icon_range", f"{prefix}_text_range"],
        layer=layer,
        container_name=f"{prefix}_split",
    )

    icon_range, text_range = band.children[0], band.children[1]
    # 旧版左格带 Padding.bottom(3)，起到把图标上抬的视觉效果（保持原语义）
    icon_range.padding = Padding.bottom(3)
    icon_range.add_child(icon)
    text_range.add_child(text)
    if text_cfg is not None:
        text_cfg.apply(icon)
        text_cfg.apply(text)

    divider = RectangleObject(
        name=f"{prefix}_divider",
        x=0, y=0, width=0, height=DEFAULT_DIVIDER_HEIGHT,
        color=Black,
        padding=Padding.all(0),
        align_x=AlignX.NONE,
        align_y=AlignY.BOTTOM,
        layer=layer,
    )
    content.add_child(divider)

    handle = TitleHandle(
        node=content, split=band,
        icon_range=icon_range, icon=icon,
        text_range=text_range, text=text,
        divider=divider,
    )
    if title or image_path:
        handle.fill(title=title, image_path=image_path)
    # 分隔线之下的留白。默认 0（与历史行为一致）；
    # **直挂内容**的调用方（不走 add_section）应当传
    # `gap_after=Spacing().section_title_to_body`，否则标题与内容会贴在一起
    # ——实测为 0.00mm，是"技能亮点"那节看起来没有边距的原因。
    if gap_after > 0:
        self.add_spacer(f"{prefix}_below_gap", gap_after, layer=layer)
    return handle


def add_detail_head(self: LayoutObject,
                    prefix: str,
                    key: str = "",
                    during_time: str = "",
                    tags: str = "",
                    key_style: Optional[Style] = None,
                    time_style: Optional[Style] = None,
                    tags_style: Optional[Style] = None,
                    ratio: Optional[Sequence[float]] = None,
                    height: float = DEFAULT_BRIEF_HEIGHT,
                    text_cfg: Optional[TextConfig] = None,
                    key_align: Optional[TextConfig] = None,
                    time_align: Optional[TextConfig] = None,
                    tags_align: Optional[TextConfig] = None,
                    layer: int = 0) -> DetailHeadHandle:
    """
    详情·标题三栏子模板（关键词 / 时间 / 标签）。

    结构：
        {prefix}_brief（高 height，FLOW）
        └─ {prefix}_brief_band : 三栏，宽按 ratio
             ├─ {prefix}_brief_col_0 → {prefix}_key          : LEFT/VCENTER
             ├─ {prefix}_brief_col_1 → {prefix}_during_time  : CENTER/VCENTER
             └─ {prefix}_brief_col_2 → {prefix}_tags         : RIGHT/VCENTER

    Args:
        prefix: 命名前缀（由 `add_detail` 统一给出，保证详情内命名一致）
        key / during_time / tags: 三栏文字，构造时直接填入
        key_style / time_style / tags_style: 三栏样式
        ratio: 三栏宽度比例，必须恰好 3 个元素，默认 [2, 1, 2]
        height: 三栏高度 (mm)

    Returns:
        DetailHeadHandle
    """
    key_style = STYLES["detail_key_1"] if key_style is None else key_style
    time_style = STYLES["detail_time_1"] if time_style is None else time_style
    tags_style = STYLES["detail_tags_1"] if tags_style is None else tags_style
    ratio = _resolve_ratio(ratio, DEFAULT_BRIEF_RATIO)
    if len(ratio) != 3:
        raise ValueError(f"add_detail_head: ratio 必须恰好 3 个元素，当前 {ratio}")

    brief = LayoutObject(
        name=f"{prefix}_brief",
        x=0, y=0, width=0, height=height,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(brief)

    band = create_band(
        parent=brief,
        cells=list(ratio),
        gap=0,
        padding=Padding.all(0),
        height=height,
        names=[f"{prefix}_brief_col_{i}" for i in range(3)],
        layer=layer,
        container_name=f"{prefix}_brief_band",
    )
    col_key, col_time, col_tags = band.children[0], band.children[1], band.children[2]
    col_tags.padding = Padding.right(1.5)

    key_obj = TextObject.from_style(
        f"{prefix}_key", key_style,
        text=key,
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.LEFT,
        align_y=AlignY.VCENTER,
        multi_line=False,
        layer=layer + 1,
    )
    time_obj = TextObject.from_style(
        f"{prefix}_during_time", time_style,
        text=during_time,
        width=0, height=0,
        color=White,
        # ⚠️ 这里**不能**沿用 time_style.padding（detail_time_1 带 Padding(top=5)）。
        # 原因：本对象是 SizeY.FILL，effective_h = 父容器高（= 带高），
        # 引擎按 inner_h = eff_h - padding 算纵向居中量，于是那 5mm 顶内边距
        # 会把文字**整体下推** 5mm，破坏与左右两格的视觉对齐。
        # 实测（带高 10mm）：沿用 padding 时三格基线为 5.00/6.48/5.00（极差 1.48mm）。
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.VCENTER,
        multi_line=False,
        layer=layer + 1,
    )
    tags_obj = TextObject.from_style(
        f"{prefix}_tags", tags_style,
        text=tags,
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.RIGHT,
        align_y=AlignY.VCENTER,
        multi_line=False,
        layer=layer + 1,
    )
    col_key.add_child(key_obj)
    col_time.add_child(time_obj)
    col_tags.add_child(tags_obj)

    # 对齐/行距：先套用统一配置，再套用逐栏配置（后者优先），
    # 都没给就保持上面三处硬编码的默认（三栏同为 VCENTER => 基线对齐）。
    if text_cfg is not None:
        for _o in (key_obj, time_obj, tags_obj):
            text_cfg.apply(_o)
    for _cfg, _o in ((key_align, key_obj), (time_align, time_obj),
                     (tags_align, tags_obj)):
        if _cfg is not None:
            _cfg.apply(_o)

    return DetailHeadHandle(
        node=brief, band=band,
        col_key=col_key, col_time=col_time, col_tags=col_tags,
        key=key_obj, during_time=time_obj, tags=tags_obj,
    )


def add_detail_body(self: LayoutObject,
                    prefix: str,
                    description: str = "",
                    style: Optional[Style] = None,
                    height: Optional[float] = None,
                    inner_padding: Optional[Padding] = None,
                    break_policy: Optional[BreakPolicy] = None,
                    text_cfg: Optional[TextConfig] = None,
                    layer: int = 0) -> DetailBodyHandle:
    """
    详情·描述子模板（可自动换行的多行文本块）。

    结构：
        {prefix}_details（SizeY.CONTENT）
        └─ {prefix}_description : TextObject(multi_line, LEFT/FLOW)

    高度默认由内容自动结算（`SizeY.CONTENT` + 引擎真实文本测量）；
    给 `height` 则退回固定高度模式。

    Args:
        prefix: 命名前缀（由 `add_detail` 统一给出）
        description: 描述文字（支持 \\n 硬换行与内联 Markdown）
        style: 文本样式
        height: 固定高度 (mm)。None 表示自动结算
        inner_padding: 文本块**自身的内边距**，默认 `Padding.all(2)`（= 历史行为）。
                       ⚠️ 它会计入 CONTENT 高度，所以文字顶部与底部各留出该空白 ——
                       单行文本时表现就是"文字略微偏下"（盒高 = 文本高 + 上下内边距）。
                       要紧凑排版或调试对齐时传 `Padding.all(0)` 关闭。

    Returns:
        DetailBodyHandle
    """
    style = STYLES["detail_description"] if style is None else style
    if inner_padding is None:
        inner_padding = Padding.all(2)

    details = LayoutObject(
        name=f"{prefix}_details",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    # 必须由内容撑高。若留在 FILL，它处于 CONTENT 父之下会走"退化规则"
    # 去读子元素高度，而子元素此刻尚未测量 —— 整条详情会塌缩为 0 高。
    details.size_y = SizeY.CONTENT
    self.add_child(details)

    desc_obj = TextObject.from_style(
        f"{prefix}_description", style,
        text=description,
        width=0, height=0,
        color=White,
        padding=inner_padding,
        align_x=AlignX.LEFT,
        align_y=AlignY.FLOW,
        multi_line=True,
        break_policy=break_policy,
        # line_height 不显式传入：引擎按 line_height_ratio 推出行高
        layer=layer + 1,
    )
    details.add_child(desc_obj)

    if text_cfg is not None:
        text_cfg.apply(desc_obj)

    handle = DetailBodyHandle(node=details, description=desc_obj)
    set_content_height(desc_obj, height)
    return handle


def add_detail(self: LayoutObject,
               index: int = 0,
               name_key: Optional[str] = None,
               key_style: Optional[Style] = None,
               time_style: Optional[Style] = None,
               tags_style: Optional[Style] = None,
               desc_style: Optional[Style] = None,
               brief_ratio: Optional[Sequence[float]] = None,
               brief_height: float = DEFAULT_BRIEF_HEIGHT,
               description_height: Optional[float] = None,
               key: str = "",
               during_time: str = "",
               tags: str = "",
               description: str = "",
               break_policy: Optional[BreakPolicy] = None,
               text_cfg: Optional[TextConfig] = None,
               key_align: Optional[TextConfig] = None,
               time_align: Optional[TextConfig] = None,
               tags_align: Optional[TextConfig] = None,
               desc_mode: str = "inline",
               para_gap: float = 1.0,
               para_kwargs: Optional[dict] = None,
               layer: int = 0) -> DetailsHandle:
    """
    节详情子模板 —— **容器**，由"标题三栏"与"描述"两个子模板组合而成。

    结构：
        self
        └─ {p}_content（SizeY.CONTENT）
             ├─ {p}_brief（三栏，见 add_detail_head）
             └─ {p}_details → {p}_description（见 add_detail_body）

    其中 `{p}` = `{self.name}_section_details_{index if name_key is None else name_key}`。

    两个部件也可以单独使用：`add_detail_head(prefix)` / `add_detail_body(prefix)`，
    它们的 `prefix` 由调用方给出，便于自由组合。

    Args:
        index: 编号，出现在节点名中
        name_key: 命名键。给定时取代 index 参与命名，用于让**跨节**的详情
                  互不同名（如 `"{节号}_{节内序号}"`）
        key_style / time_style / tags_style / desc_style: 各部件样式
        brief_ratio: 三栏比例，必须 3 个元素
        brief_height: 三栏高度 (mm)
        description_height: 描述高度。None 表示自动结算
        key / during_time / tags / description: 四段文字，构造时直接填入

    Returns:
        DetailsHandle（`head` 与 `body` 两个子句柄都可直接取用）
    """
    desc_style = STYLES["detail_description"] if desc_style is None else desc_style
    prefix = f"{self.name}_section_details_{index if name_key is None else name_key}"

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    # 必须由内容撑高：若留在默认的 FILL，本容器会吃满整列可用高，
    # 后随的 description（CONTENT）拿到的约束就被挤成 0。
    content.size_y = SizeY.CONTENT
    self.add_child(content)

    head = add_detail_head(
        content, prefix,
        key=key, during_time=during_time, tags=tags,
        key_style=key_style, time_style=time_style, tags_style=tags_style,
        ratio=brief_ratio, height=brief_height,
        text_cfg=text_cfg, key_align=key_align, time_align=time_align,
        tags_align=tags_align, layer=layer,
    )

    if desc_mode == "para":
        # 描述体改用**图标段落**：先建一个与 add_detail_body 同形的空容器
        # （SizeY.CONTENT，挂着不掉队），再按 \n 逐段 add_para。
        # ⚠️ 这里**不能**先调 add_detail_body 再追加段落 —— 那样原描述节点
        #    仍会占满一段高度（实测白占 40mm），等于两套描述同时存在。
        body_node = LayoutObject(
            name=f"{prefix}_details",
            x=0, y=0, width=0, height=0,
            color=White,
            padding=Padding.all(0),
            align_x=AlignX.CENTER,
            align_y=AlignY.FLOW,
            layer=layer,
        )
        body_node.size_y = SizeY.CONTENT
        content.add_child(body_node)

        _lines = [s for s in (description or "").split("\n") if s.strip()]
        _paras = []
        _pk = dict(para_kwargs or {})
        # 若构造时就给了正文，立刻建段落；否则留给 ParaDeferredHandle.fill() 建
        if _lines:
            for _k, _ln in enumerate(_lines):
                _nm = f"{prefix}" if _k == 0 else f"{prefix}_details_para_{_k}"
                _sfx = "description" if _k == 0 else "content"
                _paras.append(body_node.add_para(text=_ln, layer=layer, name=_nm,
                                                 name_suffix=_sfx, **_pk))
                if para_gap > 0 and _k < len(_lines) - 1:
                    body_node.add_spacer(f"{prefix}_para_gap_{_k}", para_gap)
        # 不放占位文本对象：description 由 ParaDeferredHandle 转发到第一段正文。
        # 位置占位（若构造时就给了正文）也要让 description 指得到它。
        _first = _paras[0].text if _paras else None
        return ParaDeferredHandle(
            node=content, head=head,
            body=DetailBodyHandle(node=body_node, description=_first),
            _body_node=body_node, _para_gap=para_gap,
            _para_kwargs=_pk, _layer=layer, _paras=_paras,
            _first_prefix=prefix,
        )

    body = add_detail_body(
        content, prefix,
        description=description, style=desc_style,
        height=description_height, break_policy=break_policy,
        text_cfg=text_cfg, layer=layer,
    )
    return DetailsHandle(node=content, head=head, body=body)

def add_summary(self: LayoutObject,
                index: int = 0,
                desc_style: Optional[Style] = None,
                description: str = "",
                description_height: Optional[float] = None,
                layer: int = 0) -> SummaryHandle:
    """
    生成个人总结模板（只有描述，没有三栏）。

    独立命名空间 `{self.name}_summary_{index}` —— 旧版与节详情共用
    `_section_details_` 前缀，迫使调用方手工错开编号，属隐式耦合。

    Returns:
        SummaryHandle
    """
    desc_style = STYLES["summary_text"] if desc_style is None else desc_style
    prefix = f"{self.name}_summary_{index}"

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    # 必须由内容撑高（同 add_details：FILL 会吃满整列，把描述挤成 0）
    content.size_y = SizeY.CONTENT
    self.add_child(content)

    details = LayoutObject(
        name=f"{prefix}_details",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    content.add_child(details)

    desc_obj = TextObject.from_style(
        f"{prefix}_description", desc_style,
        text=description,
        width=0, height=0,
        color=White,
        padding=Padding.all(2),
        align_x=AlignX.LEFT,
        align_y=AlignY.FLOW,
        multi_line=True,
        layer=layer + 1,
    )
    details.add_child(desc_obj)

    handle = SummaryHandle(node=content, details=details, description=desc_obj)
    set_content_height(desc_obj, description_height)
    return handle


def add_text_row(self: LayoutObject,
                 name: str,
                 text: str = "",
                 style: Optional[Style] = None,
                 height: Optional[float] = None,
                 text_padding: Optional[Padding] = None,
                 row_padding: Optional[Padding] = None,
                 align_x: AlignX = AlignX.LEFT,
                 align_y: AlignY = AlignY.VCENTER,
                 multi_line: bool = False,
                 text_width: float = 0,
                 row_height_ratio: float = 0.5,
                 text_cfg: Optional[TextConfig] = None,
                 layer: int = 0) -> TextObject:
    """
    生成"一行文本块"：容器（定高、FLOW）+ 其中的文本。

    这是技能 / 证书 / 荣誉三段共用的形状，也适合任何"标题行 + 正文行"。
    旧版在顶层手抄了 3 × 2 = 6 份逐行相同的构造代码（约 200 行）。

    Args:
        name: 行名；容器为 `{name}_content`，文本为 `{name}`
        text: 行文本（多行用 \\n）
        style: 文本样式
        height: 行高。None 表示按 style 字号 × row_height_ratio 推算
        row_height_ratio: height 为 None 时的高度系数，默认 0.5（与历史行为一致）
        text_padding: 文本块内边距
        row_padding: 容器内边距
        align_x / align_y: 文本块对齐
        multi_line: 是否自动换行
        text_width: 文本块声明宽度（0 = 撑满容器）
        layer: 图层索引

    Returns:
        TextObject —— 新建的文本对象（容器可按 `{name}_content` 查找）
    """
    style = STYLES["detail_description"] if style is None else style
    if height is None:
        height = style.font_size * row_height_ratio
    row_padding = Padding.all(0) if row_padding is None else row_padding
    if text_padding is None:
        text_padding = Padding.all(0)

    content = LayoutObject(
        name=f"{name}_content",
        x=0, y=0, width=0, height=height,
        color=White,
        padding=row_padding,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(content)

    # 用 TextObject.from_style 直接构造：create_text_block 的参数表不含
    # width / size_x，而"一行文本"需要能控制宽度轴（撑满容器或定宽）。
    # height=0 的语义是 FILL —— 即撑满行容器的内容高，正是标题行/V CENTER 所需。
    block = TextObject.from_style(
        name, style,
        text=text,
        width=text_width,
        height=0,
        multi_line=multi_line,
        align_x=align_x,
        align_y=align_y,
        padding=text_padding,
        layer=layer + 1,
    )
    if text_width <= 0:
        block.size_x = SizeX.FILL
    if text_cfg is not None:
        text_cfg.apply(block)
    content.add_child(block)
    return block


# ============================================================================
# 5b. 重点突出信息行
# ============================================================================

def add_highlight(self: LayoutObject,
                  text: str = "",
                  style: Optional[Style] = None,
                  height: float = DEFAULT_HIGHLIGHT_HEIGHT,
                  padding: Optional[Padding] = None,
                  align_x: AlignX = AlignX.LEFT,
                  text_cfg: Optional[TextConfig] = None,
                  layer: int = 0) -> HighlightHandle:
    """
    重点突出信息行子模板 —— 一条显著突出的单行信息。

    用于让 HR 一眼看到的少数几条（如「5 年后端开发经验」「GPA 3.9/4.0」）。
    默认样式比正文大一档、加粗、带深色底（见 `STYLES["highlight_text"]`）。

    结构：
        self
        └─ {self.name}_highlight_{n}_content（定高、FLOW、带底色）
             └─ ..._text : TextObject（盒内垂直居中）

    Args:
        text: 文字内容，构造时直接填入
        style: 文字样式。默认 `STYLES["highlight_text"]`
        height: 行高 (mm)
        padding: 行内边距
        align_x: 文字水平对齐
        layer: 图层索引

    Returns:
        HighlightHandle
    """
    style = STYLES["highlight_text"] if style is None else style
    padding = Padding.all(0) if padding is None else padding

    # 取一个不重名的序号（同一挂载点下可放多条）
    n = sum(1 for c in self.children if "_highlight_" in c.name)
    prefix = f"{self.name}_highlight_{n}"

    content = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=height,
        color=style.fill_color,        # 底色（is_fill 调试态可见）
        padding=padding,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(content)

    text_obj = TextObject.from_style(
        f"{prefix}_text", style,
        text=text,
        width=0, height=0,
        color=style.fill_color,
        padding=Padding.all(0),
        align_x=align_x,
        align_y=AlignY.VCENTER,        # 行内垂直居中
        multi_line=False,
        layer=layer + 1,
    )
    content.add_child(text_obj)
    if text_cfg is not None:
        text_cfg.apply(text_obj)
    return HighlightHandle(node=content, text=text_obj)


# ============================================================================
# 5c. 通用分条目
# ============================================================================

def add_bullets(self: LayoutObject,
                item: str = "",
                bullet_size: float = DEFAULT_BULLET_SIZE,
                bullet_kind: str = "block",
                bullet_value: Optional[str] = None,
                bullet_style: Optional[Style] = None,
                indent: float = DEFAULT_BULLET_INDENT,
                gap: float = DEFAULT_BULLET_GAP,
                style: Optional[Style] = None,
                padding: Optional[Padding] = None,
                align_x: AlignX = AlignX.LEFT,
                text_cfg: Optional[TextConfig] = None,
                layer: int = 0) -> BulletHandle:
    """
    通用分条目子模板 —— 一行「正方形引导符 + 正文」。

    **一次挂一条**（多条请由调用方循环；需要间距时在循环里 `add_spacer`）。

    结构：
        self
        └─ ..._bullet_{n}_content（高 = 正文折行后的实际高）
             ├─ ..._mark_cell（边长 bullet_size 的正方形，竖直对准正文首行）
             │    └─ ..._mark（ImageObject / TextObject / 无）
             └─ ..._text_cell → ..._text : TextObject(multi_line)

    尺寸规则（全部实测验证）：
        · 整行宽度 = 父内容区宽（用行容器的 padding 表达左缩进）
        · 正文列宽 = 父内容区宽 − indent − bullet_size − gap
        · 行高 = 正文在该列宽下折行后的**实际高度**（随宽度自动变化）
        · 引导符竖直位置 = (首行实高 − bullet_size) / 2
          —— 使正方形中心落在正文首行中心上（实测偏差 0.00mm）；
          正文只有一行时即为整行居中

    Args:
        item: 该条目正文（支持 \n 硬换行与内联 Markdown）
        bullet_size: 正方形引导符的边长 (mm)
        bullet_kind: `"block"` 空色块 / `"text"` 文字符号 / `"image"` 图片
        bullet_value: `"text"` 时为符号字符（如 `"·"`、`"▪"`）；`"image"` 时为图片路径
        bullet_style: 引导符文字/图片的样式
        indent: 整行左缩进 (mm)
        gap: 引导符与正文之间的距离 (mm)
        style: 正文字样式。默认 `STYLES["bullet_text"]`
        padding: 正文格内边距。**它由本参数控制，`style.padding` 不参与** ——
                 本模板内部以 `Padding.all(0)` 构造文本对象，正文留白统一走这里，
                 行高也随之 = 折行实高 + `padding` 上下。默认全 0
        align_x: 正文水平对齐

    Returns:
        BulletHandle

    Raises:
        ValueError: bullet_kind 非法，或挂载点没有可用宽度
    """
    if bullet_kind not in ("block", "text", "image"):
        raise ValueError(
            f"add_bullets: bullet_kind 只能是 'block' / 'text' / 'image'，"
            f"收到 {bullet_kind!r}")
    style = STYLES["bullet_text"] if style is None else style
    bullet_style = STYLES["bullet_mark"] if bullet_style is None else bullet_style
    padding = Padding.all(0) if padding is None else padding

    # ---- 0) 定出行高系数 ----
    # ⚠️ 必须在"量行高"之前定好：本模板的行高是**量出来的**（不是引擎按
    # TextObject.line_height_ratio 现算的），所以 text_cfg 里的行高系数要提前取，
    # 事后 apply 到 TextObject 上已经晚了（对象属性变了，行高却还是旧的）。
    # 优先级：text_cfg > 样式 > 引擎默认 1.2
    lhr = None
    if text_cfg is not None:
        lhr = text_cfg.line_height_ratio
    if lhr is None:
        lhr = getattr(style, "line_height_ratio", None)
    if lhr is None:
        lhr = 1.2

    # ---- 1) 先算可用宽与正文列宽 ----
    _, _, parent_w, _ = self.get_content_area()
    if parent_w <= 0:
        raise ValueError(f"add_bullets: 挂载点 '{self.name}' 没有可用宽度")
    inner_w = max(parent_w - indent, 0.0)
    text_w = max(inner_w - bullet_size - gap, 0.0)

    # ---- 2) 量出正文折行后的实际高度与行数 ----
    # ⚠️ `wrapped_height` 走的是 `TextRun` + `measure_text` 这条路，而 `TextRun`
    # 只承载文字度量属性（text / font_name / font_size / bold / italic / color），
    # **不含 padding**。所以内边距必须在这里补上，否则带了 padding 的样式会偏矮。
    text_h = wrapped_height(item, style, text_w, line_height_ratio=lhr) \
        + padding.top + padding.bottom
    lines = wrapped_lines(item, style, text_w, line_height_ratio=lhr)
    # 单行实高（用于把引导符对准首行）：字号 × 行高系数 + 该样式的上下留白
    line_h = (style.font_size * lhr * PT_TO_MM) + padding.top + padding.bottom
    row_h = max(text_h, line_h if lines else 0.0, bullet_size)

    n = sum(1 for c in self.children if "_bullet_" in c.name)
    prefix = f"{self.name}_bullet_{n}"

    # ---- 3) 行容器：缩进做成 padding，子元素可用宽自然收窄 ----
    row = LayoutObject(
        name=f"{prefix}_content",
        x=0, y=0, width=0, height=row_h,
        color=White,
        padding=Padding(left=indent),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    self.add_child(row)

    # ---- 4) 引导符格：正方形，竖直对准正文首行 ----
    mark_y = (line_h - bullet_size) / 2
    mark_cell = LayoutObject(
        name=f"{prefix}_mark_cell",
        x=0, y=mark_y, width=bullet_size, height=bullet_size,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    row.add_child(mark_cell)

    mark: Optional[LayoutObject] = None
    if bullet_kind == "text":
        mark = TextObject.from_style(
            f"{prefix}_mark", bullet_style,
            text=bullet_value or "·",
            width=0, height=0,
            color=White,
            padding=Padding.all(0),
            align_x=AlignX.CENTER,
            align_y=AlignY.VCENTER,
            multi_line=False,
            layer=layer + 1,
        )
        mark_cell.add_child(mark)
    elif bullet_kind == "image":
        mark = ImageObject.from_style(
            f"{prefix}_mark", bullet_style,
            image_path=bullet_value or "",
            width=bullet_size, height=bullet_size,
            keep_aspect_ratio=True,
            color=White,
            padding=Padding.all(0),
            align_x=AlignX.CENTER,
            align_y=AlignY.VCENTER,
            layer=layer + 1,
        )
        mark_cell.add_child(mark)
    # block：什么都不放，靠 mark_cell 自身的底色（调试态可见）

    # ---- 5) 正文格 ----
    text_cell = LayoutObject(
        name=f"{prefix}_text_cell",
        x=bullet_size + gap, y=0, width=text_w, height=row_h,
        color=White,
        padding=padding,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    row.add_child(text_cell)

    text_obj = TextObject.from_style(
        f"{prefix}_text", style,
        text=item,
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=align_x,
        align_y=AlignY.FLOW,
        multi_line=True,
        layer=layer + 1,
    )
    text_cell.add_child(text_obj)

    if text_cfg is not None:
        text_cfg.apply(text_obj)
        text_cfg.apply(mark)          # ImageObject / TextObject / None，apply 会自行判断

    return BulletHandle(node=row, mark_cell=mark_cell, text_cell=text_cell,
                        text=text_obj, mark=mark)


# ============================================================================
# 5d. 批量分条目
# ============================================================================

def add_bullet_list(self: LayoutObject,
                    items: Sequence[Any],
                    gap: float = 0.0,
                    gap_name: str = "Bullet_Gap",
                    text_cfg: Optional[TextConfig] = None,
                    **shared) -> BulletListHandle:
    """
    批量分条目子模板 —— 一次挂出 N 条「正方形引导符 + 正文」。

    **内部就是对 `add_bullets` 的循环**，因此单条入口的一切能力（引导符三形态、
    高度按折行自适应、引导符对准正文首行、内联 Markdown 强调）在批量里同样有效。
    单条入口本身一行未改，两者可以混用。

    结构：
        self
        └─ ..._bullet_0_content   （第 1 条，见 add_bullets）
        └─ <gap_name>_0            （条间留白，仅在 gap > 0 时插入）
        └─ ..._bullet_1_content   （第 2 条）
        └─ ...

    Args:
        items: 条目列表。每项可以是
                 · 字符串 —— 直接作为正文
                 · dict     —— 本条的**独立覆盖**（键同 add_bullets 的参数名，
                               外加 `text` 表示正文），未给的键沿用 shared 与默认
        gap: 条间留白 (mm)。0 表示条间不留白。**只在条目之间插入**，
             最后一条之后不加（避免末尾多出空隙把后续内容推下去）
        gap_name: 条间留白的命名前缀
        text_cfg: 传给每一条的 TextConfig（条目内可用 `text_cfg` 键单独覆盖）
        **shared: 所有条目共用的参数（bullet_kind / bullet_value / indent /
                  style / padding / align_x / layer 等）

    Returns:
        BulletListHandle —— `.rows` 按传入顺序给出每条的 BulletHandle

    Example:
        >>> col.add_bullet_list(
        ...     items=[
        ...         "响应时间从 <c:CC0000>**320ms**</c> 降到 <c:0066CC>**95ms**</c>。",
        ...         "重构缓存层，QPS 提升 3 倍。",
        ...         {"text": "带独立符号的条目", "bullet_value": "▪", "indent": 2.0},
        ...     ],
        ...     bullet_kind="text", bullet_value="·", gap=1.5,
        ... )
    """
    rows: List[BulletHandle] = []
    n = len(items)
    for i, item in enumerate(items):
        params = dict(shared)
        if isinstance(item, dict):
            params.update(item)
            body = params.pop("text", "")
        else:
            body = "" if item is None else str(item)
        if text_cfg is not None and "text_cfg" not in params:
            params["text_cfg"] = text_cfg
        rows.append(self.add_bullets(item=body, **params))
        # 只在前 n-1 条之后加留白
        if gap > 0 and i < n - 1:
            self.add_spacer(f"{gap_name}_{i}", gap)
    return BulletListHandle(node=self, rows=rows)


# ============================================================================
# 5e. 图标段落（左栏图标 + 右栏文本）
# ============================================================================

def add_para(self: LayoutObject,
             text: str = "",
             icon: str = DEFAULT_PARA_ICON,
             icon_width: float = DEFAULT_PARA_ICON_WIDTH,
             icon_align: AlignY = AlignY.VCENTER,
             icon_anchor: str = "first_line",
             indent: float = DEFAULT_PARA_ICON_INDENT,
             gap: float = DEFAULT_BULLET_GAP,
             left_pad: Optional[Padding] = None,
             style: Optional[Style] = None,
             text_cfg: Optional[TextConfig] = None,
             padding: Optional[Padding] = None,
             align_x: AlignX = AlignX.LEFT,
             align_y: AlignY = AlignY.VCENTER,
             name: Optional[str] = None,
             name_suffix: str = "content",
             layer: int = 0) -> ParaHandle:
    """
    图标段落子模板 —— **左栏图标 + 右栏文本**，用于在大片密集信息里标出重点。

    与 `add_bullets` 的区别（两者刻意分开，几何契约不同）：

    | | `add_para`（本模板） | `add_bullets` |
    | --- | --- | --- |
    | 左栏尺寸 | **图标宽 × 行高（满高）** | 正方形小格（边长 `bullet_size`） |
    | 图标竖直位置 | **左栏内边距 + 自身对齐**决定 | **对准正文首行中心** |
    | 图标尺寸 | 独立参数（正方形） | 引导符边长 |

    结构：
        self
        └─ ..._para_{n}_content（高 = max(正文实高, 图标高 + 左栏上内边距)）
             ├─ ..._left（宽 = icon_width，FILL 满高，padding = left_pad）
             │    └─ ..._icon : ImageObject（正方形）
             └─ ..._right（宽 = 剩余，FILL 满高）
                  └─ ..._text : TextObject（自动折行，支持内联 Markdown）

    ⚠️ **为什么手工摆放而不用 `create_band`**（实测结论）：

    1. `create_band(cells=[5.0, 1.0])` 会把 `5.0` 当**比例**，得到 91.67/18.33
       而不是 5mm —— 它不支持固定像素宽；
    2. `create_band` 要求父容器内容区高为正，而 `SizeY.CONTENT` 的行在测量期
       高为 0，会直接抛
       `ValueError: create_band: 高度必须为正`。

    ⚠️ **图标必须显式给高才保持正方形**：`ImageObject(width=4, height=0,
    keep_aspect_ratio=True)` 会拿**可用高反推**（实测 5.00×6.97，不是正方形）；
    给 `height=icon_width` 才是 5.00×5.00。

    ⚠️ **行高取 `max(正文实高, 图标高 + 上内边距)`**：否则图标会溢出左格
    （实测短正文行高 4.23、图标 5.0 时溢出 2.27mm）。正文通常比图标高，
    所以这一项只在图标偏大时生效。

    Args:
        text: 正文（支持 \\n 与内联 Markdown：`**粗**`、`<c:RRGGBB>色</c>` 等）
        icon: 图标路径。**必填项，但给了一个缺省值** `DEFAULT_PARA_ICON`
        icon_width: 图标边长 = 左栏宽度 (mm)。图标按正方形处理
        icon_anchor: **图标锚在哪里**，默认 `"first_line"`：
                     `"first_line"` —— 图标**中心对齐正文首行的中心**（推荐）。
                                       由模板自动算左栏上内边距
                                       `首行高/2 − 图标高/2`，因此换字号/行高系数/图标
                                       尺寸都不会错位。此时 `icon_align` 被忽略。
                     `"cell"` —— 图标在**整个左栏**（满高）里按 `icon_align` 摆。
                                 单行时两者等价；多行时图标会跟着整块文本的中心下沉，
                                 于是**与首行错开**（实测 2 行偏 +2.37mm、3 行 +4.48mm）。
                                 需要"贴着整块居中"时用这个。
        icon_align: `icon_anchor="cell"` 时，图标在左栏内的竖直对齐
                    （TOP / VCENTER / BOTTOM）
        indent: 整行左缩进 (mm)，用行容器的内边距表达
        gap: 左栏与右栏之间的距离 (mm)
        left_pad: 左栏内边距。None 表示 `Padding(top=DEFAULT_PARA_ICON_PAD_TOP)`
        style: 正文字样式。默认 `STYLES["bullet_text"]`
        text_cfg: 正文的对齐 / 行距 / 断行禁则配置
        padding: 正文格内边距
        align_x: 正文水平对齐
        name: 整行的命名前缀。None 表示自动 {self.name}_para_{n}
        name_suffix: 整行容器的后缀名，默认 content
        align_y: **正文在行内的垂直对齐**，默认 VCENTER（盒内居中）。
                两个格子都是满高，所以文字比格子矮时会居中而不是浮在顶部；
                多行正文比图标高时行高由正文决定，居中无副作用。
                想贴顶就传 AlignY.TOP

    Returns:
        ParaHandle(node / left / icon / right / text)

    Example:
        >>> for t in paragraphs:
        ...     col.add_para(text=t, icon=".\\\\Resources\\\\icon_Project_History.png")
        >>> # 只强调最要紧的一条
        >>> col.add_para(text="<c:CC0000>**主导**</c>了千万级流量系统的重构",
        ...              icon_width=5.0, icon_align=AlignY.TOP)
    """
    icon_path = icon if icon else DEFAULT_PARA_ICON
    style = STYLES["bullet_text"] if style is None else style
    padding = Padding.all(0) if padding is None else padding
    if left_pad is None:
        left_pad = Padding(top=DEFAULT_PARA_ICON_PAD_TOP)
    if icon_anchor not in ("first_line", "cell"):
        raise ValueError(
            f"add_para: icon_anchor 只能是 'first_line' 或 'cell'，收到 {icon_anchor!r}")

    # ---- 1) 可用宽与右栏宽 ----
    _, _, parent_w, _ = self.get_content_area()
    if parent_w <= 0:
        raise ValueError(f"add_para: 挂载点 '{self.name}' 没有可用宽度")
    inner_w = max(parent_w - indent, 0.0)
    text_w = max(inner_w - icon_width - gap, 0.0)

    # ---- 2) 行高 = max(正文折行实高, 图标高 + 左栏上内边距) ----
    # 行高系数必须在这里定（本模板的行高是量出来的，不是引擎现算的）
    lhr = None
    if text_cfg is not None:
        lhr = text_cfg.line_height_ratio
    if lhr is None:
        lhr = getattr(style, "line_height_ratio", None)
    if lhr is None:
        lhr = 1.2
    # 首行实高（pt 空间的字格高换算到 mm）—— 图标的"首行对齐"以它为准
    first_line_h = style.font_size * lhr * PT_TO_MM
    if icon_anchor == "first_line":
        # 让图标**中心**落在首行中心：
        #     图标中心 = pad_top + 图标高/2            （左栏内边距 + 半个图标）
        #     首行中心 = 首行高/2
        #  => pad_top = 首行高/2 − 图标高/2
        # 这不是固定值：它随字号 / 行高系数 / 图标边长变化，所以必须算而不要手填。
        _pad_top = first_line_h / 2 - icon_width / 2
        if _pad_top < 0:
            # 需要负内边距才能把图标推到首行中心 —— 物理上做不到
            # （引擎的内容区从行顶开始，没有负内边距就压不上去）。
            # 与其静默错位几毫米，不如明确报错并给出三条出路。
            raise ValueError(
                f"add_para: icon_anchor='first_line' 要求图标中心对齐首行中心，"
                f"但图标 {icon_width:.2f}mm 比首行高 {first_line_h:.3f}mm 还大，"
                f"需要负内边距（{_pad_top:+.3f}mm）才能实现。可选：\n"
                f"  1) 把 icon_width 调到 ≤ {first_line_h:.2f}mm；\n"
                f"  2) 提高行高（style.line_height_ratio 或 text_cfg）；\n"
                f"  3) 改用 icon_anchor='cell'（图标在整块左栏里居中，"
                f"不对齐首行）")
        left_pad = Padding(top=_pad_top)
    text_h = wrapped_height(text, style, text_w, line_height_ratio=lhr) \
        + padding.top + padding.bottom
    icon_need = icon_width + left_pad.top + left_pad.bottom
    row_h = max(text_h, icon_need)

    n = sum(1 for c in self.children if "_para_" in c.name)
    prefix = name if name else f"{self.name}_para_{n}"

    # ---- 3) 行容器：缩进做成 padding；高度显式算好 ----
    # name_suffix 让调用方能给整行指定后缀。默认 content；
    # add_detail(desc_mode="para") 用 description，使第一段的主节点
    # 与 inline 模式的 {prefix}_description 同名，命名式断言两模式通用。
    row = LayoutObject(
        name=f"{prefix}_{name_suffix}",
        x=0, y=0, width=0, height=row_h,
        color=White,
        padding=Padding(left=indent),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    row.size_x = SizeX.FILL
    row.size_y = SizeY.FIXED        # 显式高：见上面 create_band 的两条限制
    self.add_child(row)

    # ---- 4) 左栏：宽 = 图标宽，满高 ----
    left = LayoutObject(
        name=f"{prefix}_left",
        x=0, y=0, width=icon_width, height=0,
        color=White,
        padding=left_pad,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    left.size_x = SizeX.FIXED
    left.size_y = SizeY.FILL
    row.add_child(left)

    icon_obj = ImageObject.from_style(
        f"{prefix}_icon",
        Style(image_path=icon_path, font_name=style.font_name,
              font_size=style.font_size),
        width=icon_width,
        height=icon_width,          # ⚠️ 显式给高才是正方形（见 docstring）
        image_path=icon_path,
        keep_aspect_ratio=True,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        # first_line 锚定时已用左栏内边距把位置算准，图标自身贴顶即可
        align_y=(AlignY.TOP if icon_anchor == "first_line" else icon_align),
        layer=layer + 1,
    )
    left.add_child(icon_obj)

    # ---- 5) 右栏：剩余宽，满高 ----
    right = LayoutObject(
        name=f"{prefix}_right",
        x=icon_width + gap, y=0, width=text_w, height=0,
        color=White,
        padding=padding,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    right.size_x = SizeX.FIXED
    right.size_y = SizeY.FILL
    row.add_child(right)

    text_obj = TextObject.from_style(
        f"{prefix}_text", style,
        text=text,
        width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=align_x,
        # 默认盒内垂直居中：本模板两个格子都是**满高**，文字比格子矮时
        # （单行正文、或图标把行高撑起来）顶对齐会显得"文字浮在上面"。
        # 多行正文比图标高时行高由正文决定，居中自然无副作用。
        align_y=align_y,
        multi_line=True,
        layer=layer + 1,
    )
    right.add_child(text_obj)

    handle = ParaHandle(node=row, left=left, icon=icon_obj,
                        right=right, text=text_obj)
    if text_cfg is not None:
        text_cfg.apply(text_obj)
    return handle


# ============================================================================
# 6. 组合模板：由子模板构成，体现"整个模板就是子模板的组合"
# ============================================================================

def add_section(self: LayoutObject,
                section: Any,
                index: int = 0,
                title_style: Optional[Style] = None,
                icon_style: Optional[Style] = None,
                detail_styles: Optional[dict] = None,
                brief_ratio: Optional[Sequence[float]] = None,
                brief_height: float = DEFAULT_BRIEF_HEIGHT,
                desc_mode: str = "inline",
                para_gap: float = 1.0,
                para_kwargs: Optional[dict] = None,
                title_detail_gap: float = 0.0,
                between_details_gap: float = 0.0,
                layer: int = 0) -> SectionHandle:
    """
    生成一个完整章节 = 节标题 + 该节全部详情（子模板的组合）。

    section 可以是 dict 或对象，需提供 `title` / `icon` / `details` 三个字段；
    `details` 中每项须能被 DetailsHandle.apply 识别（key / during_time /
    tags / description / description_height）。

    Args:
        section: 章节数据
        index: 章节索引，用于给节标题与详情编号
        title_style / icon_style: 节标题样式
        detail_styles: 传给 add_details 的样式字典，键为
                       key_style / time_style / tags_style / desc_style
        brief_ratio / brief_height: 详情三栏比例与高度
        desc_mode: **描述体的渲染方式**
                   `"inline"`（默认）—— 整段文本，与原行为逐字节一致；
                   `"para"` —— 按 `\\n` 拆成多段，每条用**图标段落**（`add_para`）排版。
                   两种模式都保留上方的三栏标题（关键词/时间/标签）。
        para_gap: `desc_mode="para"` 时相邻段落之间的留白 (mm)
        para_kwargs: `desc_mode="para"` 时透传给 `add_para` 的参数
                     （如 `icon_width` / `icon_align` / `gap` / `left_pad`）
        title_detail_gap: 节标题与第一条详情之间的留白 (mm)
        between_details_gap: 相邻详情之间的留白 (mm)
        layer: 图层索引

    Returns:
        SectionHandle —— title 与 details 都是句柄，可直接改
    """
    if desc_mode not in ("inline", "para"):
        raise ValueError(
            f"add_section: desc_mode 只能是 'inline' 或 'para'，收到 {desc_mode!r}")

    get = _field_getter(section)
    title_text = get("title", "")
    icon_path = get("icon", "")
    items = list(get("details", []) or [])
    detail_styles = detail_styles or {}

    if not items:
        return SectionHandle(node=None, title=None, details=[])

    title_handle = self.add_section_heading(
        index=index,
        icon_style=icon_style,
        text_style=title_style,
        # 留白统一由 add_section_heading 的 gap_after 负责（与直挂内容的调用方同一机制），
        # 这样"节标题到该节内容"的间距只有一个实现，不会再出现某条路径漏加。
        gap_after=title_detail_gap,
        layer=layer,
    ).fill(title=title_text, image_path=icon_path)

    handles: List[DetailsHandle] = []
    for i, item in enumerate(items):
        handle = self.add_detail(
            index=i,
            name_key=f"{index}_{i}",
            brief_ratio=brief_ratio,
            brief_height=brief_height,
            desc_mode=desc_mode,
            para_gap=para_gap,
            para_kwargs=para_kwargs,
            layer=layer,
            **detail_styles,
        ).apply(item)
        handles.append(handle)
        if i < len(items) - 1 and between_details_gap > 0:
            self.add_spacer(f"Lead_Section_{index}_Detail_{i}", between_details_gap)

    return SectionHandle(node=self, title=title_handle, details=handles)


def add_details_list(self: LayoutObject,
                     items: Iterable[Any],
                     start_index: int = 0,
                     between_gap: float = 0.0,
                     **detail_kwargs) -> List[DetailsHandle]:
    """
    列表入口 —— 用同一份蓝图实例化 N 条详情（结构化信息的批量落地）。

    Args:
        items: 数据序列，每项须能被 DetailsHandle.apply 识别
        start_index: 起始编号，便于与别的模板错开命名空间
        between_gap: 相邻详情之间的留白 (mm)
        **detail_kwargs: 透传给 add_details（样式、比例等）

    Returns:
        List[DetailsHandle]，与 items 一一对应。
    """
    items = list(items)
    handles: List[DetailsHandle] = []
    for i, item in enumerate(items):
        index = start_index + i
        handle = self.add_detail(index=index, **detail_kwargs).apply(item)
        handles.append(handle)
        if i < len(items) - 1 and between_gap > 0:
            self.add_spacer(f"Lead_DetailsList_{index}", between_gap)
    return handles


def add_spacer(self: LayoutObject,
               name: str,
               height: float,
               layer: int = 0) -> LayoutObject:
    """在 self 之下添加一段流式留白（引擎 create_spacer 的方法风格包装）。"""
    return create_spacer(name=name, height=height, parent=self, layer=layer)


# ============================================================================
# 7. 便捷样式字典
# ============================================================================

BRIEF_DETAIL_STYLES = {
    "key_style": STYLES["detail_key_1"],
    "time_style": STYLES["detail_time_1"],
    "tags_style": STYLES["detail_tags_1"],
    "desc_style": STYLES["detail_description"],
}


# ============================================================================
# 8. 挂载为 LayoutObject 的方法
# ============================================================================
#
# 模板必须知道 Style / STYLES / 章节 / 详情这些**简历词汇**，而 LayoutObject
# 住在底层、不认这些词 —— 因此方法不能在 LayoutEngine.py 里定义。
# 这里在导入本模块时把它们挂到 LayoutObject 上，得到 `节点.add_xxx(...)` 的
# 调用形式，同时保持引擎对领域词汇零知识。

_TEMPLATE_METHODS = {
    "add_split": add_split,
    "add_basic": add_basic,
    "add_info": add_info,
    "add_photo": add_photo,
    "add_section_heading": add_section_heading,
    "add_detail": add_detail,
    "add_detail_head": add_detail_head,
    "add_detail_body": add_detail_body,
    "add_highlight": add_highlight,
    "add_bullets": add_bullets,
    "add_bullet_list": add_bullet_list,
    "add_para": add_para,
    "add_section": add_section,
    "add_text_row": add_text_row,
    "add_spacer": add_spacer,
}

# 已退役的模板（保留函数定义供过渡期参考，但**不再挂到 LayoutObject 上**）：
#   add_summary      —— 用 add_detail_body(prefix=...) 取代
#   add_details_list —— 用调用方自己的循环 + add_detail(...) 取代
# 退役后调用 `obj.add_summary(...)` 会得到 AttributeError，这就是"新名不留旧名"。


def _install_methods() -> None:
    for _name, _func in _TEMPLATE_METHODS.items():
        _existing = getattr(LayoutObject, _name, None)
        if _existing is not None and _existing is not _func:
            raise RuntimeError(f"LayoutObject 上已存在名为 {_name} 的成员，拒绝覆盖")
        setattr(LayoutObject, _name, _func)


_install_methods()


# ============================================================================
# 9. 测试入口
# ============================================================================

if __name__ == "__main__":
    # DSH_RESUME_SMOKE=1：只验“能否生成”，跳过自检断言（供资源降级测试用）
    _SMOKE = os.environ.get("DSH_RESUME_SMOKE") == "1"
    from fpdf import FPDF

    print("=" * 60, flush=True)
    print("简历模板层 - 综合测试（方法风格 API）", flush=True)
    print("=" * 60, flush=True)

    # ---- 1. 创建 PDF ----
    pdf = FPDF()
    pdf.add_page()

    # ---- 2. 注册中文字体 ----
    try:
        pdf.add_font("LXGW", "", ".\\Resources\\LXGWWenkai-Regular.ttf")
        pdf.add_font("LXGW", "B", ".\\Resources\\LXGWWenkai-Bold.ttf")
        print("✅ 已加载霞鹜文楷字体", flush=True)
    except Exception as e:
        print(f"⚠️ 加载字体失败: {e}", flush=True)
        print("   将使用 Helvetica 字体", flush=True)

    # ---- 3. 创建根布局 ----
    root = LayoutObject(
        name="Root",
        x=0, y=0, width=210, height=297,
        color=White,
        padding=Padding.all(10),
        layer=0,
    )

    # ---- 4. 基础模板：句柄直接给出左右栏 ----
    print("\n【4. 生成基础模板】", flush=True)
    basic = root.add_split(
        ratio=[1.0, 2.5],
        colors=[STYLES["left_column"].fill_color, None],
        paddings=[Padding.all(0), Padding.left(8)],
        layer=0,
    )
    left_column, right_column = basic.left, basic.right
    print(f"  ✅ 分栏容器: {basic.node.name}（{len(basic)} 栏）", flush=True)
    print(f"  ✅ 左栏: {left_column.name}, 右栏: {right_column.name}", flush=True)

    # ---- 5. 左栏：个人信息 ----
    print("\n【5. 生成个人信息模板】", flush=True)
    profile = left_column.add_info(
        index=0,
        variant="name",
        text="韩 梅 梅",
        image_path=".\\Resources\\icon_Profile_Name.png",
        layer=1,
    )
    print(f"  ✅ 个人信息: {profile.node.name} → {profile.text.get_text()}", flush=True)

    # 联系方式：同一个蓝图复用 N 次
    contacts = [
        (".\\Resources\\telephone.png", "138-0000-0000"),
        (".\\Resources\\email.png", "hanmeimei@ex.com"),
    ]
    for i, (icon_path, value) in enumerate(contacts, start=1):
        left_column.add_info(
            index=i,
            text=value,
            image_path=icon_path,
            layer=1,
        )
    print(f"  ✅ 联系方式 {len(contacts)} 条（蓝图复用）", flush=True)

    # ---- 6. 右栏：节标题 + 节详情 ----
    print("\n【6. 生成右栏内容】", flush=True)

    # 留白统一取自 Spacing（中层唯一真相源）。
    # 想整体调松紧：换成 Spacing.compact() / Spacing.loose() / Spacing().scaled(k)
    _SP = Spacing()
    # 各节"标题分隔线之下"的留白：**逐节指定**，默认 0。
    # 想给某一节单独留白，只改这一个数字即可。
    _TITLE_GAP = {
        "技能亮点": 3.0,      # 这一节单独留白
    }
    # 图标分段的公共参数：左栏宽 = 图标宽、整行不额外缩进（右栏本身有内边距）
    # 不传 icon_align —— 图标默认按 first_line 锚定（对齐正文首行），
    # icon_align 只在 icon_anchor="cell" 时生效。
    _PARA_KW_ARGS = {"icon_width": 4.0, "indent": 0.0, "gap": 2.0}

    edu_title = right_column.add_section_heading(
        index=0,
        icon_style=STYLES["section_title_image"],
        text_style=STYLES["section_title_text"],
        title="教育背景",
        gap_after=_TITLE_GAP.get("教育背景", _SP.section_title_to_body),
        image_path=".\\Resources\\icon_Education_History.png",
        # 标题分隔线之下的留白 —— 直挂内容的节必须自己给，否则实测 0.00mm
        layer=1,
    )
    print(f"  ✅ 节标题: {edu_title.node.name} → {edu_title.text.get_text()}", flush=True)

    # 多条详情 = 调用方自己的循环（同一个蓝图实例化 N 次）
    edu_items = [
        {
            "key": "日本农业苞谷大学",
            "during_time": "2020.09 - 2024.06",
            "tags": "金坷垃制造与苞米发酵工程 | 本科",
            "description": "主修课程：数据结构与算法、操作系统、计算机网络、数据库原理、软件工程。\n毕业论文：基于深度学习的图像分类算法研究。",
        },
        {
            "key": "XX高中",
            "during_time": "2017.09 - 2020.06",
            "tags": "理科实验班",
            "description": "高考成绩：全省前 5%，数学 148/150。",
        },
    ]
    edu_details = [
        right_column.add_detail(
            index=i,
            brief_ratio=[2.0, 1.0, 2.0],
            brief_height=DEFAULT_BRIEF_HEIGHT,
            # 描述体用**图标段落**（黑圆点 + 文本）而非整段文本
            desc_mode="para",
            para_gap=1.0,
            para_kwargs=_PARA_KW_ARGS,
            layer=1,
            **item,
            **BRIEF_DETAIL_STYLES,
        )
        for i, item in enumerate(edu_items)
    ]
    print(f"  ✅ 教育经历 {len(edu_details)} 条"
          f"（调用方循环 + 图标分段）", flush=True)

    proj_title = right_column.add_section_heading(
        index=1,
        icon_style=STYLES["section_title_image"],
        text_style=STYLES["section_title_text"],
        title="项目经历",
        gap_after=_TITLE_GAP.get("项目经历", _SP.section_title_to_body),
        image_path=".\\Resources\\icon_Project_History.png",
        # 标题分隔线之下的留白 —— 直挂内容的节必须自己给，否则实测 0.00mm
        layer=1,
    )

    proj_items = [
        {
            "key": "Python 文档排版系统",
            "during_time": "2025.03 - 2025.06",
            "tags": "Python, FPDF, 排版引擎",
            "description": "设计并实现了一套基于 Python 的 PDF 简历自动生成系统。\n系统采用分层排版引擎，支持样式定制、多模板切换、自动分栏等高级功能。\n实现了简历元件的模块化管理，支持快速生成针对不同岗位的定制化简历。",
        },
        {
            "key": "数据可视化看板开发",
            "during_time": "2024.09 - 2024.12",
            "tags": "Vue.js, ECharts, Flask",
            "description": "为某电商公司开发了实时数据监控看板，展示销售、流量、转化等核心指标。\n使用 WebSocket 实现实时数据更新，日活用户 200+。",
        },
    ]
    proj_details = [
        right_column.add_detail(
            index=len(edu_details) + i,
            brief_ratio=[2.0, 1.0, 2.0],
            desc_mode="para",
            para_gap=1.0,
            para_kwargs=_PARA_KW_ARGS,
            layer=1,
            **item,
            **BRIEF_DETAIL_STYLES,
        )
        for i, item in enumerate(proj_items)
    ]
    print(f"  ✅ 项目经历 {len(proj_details)} 条（图标分段）", flush=True)

    # ---- 6b. 直接调用 add_para：图标段落模板的公共入口 ----
    # 上面两节是"由 add_detail 的 desc_mode='para' 间接使用"；
    # 这里演示**直接调用** —— 这个模板可以挂在任何节点下
    # （左栏、右栏、任意容器都行），用于在密集信息里标出重点。
    print("\n【6b. 直接调用 add_para（图标段落）】", flush=True)

    demo_title = right_column.add_section_heading(
        index=2,
        icon_style=STYLES["section_title_image"],
        text_style=STYLES["section_title_text"],
        title="技能亮点",
        gap_after=_TITLE_GAP.get("技能亮点", _SP.section_title_to_body),
        image_path=".\\Resources\\icon_Project_History.png",
        # 标题分隔线之下的留白 —— 直挂内容的节必须自己给，否则实测 0.00mm
        layer=1,
    )
    print(f"  ✅ 节标题: {demo_title.text.get_text()}", flush=True)

    para_demos = [
        # 普通一条：默认黑圆点 + 盒内垂直居中
        right_column.add_para(
            text="熟练使用 <c:0066CC>**Python**</c> 与 <c:0066CC>**FPDF**</c>，"
                 "独立完成排版引擎的实现。",
            layer=1,
        ),
        right_column.add_para(
            text="把订单接口的响应时间从 <c:CC0000>**320ms**</c> 压到 "
                 "<c:CC0000>**95ms**</c>，并支撑大促三倍峰值。",
            layer=1,
        ),
        # 强调最要紧的一条：用颜色 + 加粗，而不是放大图标
        # （图标一旦大于首行高就无法对齐首行中心，模板会明确报错）
        right_column.add_para(
            text="<c:CC0000>**主导**</c>了千万级流量系统的重构。",
            layer=1,
        ),
    ]
    print(f"  ✅ add_para {len(para_demos)} 条"
          f"（含行内彩色加粗的强调条目）", flush=True)

    # ---- 7. 渲染与高度结算 ----
    print("\n【7. 渲染 PDF】", flush=True)
    root.layout(pdf=pdf, force=True)
    root.render(pdf, is_fill=False)

    # ---- 7b. 详情标题三栏的基线探针（必须在 pdf.output() 之前做）----
    # 用一个独立的小树渲染一次，抓 pdf.cell 的真实落点。
    # 之所以放在这里：pdf.output() 会终结文档，之后不能再渲染。
    #
    # ⚠️ **探针绝不能落到产物上**。曾经的写法是把探针树直接 render 到本 pdf，
    #    结果往第 1 页顶部画了一份三栏复制品（实测多了 3 段文字，落点 y≈2.25/3.52/3.31），
    #    看起来就像"时间字段跑到页顶去了"。
    #    现在改用 _ProbePdf：一个**只记录、不落笔**的代理 ——
    #    cell() 只记账不绘制，rect()/颜色设置一律吞掉，
    #    set_font 转发给真 pdf（它只改内部状态、不写内容流，且字体度量必须是真的）。
    _bh_root = LayoutObject(name="BH_Root", width=200, height=50,
                            padding=Padding.all(0), layer=0)
    _bh_root.add_detail_head(
        prefix="BH", height=DEFAULT_BRIEF_HEIGHT,
        key="日本农业苞谷大学", during_time="2020.09 - 2024.06",
        tags="金坷垃制造与苞米发酵工程 | 本科",
        key_style=BRIEF_DETAIL_STYLES["key_style"],
        time_style=BRIEF_DETAIL_STYLES["time_style"],
        tags_style=BRIEF_DETAIL_STYLES["tags_style"],
    )
    _bh_root.layout(pdf=pdf, force=True)

    class _ProbePdf:
        """只记录 cell 落点、不向文档写任何内容的代理"""

        def __init__(self, target):
            self._t = target
            self.cells = []
            self._xy = (0.0, 0.0)

        def set_xy(self, x, y):
            self._xy = (float(x), float(y))
            return None

        def cell(self, w=0, h=0, txt="", *a, **kw):
            self.cells.append((self._xy[0], self._xy[1], float(h), str(txt)))
            return None

        # 绘制类：吞掉
        def rect(self, *a, **kw):
            return None

        def set_fill_color(self, *a, **kw):
            return None

        def set_text_color(self, *a, **kw):
            return None

        # 字体类：转发给真 pdf（只改内部状态；get_string_width 等要真实度量）
        def __getattr__(self, name):
            return getattr(self._t, name)

    _probe = _ProbePdf(pdf)
    with contextlib.redirect_stdout(io.StringIO()):
        _bh_root.render(_probe, is_fill=False)
    _cell_recs = _probe.cells
    
    # ---- 7c. TextConfig 可控性探针（同样必须在 pdf.output() 之前）----
    def _head_probe(**kw):
        """渲染一次详情三栏，返回 (三栏基线列表, 几何)，供断言核对"""
        _r = LayoutObject(name="TC_Root", width=200, height=40,
                          padding=Padding.all(0), layer=0)
        _h = _r.add_detail_head(
            prefix="TC", height=DEFAULT_BRIEF_HEIGHT,
            key="日本农业苞谷大学", during_time="2020.09 - 2024.06",
            tags="金坷垃制造与苞米发酵工程 | 本科",
            key_style=BRIEF_DETAIL_STYLES["key_style"],
            time_style=BRIEF_DETAIL_STYLES["time_style"],
            tags_style=BRIEF_DETAIL_STYLES["tags_style"], **kw)
        _r.layout(pdf=pdf, force=True)
        _p = _ProbePdf(pdf)
        with contextlib.redirect_stdout(io.StringIO()):
            _r.render(_p, is_fill=False)
        _geo = (_h.node.get_effective_height(), _h.band.get_effective_height())
        return [(y + h / 2.0) for (_x, y, h, _t) in _p.cells], _geo

    _tc_base, _tc_geo = _head_probe()
    _tc_time, _tc_geo2 = _head_probe(time_align=TextConfig(align_y=AlignY.TOP))
    _tc_all, _tc_geo3 = _head_probe(text_cfg=TextConfig(align_y=AlignY.TOP))
    _tc_lhr, _tc_geo4 = _head_probe(text_cfg=TextConfig(line_height_ratio=2.0))
    
    output_path = "resume_template_v2_test.pdf"
    pdf.output(output_path)
    print(f"\n✅ PDF 已生成: {output_path}", flush=True)

    if _SMOKE:
        print("\n【smoke 模式】已生成，跳过自检断言（DSH_RESUME_SMOKE=1）")
        raise SystemExit(0)

    # ---- 8. 回归契约断言 ----
    print("\n【8. 回归契约断言】", flush=True)

    # 8.1 方法已挂到 LayoutObject 上
    for _m in ("add_split", "add_basic", "add_info", "add_photo",
               "add_section_heading", "add_detail",
               "add_detail_head", "add_detail_body",
               "add_section", "add_text_row", "add_spacer"):
        assert hasattr(LayoutObject, _m), f"LayoutObject 缺少方法 {_m}"
    for _old in ("add_profile", "add_profile_photo", "add_section_title",
                 "add_details", "add_details_list", "add_summary"):
        assert not hasattr(LayoutObject, _old), f"旧方法 {_old} 应已退役"
    print("  ✅ 方法挂载契约通过（并确认旧名已退役）", flush=True)

    # 8.2 句柄代替字符串查询：不查名字也能拿到部件
    assert edu_details[0].key.get_text() == "日本农业苞谷大学"
    assert edu_details[1].tags.get_text() == "理科实验班"
    assert profile.text.get_text() == "韩 梅 梅"
    assert edu_title.text.get_text() == "教育背景"
    print("  ✅ 句柄取用契约通过（零字符串查询）", flush=True)

    # 8.3 左右栏挂载正确
    assert left_column.parent is not None, "左栏应挂在分栏容器下"
    assert right_column.parent is not None, "右栏应挂在分栏容器下"
    print("  ✅ 基础模板左右栏挂载契约通过", flush=True)

    # 8.4 分隔线名字带 index：多个节标题不再互相覆盖注册表
    assert right_column.find_by_name(f"{right_column.name}_section_title_0_divider") is not None
    assert right_column.find_by_name(f"{right_column.name}_section_title_1_divider") is not None
    print("  ✅ 分隔线命名含 index（旧缺陷已消除）", flush=True)

    # 8.5 描述体已改为**图标段落**（desc_mode="para"）：正文落在 add_para 上
    _p_nodes = [n for n in edu_details[0].body.node.children
                if "_para_" in n.name]
    assert _p_nodes, "para 模式下描述体下应有 _para_ 段落节点"
    _desc_h = edu_details[1].description.get_effective_height()
    assert _desc_h > 0, f"描述有效高应为正，实际 {_desc_h}"
    # 段落文本是 FILL（满高，靠 align_y 居中），而不再是 CONTENT 的整段文本
    assert edu_details[0].description.align_y is AlignY.VCENTER, \
        "para 模式下段落正文应在行内垂直居中"
    assert edu_details[0].description.line_height_ratio == 1.2, \
        "段落正文行高应走引擎默认 1.2"
    print(f"  ✅ 描述体 = 图标段落（{len(_p_nodes)} 个段落节点，"
          f"正文高 {_desc_h:.2f}mm）", flush=True)

    # 8.6 段落之间的留白只在**段落之间**（n 段 → n-1 个）
    _body_kids = edu_details[0].body.node.children
    _gaps = [c for c in _body_kids if "_para_gap_" in c.name]
    # 段落 = 整行容器（名含 _para_ 或 _description 且不是留白）
    _n_para = len([c for c in _body_kids
                   if "_para_gap_" not in c.name
                   and ("_para_" in c.name or c.name.endswith("_description"))])
    assert _n_para >= 2, f"本用例应有多个段落，实际 {_n_para}"
    assert len(_gaps) == _n_para - 1, \
        f"{_n_para} 段之间应有 {_n_para - 1} 个留白，实际 {len(_gaps)}"
    print(f"  ✅ 段落留白正确（{_n_para} 段 → {len(_gaps)} 个留白，末段之后不加）",
          flush=True)

    # 8.7 详情容器由内容撑高
    assert all(d.node.size_y is SizeY.CONTENT for d in edu_details), \
        "详情容器应由内容撑高"
    print("  ✅ 详情容器高度自动结算", flush=True)

    # 8.8 分栏尺寸契约
    _lc_w = left_column.get_effective_width()
    _rc_w = right_column.get_effective_width()
    _root_content_w = root.get_content_area()[2]
    assert _lc_w > 0 and _rc_w > 0, f"两栏有效宽应为正，实际 {_lc_w} / {_rc_w}"
    assert _lc_w + _rc_w <= _root_content_w + 1e-6, \
        f"两栏宽度之和 {_lc_w + _rc_w} 超出 Root 内容宽 {_root_content_w}"
    print(f"  ✅ 分栏尺寸契约通过（左 {_lc_w:.1f} + 右 {_rc_w:.1f} <= {_root_content_w:.1f}）", flush=True)

    # 8.9 同一父元素下不得有同名兄弟
    for _parent in (right_column, left_column):
        _names = [c.name for c in _parent.children]
        _dup = {n for n in _names if _names.count(n) > 1}
        assert not _dup, f"{_parent.name} 下存在同名兄弟：{sorted(_dup)}"
    print("  ✅ 无同名兄弟", flush=True)

    # ---- 9. 新增模板：重点突出行 / 通用分条目 ----
    print("\n【9. 重点突出行 与 通用分条目】", flush=True)

    _hl = right_column.add_highlight(text="5 年后端开发经验")
    _bl = right_column.add_bullets(
        item=("负责后端服务重构与性能优化，把订单接口的平均响应时间从 320ms "
              "降到 95ms，并支撑了大促期间三倍的峰值流量。"),
        bullet_kind="text", bullet_value="·", layer=1,
    )
    _bl_short = right_column.add_bullets(item="单行短条目。",
                                         bullet_kind="text", bullet_value="·", layer=1)
    root.layout(pdf=pdf, force=True)

    # 9.1 重点突出行：整行定高、文字盒内垂直居中、带上色样式
    _hl_info = _hl.node.get_layout_info()
    assert _hl_info["size_mode"]["y"] == "fixed", "重点行应为定高"
    assert abs(_hl.node.get_effective_height() - DEFAULT_HIGHLIGHT_HEIGHT) < 1e-6, \
        f"重点行高应为 {DEFAULT_HIGHLIGHT_HEIGHT}，实际 {_hl.node.get_effective_height()}"
    assert _hl.text.align_y is AlignY.VCENTER, "重点行文字应盒内垂直居中"
    assert _hl.text.font_size == STYLES["highlight_text"].font_size
    print(f"  ✅ 重点突出行通过（高 {_hl.node.get_effective_height():.2f}mm，"
          f"字号 {_hl.text.font_size:.0f}pt，文字居中）", flush=True)

    # 9.2 分条目：行高随折行自适应，且不溢出父宽
    _rows = [(_bl, 2), (_bl_short, 1)]
    for _h, _min_lines in _rows:
        _row = _h.node
        _t = _h.text
        _lines = wrapped_lines(_t.get_text(), STYLES["bullet_text"],
                               _t.get_effective_width())
        assert _lines >= _min_lines, f"折行数应 >= {_min_lines}，实际 {_lines}"
        _expected = _lines * STYLES["bullet_text"].font_size * 1.2 * PT_TO_MM
        assert abs(_row.get_effective_height() - _expected) < 0.01, (
            f"行高应等于折行实高 {_expected:.2f}，实际 {_row.get_effective_height():.2f}")
        _right = _t.get_absolute_x() + _t.get_effective_width()
        _row_right = _row.get_absolute_x() + _row.get_effective_width()
        assert _right <= _row_right + 0.01, "正文不得溢出整行"
    print(f"  ✅ 分条目高度自适应通过（长条目 {_bl.node.get_effective_height():.2f}mm / "
          f"2 行 → 短条目 {_bl_short.node.get_effective_height():.2f}mm / 1 行）", flush=True)

    # 9.3 引导符：正方形，且中心落在正文首行中心上（这是本模板的核心契约）
    for _h in (_bl, _bl_short):
        _mc = _h.mark_cell
        assert abs(_mc.get_effective_width() - _mc.get_effective_height()) < 1e-6, \
            "引导符必须是正方形"
        _line_h = STYLES["bullet_text"].font_size * 1.2 * PT_TO_MM
        _first_center = _h.text.get_absolute_y() + _line_h / 2
        _mark_center = _mc.get_absolute_y() + _mc.get_effective_height() / 2
        assert abs(_mark_center - _first_center) < 0.01, (
            f"引导符中心应落在正文首行中心：偏差 {_mark_center - _first_center:+.3f}mm")
    print("  ✅ 引导符对首行中心对齐通过（偏差 < 0.01mm；单行时即整行居中）", flush=True)

    # 9.4 引导符三种形态都可构造
    _b_img = right_column.add_bullets(
        item="带图片引导符的条目。", bullet_kind="image",
        bullet_value=".\\Resources\\icon_Project_History.png", layer=1)
    assert _b_img.mark is not None and isinstance(_b_img.mark, ImageObject)
    _b_block = right_column.add_bullets(item="空色块引导符。", bullet_kind="block", layer=1)
    assert _b_block.mark is None
    try:
        right_column.add_bullets(item="x", bullet_kind="bogus")
        raise AssertionError("非法 bullet_kind 应当报错")
    except ValueError:
        pass
    print("  ✅ 引导符三形态通过（text / image / block，非法值报错）", flush=True)

    # 9.5 批量入口 add_bullet_list
    _bl_root = LayoutObject(name="BL_Root", width=120, height=400,
                            padding=Padding.all(0), layer=0)
    _bl_long = ("响应时间从 <c:CC0000>**320ms**</c> 降到 <c:0066CC>**95ms**</c>，"
                "并支撑大促期间三倍的峰值流量，同时把错误率压到万分之一以下。")
    _bl = _bl_root.add_bullet_list(
        items=[
            _bl_long,
            "单行条目。",
            {"text": "独立覆盖的条目", "bullet_value": "#", "indent": 3.0},
        ],
        bullet_kind="text", bullet_value="·", gap=1.5,
    )
    _bl_root.layout(pdf=pdf, force=True)
    assert len(_bl) == 3, f"应挂出 3 条，实际 {len(_bl)}"
    assert [b.node.name for b in _bl] == \
        [f"BL_Root_bullet_{i}_content" for i in range(3)], \
        f"条目命名应按顺序：{[b.node.name for b in _bl]}"
    # 条间留白只在条目之间（3 条 => 2 个），末条之后不得多出空隙
    _gaps = [c for c in _bl_root.children if "Bullet_Gap" in c.name]
    assert len(_gaps) == 2, f"3 条之间应有 2 个留白，实际 {len(_gaps)}"
    _sibling_names = [c.name for c in _bl_root.children]
    assert len(_sibling_names) == len(set(_sibling_names)), \
        f"同层不得重名：{_sibling_names}"
    # 逐条覆盖生效：第三条的符号与缩进与其余不同
    assert _bl[2].mark is not None and _bl[2].mark.get_text() == "#", \
        "逐条 bullet_value 覆盖应生效"
    assert _bl[0].text.get_effective_width() > _bl[2].text.get_effective_width(), \
        "第三条 indent=3.0 更大，正文列宽应更窄"
    print(f"  ✅ 批量入口通过（3 条 + 2 个条间留白，逐条覆盖生效）", flush=True)

    # 9.6 行高系数必须参与**行高测算**（本模板的行高是量出来的，不是引擎现算的）
    #     曾经的缺陷：text_cfg 事后才 apply 到 TextObject，对象属性变了、行高却没变。
    _lhr_root = LayoutObject(name="LHR_Root", width=120, height=400,
                             padding=Padding.all(0), layer=0)
    _lhr_a = _lhr_root.add_bullets(item=_bl_long, bullet_kind="text",
                                   bullet_value="·")
    _lhr_b = _lhr_root.add_bullets(item=_bl_long, bullet_kind="text",
                                   bullet_value="·",
                                   text_cfg=TextConfig(line_height_ratio=1.5))
    _lhr_root.layout(pdf=pdf, force=True)
    _ha, _hb = _lhr_a.node.get_effective_height(), _lhr_b.node.get_effective_height()
    assert _hb > _ha + 0.5, (
        f"行高系数 1.5 应让行高明显变大（1.2 时为 {_ha:.2f}），实际 {_hb:.2f}")
    assert abs(_hb / _ha - 1.5 / 1.2) < 0.02, \
        f"行高比应约等于系数比 1.25，实际 {_hb / _ha:.3f}"
    print(f"  ✅ 行高系数参与测算通过（{_ha:.2f} -> {_hb:.2f}mm，比值 "
          f"{_hb / _ha:.2f}）", flush=True)

    # 9.7 图标段落 add_para（左栏图标 + 右栏文本）
    _p_root = LayoutObject(name="P_Root", width=110.0, height=400,
                           padding=Padding.all(0), layer=0)
    _P_TEXT = ("系统采用<c:CC0000>**分层排版引擎**</c>，支持样式定制、"
               "多模板切换、自动分栏等高级功能。")
    with contextlib.redirect_stdout(io.StringIO()):
        _p = _p_root.add_para(text=_P_TEXT, icon_width=4.0,
                              indent=1.0, gap=2.0)
        _p_root.layout(pdf=pdf, force=True)
    _pr = _p.node.get_layout_info()["effective"]
    _pl = _p.left.get_layout_info()["effective"]
    _pi = _p.icon.get_layout_info()["effective"]
    _prr = _p.right.get_layout_info()["effective"]
    _pt = _p.text.get_layout_info()["effective"]
    # 左栏宽 = 图标宽、左栏满高
    assert abs(_pl["w"] - 4.0) < 0.01, f"左栏宽应=图标宽 4.0，实际 {_pl['w']:.2f}"
    assert abs(_pl["h"] - _pr["h"]) < 0.01, "左栏应占满行高"
    # 右栏 = 剩余宽，且满高
    assert abs(_prr["w"] - (110.0 - 1.0 - 4.0 - 2.0)) < 0.01, \
        f"右栏宽应为 容器-缩进-图标-gap = 103.0，实际 {_prr['w']:.2f}"
    assert abs(_prr["h"] - _pr["h"]) < 0.01, "右栏应占满行高"
    # 图标必须是正方形（width=height 显式给高才有可能）
    assert abs(_pi["w"] - _pi["h"]) < 0.01, \
        f"图标应保持正方形，实际 {_pi['w']:.2f}x{_pi['h']:.2f}"
    # 正文不得溢出右栏
    assert _pt["x"] + _pt["w"] <= _prr["x"] + _prr["w"] + 0.01, "正文溢出右栏"
    # 行高由正文主导（正文比图标高）
    assert abs(_pr["h"] - wrapped_height(_P_TEXT, STYLES["bullet_text"],
                                         _pt["w"])) < 0.01, \
        f"行高应由正文折行实高决定，实际 {_pr['h']:.2f}"
    print(f"  ✅ 图标段落几何通过（左栏 {_pl['w']:.1f}×{_pl['h']:.2f} 满高 / "
          f"图标 {_pi['w']:.1f}×{_pi['h']:.1f} 正方 / 右栏 {_prr['w']:.1f})", flush=True)

    # 9.8 icon_anchor="cell" 时，图标在整块左栏里按 icon_align 摆
    #     （默认 icon_anchor="first_line" 会忽略 icon_align，见 9.11）
    _tops = {}
    for _al in (AlignY.TOP, AlignY.VCENTER, AlignY.BOTTOM):
        _r2 = LayoutObject(name=f"P2_{_al.name}", width=110.0, height=100,
                           padding=Padding.all(0), layer=0)
        with contextlib.redirect_stdout(io.StringIO()):
            _h2 = _r2.add_para(text=_P_TEXT, icon_anchor="cell",
                               icon_width=3.0, icon_align=_al)
            _r2.layout(pdf=pdf, force=True)
        _tops[_al] = _h2.icon.get_absolute_y() - _h2.node.get_absolute_y()
    assert _tops[AlignY.TOP] < _tops[AlignY.VCENTER] < _tops[AlignY.BOTTOM], \
        f"三种对齐的图标 y 应递增，实际 {_tops}"
    print(f"  ✅ icon_anchor=cell 的三种对齐通过（TOP/VCENTER/BOTTOM -> "
          f"{_tops[AlignY.TOP]:.2f}/{_tops[AlignY.VCENTER]:.2f}/{_tops[AlignY.BOTTOM]:.2f}mm）",
          flush=True)

    # 9.9 行高必须容纳图标：图标比正文高时，行高被图标撑起
    #     用 icon_anchor="cell"：first_line 要求图标 ≤ 首行高（见 9.13）
    _r3 = LayoutObject(name="P3", width=110.0, height=100,
                       padding=Padding.all(0), layer=0)
    with contextlib.redirect_stdout(io.StringIO()):
        _h3 = _r3.add_para(text="短", icon_width=8.0, icon_anchor="cell")
        _r3.layout(pdf=pdf, force=True)
    _need = 8.0 + DEFAULT_PARA_ICON_PAD_TOP
    assert _h3.node.get_effective_height() >= _need - 0.01, \
        (f"行高应 >= 图标高+上内边距 = {_need}，实际 "
         f"{_h3.node.get_effective_height():.2f}（否则图标溢出左栏）")
    # 图标不得溢出左栏
    assert (_h3.icon.get_absolute_y() + _h3.icon.get_effective_height()
            <= _h3.left.get_absolute_y() + _h3.left.get_effective_height() + 0.01), \
        "图标不得溢出左栏"
    print(f"  ✅ 行高容纳图标通过（图标8mm -> 行高 "
          f"{_h3.node.get_effective_height():.2f}，图标未溢出）", flush=True)

    # 9.10 缺省图标与显式覆盖
    _r4 = LayoutObject(name="P4", width=110.0, height=100,
                       padding=Padding.all(0), layer=0)
    with contextlib.redirect_stdout(io.StringIO()):
        _p_def = _r4.add_para(text="用缺省图标")
        _p_ovr = _r4.add_para(text="显式覆盖",
                              icon=".\\Resources\\icon_Education_History.png")
        _r4.layout(pdf=pdf, force=True)
    assert _p_def.icon.get_image() == DEFAULT_PARA_ICON, \
        f"缺省图标应为 {DEFAULT_PARA_ICON}，实际 {_p_def.icon.get_image()}"
    assert _p_ovr.icon.get_image().endswith("icon_Education_History.png"), \
        "显式 icon 应覆盖缺省值"
    print("  ✅ 缺省图标 / 显式覆盖通过", flush=True)

    # 9.11 图标锚定：默认 first_line —— 图标中心必须对齐**首行**中心
    _IC_TEXT = ("系统采用分层排版引擎，支持样式定制、多模板切换、自动分栏等高级功能，"
                "并支持快速生成针对不同岗位的定制化简历，覆盖完整链路。")
    for _n_lines, _txt in ((1, "单行短文本"), (2, "系统采用分层排版引擎，支持样式定制、"
                                                "多模板切换、自动分栏等高级功能。"),
                           (3, _IC_TEXT)):
        _r5 = LayoutObject(name=f"IC_{_n_lines}", width=110.0, height=100,
                           padding=Padding.all(0), layer=0)
        with contextlib.redirect_stdout(io.StringIO()):
            _h5 = _r5.add_para(text=_txt, icon_width=4.0)
            _r5.layout(pdf=pdf, force=True)
        _rt = _h5.node.get_absolute_y()
        _icon_c = _h5.icon.get_absolute_y() + _h5.icon.get_effective_height() / 2 - _rt
        _line_h = _h5.text.font_size * _h5.text.line_height_ratio * PT_TO_MM
        assert abs(_icon_c - _line_h / 2) < 0.01, (
            f"{_n_lines} 行时图标中心应=首行中心 {_line_h / 2:.3f}，"
            f"实际 {_icon_c:.3f}（偏差 {_icon_c - _line_h / 2:+.3f}mm）")
    print(f"  ✅ 图标首行对齐通过（1/2/3 行图标中心均=首行中心 "
          f"{_line_h / 2:.3f}mm，偏差 < 0.01mm）", flush=True)

    # 9.12 first_line 的物理上限：图标大于首行高时**明确报错**，不静默错位
    def _ic_probe(**kw):
        _r = LayoutObject(name="ICh_Root", width=110.0, height=100,
                          padding=Padding.all(0), layer=0)
        with contextlib.redirect_stdout(io.StringIO()):
            _h = _r.add_para(**kw)
            _r.layout(pdf=pdf, force=True)
        return _h

    try:
        _ic_probe(text="x", icon_width=5.0)       # 首行高 4.233mm < 5.0
        raise AssertionError("图标大于首行高时应报错，而不是静默错位")
    except ValueError as _e:
        assert "first_line" in str(_e), f"报错应说明 first_line 的要求：{_e}"
    _ok = _ic_probe(text="x", icon_width=5.0, icon_anchor="cell")
    assert _ok.icon.get_effective_width() == 5.0
    print("  ✅ 首行对齐上限通过（图标 > 首行高时明确报错；"
          "icon_anchor='cell' 可绕过）", flush=True)

    # 9.13 正文垂直对齐：单行 + 大图标（行高被撑起）时默认居中
    #      （此前正文是 FLOW 顶对齐，两个格子又都是满高，于是"文字浮在上面"）
    #      用 icon_anchor="cell" 是为了让图标能大于首行高（first_line 有上限，见 9.12）
    def _para_probe(**kw):
        _r = LayoutObject(name="PA_Root", width=110.0, height=100,
                          padding=Padding.all(0), layer=0)
        with contextlib.redirect_stdout(io.StringIO()):
            _h = _r.add_para(icon_anchor="cell", **kw)
            _r.layout(pdf=pdf, force=True)
        return _h

    _pa_top = _para_probe(text="单行短文本", icon_width=8.0, align_y=AlignY.TOP)
    _pa_ctr = _para_probe(text="单行短文本", icon_width=8.0)
    assert _pa_ctr.text.align_y is AlignY.VCENTER, \
        f"add_para 正文默认应为 VCENTER，实际 {_pa_ctr.text.align_y}"
    assert _pa_top.text.align_y is AlignY.TOP, "显式 align_y=TOP 应生效"
    _rowh = _pa_ctr.node.get_effective_height()
    # ⚠️ 注意：TextObject 的 effective 高是**盒子高**（本模板下满高 = 行高），
    #    不是文字实高。要核对居中量必须用 wrapped_height 算真实文字高。
    _th = wrapped_height("单行短文本", STYLES["bullet_text"],
                         _pa_ctr.text.get_effective_width())
    assert _rowh - _th > 0.5, \
        f"本用例前提：行高应明显大于文字实高（{_rowh:.2f} vs {_th:.2f}）"
    _expect_dy = (_rowh - _th) / 2
    assert _expect_dy > 0.5, f"居中量应为正，实际 {_expect_dy:.2f}"
    # 多行时行高由正文决定，居中不得产生副作用
    _pa_ml = _para_probe(text="很长的文本内容用于触发多行折行，" * 3)
    assert abs(_pa_ml.node.get_effective_height()
               - wrapped_height("很长的文本内容用于触发多行折行，" * 3,
                                STYLES["bullet_text"],
                                _pa_ml.text.get_effective_width())) < 0.01, \
        "多行时行高应由正文折行实高决定，居中无副作用"
    print(f"  ✅ 图标段落垂直对齐通过（单行+大图标 行高{_rowh:.2f}/文字{_th:.2f}"
          f" → 居中量 {_expect_dy:.2f}mm；多行时行高仍由正文决定）", flush=True)

    # ---- 9b. 留白：Spacing 对象与节标题的 gap_after ----
    # 起因（用户目视发现）：直挂内容的节，标题分隔线与首个内容之间实测 0.00mm
    # —— 因为留白只在 add_section 那条路径上加，直挂的调用方没人加。
    print("\n【9b. 留白 Spacing 与 gap_after】", flush=True)
    # 设计约定：**所有留白默认 0**，"节标题↔内容"也不例外 —— 要留白的节逐个指定。
    assert Spacing().section_title_to_body == 0.0, \
        "节标题↔内容的默认留白应为 0（逐节指定）"
    assert Spacing().detail_head_to_body == 0.0 and Spacing().between_bullets == 0.0, \
        "新增的留白项默认也应为 0"
    # scaled 必须等比缩放全部字段
    _sp0, _sp5 = Spacing(), Spacing().scaled(0.5)
    _flds = [f.name for f in dataclasses.fields(Spacing)]
    for _fn in _flds:
        assert abs(getattr(_sp5, _fn) - getattr(_sp0, _fn) * 0.5) < 1e-9, \
            f"scaled(0.5) 应把 {_fn} 减半"
    assert len(Spacing.compact().as_lead()) == 12, "as_lead 应导出 12 个 Lead 键"
    # gap_after 必须精确落到"分隔线之下"
    _g_probe = {}
    for _gap in (0.0, 3.0, 6.0):
        _gr = LayoutObject(name=f"Gap_{_gap}", width=135.0, height=200,
                           padding=Padding.all(0), layer=0)
        with contextlib.redirect_stdout(io.StringIO()):
            _gh = _gr.add_section_heading(
                index=0, text_style=STYLES["section_title_text"],
                icon_style=STYLES["section_title_image"],
                title="技能亮点", gap_after=_gap, layer=0)
            _gp = _gr.add_para(text="内容", icon_width=4.0, indent=0.0, gap=2.0)
            _gr.layout(pdf=pdf, force=True)
        _db = _gh.divider.get_absolute_y() + _gh.divider.get_effective_height()
        _g_probe[_gap] = _gp.node.get_absolute_y() - _db
    for _gap, _got in _g_probe.items():
        assert abs(_got - _gap) < 0.01, \
            f"gap_after={_gap} 时实际留白应为 {_gap}，实测 {_got:.3f}"
    print(f"  ✅ gap_after 精确生效（0/3/6 → "
          f"{_g_probe[0.0]:.2f}/{_g_probe[3.0]:.2f}/{_g_probe[6.0]:.2f}mm）", flush=True)
    print(f"  ✅ Spacing 通过（{Spacing().describe()}；"
          f"scaled(0.5) 等比、as_lead 导出 12 键）", flush=True)

    # ---- 9c. 段落模式（desc_mode="para"）的渲染级断言 ----
    # ⚠️ 为什么必须走渲染：这三处（段内行距 / 段间距 / 与三栏基线的相对位置）
    #    在**几何上完全看不出来** —— 段落文字盒都是满高 FILL，
    #    x/y/w/h 与落点无关。批次 9 那个"行距被放大 2.83 倍"的缺陷，
    #    任何只比几何的验收都抓不到，就是这个原因。
    print("\n【9c. 段落模式渲染级断言】", flush=True)
    _pc_root = LayoutObject(name="PC_Root", width=135.0, height=400,
                            padding=Padding.all(0), layer=0)
    _PC_LONG = ("系统采用分层排版引擎，支持样式定制、多模板切换、自动分栏等高级功能，"
                "并支持快速生成针对不同岗位的定制化简历，覆盖完整链路。")
    with contextlib.redirect_stdout(io.StringIO()):
        _pc = _pc_root.add_detail(
            index=0, key="日本农业苞谷大学", during_time="2020.09 - 2024.06",
            tags="本科 | 计算机", description=_PC_LONG + "\n第二段。",
            brief_ratio=[2.0, 1.0, 2.0], brief_height=DEFAULT_BRIEF_HEIGHT,
            desc_mode="para", para_gap=1.0,
            para_kwargs={"icon_width": 4.0, "indent": 0.0, "gap": 2.0},
            **BRIEF_DETAIL_STYLES)
        _pc_root.layout(pdf=pdf, force=True)
    _pc_recs = []
    _pr = _ProbePdf(pdf)
    with contextlib.redirect_stdout(io.StringIO()):
        _pc_root.render(_pr, is_fill=False)
    _pc_recs = [(y + h / 2.0, t) for (_x, y, h, t) in _pr.cells]
    _base_head = [b for (b, t) in _pc_recs if t in ("日本农业苞谷大学",
                                                    "2020.09 - 2024.06",
                                                    "本科 | 计算机")]
    assert len(_base_head) == 3, f"三栏应各有落点，实际 {len(_base_head)}"
    _head_b = _base_head[0]
    assert max(_base_head) - min(_base_head) < 0.01, "三栏基线必须对齐"
    # 描述段的落点：排除三栏
    _para_b = [b for (b, t) in _pc_recs if t not in
               ("日本农业苞谷大学", "2020.09 - 2024.06", "本科 | 计算机")]
    assert len(_para_b) >= 3, f"应观测到多行描述，实际 {len(_para_b)}"
    _lh = STYLES["bullet_text"].font_size * 1.2 * PT_TO_MM      # 行高
    # (1) 段内行距 = 行高（多行折行的相邻行）
    _within = _para_b[1] - _para_b[0]
    assert abs(_within - _lh) < 0.01, \
        (f"段内行距应为行高 {_lh:.4f}mm，实际 {_within:.4f}mm"
         f"（若接近 {STYLES['bullet_text'].font_size * 1.2:.2f} 则是把 pt 当 mm 了）")
    # (2) 段间距 = para_gap + 行高（第二段首行相对第一段末行）
    _between = _para_b[2] - _para_b[1]
    assert abs(_between - (1.0 + _lh)) < 0.01, \
        f"段间距应为 para_gap(1.0) + 行高({_lh:.4f})，实际 {_between:.4f}mm"
    # (3) 描述首行基线相对三栏基线的位置必须精确
    #     = 带高 − 三栏基线到带底的距离(= brief_height/2) + 描述首行半高
    _expect_off = DEFAULT_BRIEF_HEIGHT - DEFAULT_BRIEF_HEIGHT / 2 + _lh / 2
    assert abs((_para_b[0] - _head_b) - _expect_off) < 0.01, \
        (f"描述首行基线应比三栏基线低 {_expect_off:.3f}mm，"
         f"实际 {_para_b[0] - _head_b:.3f}mm")
    print(f"  ✅ 段内行距 = 行高（{_within:.4f}mm = 10pt×1.2）", flush=True)
    print(f"  ✅ 段间距 = para_gap + 行高（{_between:.4f}mm）", flush=True)
    print(f"  ✅ 描述首行基线相对三栏 = {_para_b[0] - _head_b:.3f}mm（预期 "
          f"{_expect_off:.3f}）", flush=True)

    # ---- 10. 详情标题三栏的**基线对齐**（渲染级断言）----
    # ⚠️ 这条断言存在的理由：这三栏的"文字盒几何"完全相同（都是 FILL，随容器），
    #    所以任何只比对几何的验收都**看不出**文字落点的差异 —— 曾经就是这样漏掉了
    #    一个把时间格 align_y 写成 TOP、并沿用 Padding(top=5) 的回归，
    #    表现为时间"焊死在底部"。探针在【7b】用 _ProbePdf 抓好了（不落笔）。
    print("\n【10. 详情标题三栏的基线对齐】", flush=True)
    assert len(_cell_recs) == 3, f"三栏应画出 3 段文字，实际 {len(_cell_recs)}"
    _bases = [(y + h / 2.0, t) for (_x, y, h, t) in _cell_recs]
    _spread = max(b for b, _ in _bases) - min(b for b, _ in _bases)
    for _b, _t in _bases:
        print(f"     基线 {_b:>5.2f}mm  {_t!r}", flush=True)
    assert _spread < 0.01, (
        f"三栏文字基线应对齐（视觉上同处一行），实测极差 {_spread:.3f}mm —— "
        f"检查是否有某一栏的 align_y 或 padding 与其余不一致")
    print(f"  ✅ 三栏基线对齐通过（极差 {_spread:.3f}mm，同为 "
          f"{_bases[0][0]:.2f}mm）", flush=True)

    # 10b. TextConfig 可控性：对齐/行距能改，且**不改几何**
    #      （对齐不参与 measure，所以盒子不该动 —— 这正是它安全的原因）
    #      探针在【7c】就已渲染好（pdf.output() 之后不能再渲染）
    assert _tc_geo == (DEFAULT_BRIEF_HEIGHT, DEFAULT_BRIEF_HEIGHT), \
        f"基准几何异常：{_tc_geo}"
    # 只把"时间"一栏改成贴顶：只有它该动
    assert _tc_geo2 == _tc_geo, "对齐配置不得改变几何"
    assert abs(_tc_time[0] - _tc_base[0]) < 0.01, "关键词栏不该被 time_align 影响"
    assert abs(_tc_time[2] - _tc_base[2]) < 0.01, "标签栏不该被 time_align 影响"
    assert _tc_time[1] < _tc_base[1] - 0.1, \
        f"时间栏应贴顶（更小的基线），实测 {_tc_time[1]:.3f} vs {_tc_base[1]:.3f}"
    print(f"  ✅ TextConfig 逐栏覆盖通过（time_align=TOP 只动时间栏："
          f"{_tc_base[1]:.2f} -> {_tc_time[1]:.2f}mm）", flush=True)

    # 统一 text_cfg：三栏一起改
    assert _tc_geo3 == _tc_geo, "统一对齐配置同样不得改变几何"
    assert all(b < _tc_base[i] - 0.1 for i, b in enumerate(_tc_all)), \
        f"三栏都应贴顶，基准 {_tc_base}，实测 {_tc_all}"
    print("  ✅ TextConfig 统一覆盖通过（三栏同时贴顶，几何不变）", flush=True)

    # 行距：只改行高，不改几何
    assert _tc_geo4 == _tc_geo, "行距配置不得改变几何"
    print("  ✅ TextConfig 行距可控且不改几何", flush=True)

    print("\n✅ 回归契约断言全部通过", flush=True)
    print("\n" + "=" * 60, flush=True)
    print(f"✅测试完成！测试PDF存储路径: {output_path}", flush=True)
    print("=" * 60, flush=True)
