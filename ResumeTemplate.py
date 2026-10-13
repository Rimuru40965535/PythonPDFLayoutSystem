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

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence

from LayoutEngine import (
    # 构件
    LayoutObject,
    TextObject,
    ImageObject,
    RectangleObject,
    # 样式
    Style,
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
}


# ============================================================================
# 3. 结果句柄 (Handle)
# ============================================================================
# 每个句柄持有本模板实例的公开部件。部件名只用于调试/兼容查找，
# 正常取用一律走属性 —— 这是"不再靠字符串连接"的关键。


@dataclass
class BasicHandle:
    """基础模板（左右分栏）句柄"""
    node: LayoutObject        # 分栏容器
    left: LayoutObject        # 左栏（RectangleObject）
    right: LayoutObject       # 右栏

    @property
    def content(self) -> LayoutObject:
        """兼容别名：旧 API 的返回值（content 对象）。"""
        return self.node


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
class DetailsHandle:
    """节详情模板（关键词 / 时间 / 标签 / 描述）句柄"""
    node: LayoutObject
    brief: LayoutObject
    col_key: LayoutObject
    col_time: LayoutObject
    col_tags: LayoutObject
    key: TextObject
    during_time: TextObject
    tags: TextObject
    details: LayoutObject
    description: TextObject

    @property
    def content(self) -> LayoutObject:
        return self.node

    def fill(self, key: str = "", during_time: str = "", tags: str = "",
             description: str = "",
             description_height: Optional[float] = None) -> 'DetailsHandle':
        """
        就地填充四段文字。

        description_height 为 None（默认）时，描述高度由内容自动结算
        （`SizeY.CONTENT` + 引擎真实文本测量）。给值则退回固定高度模式。
        """
        self.key.set_text(key)
        self.during_time.set_text(during_time)
        self.tags.set_text(tags)
        self.description.set_text(description)
        set_content_height(self.description, description_height)
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
class SectionHandle:
    """组合模板（节标题 + N 条详情）句柄"""
    node: Optional[LayoutObject]
    title: Optional[TitleHandle]
    details: List[DetailsHandle]

    @property
    def content(self) -> Optional[LayoutObject]:
        return self.node


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


def add_basic(self: LayoutObject,
              ratio: Optional[Sequence[float]] = None,
              left_padding: Optional[Padding] = None,
              right_padding: Optional[Padding] = None,
              layer: int = 0) -> BasicHandle:
    """
    生成基础模板 —— 左右分栏。同一份简历中只应调用一次。

    结构：
        self
        └─ {self.name}_split_container
             ├─ {self.name}_left_column   : RectangleObject（底色）
             └─ {self.name}_right_column  : LayoutObject

    Args:
        ratio: 左右比例，默认 [1.0, 2.5]
        left_padding: 左栏内边距，默认 Padding.all(0)
        right_padding: 右栏内边距，默认 Padding.left(5)
        layer: 图层索引

    Returns:
        BasicHandle —— 直接给 left / right，不必再按名字查找。
    """
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

    _, _, content_w, content_h = self.get_content_area()
    if content_w <= 0:
        raise ValueError(f"add_basic: 挂载点 '{self.name}' 没有可用宽度，无法分栏")

    # 宽度按比例定死，再作为"已构造格子"交给 create_band 排放。
    # （split_column_advanced 返回 parent，这里需要带容器本身，故直接用 create_band。）
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
    return BasicHandle(node=band, left=left_column, right=right_column)


def add_profile(self: LayoutObject,
                index: int = 0,
                icon_style: Optional[Style] = None,
                text_style: Optional[Style] = None,
                icon_width: float = DEFAULT_ICON_WIDTH,
                gap: float = 0,
                content_height: Optional[float] = None,
                row_inset: float = DEFAULT_ROW_INSET,
                layer: int = 0) -> ProfileHandle:
    """
    生成个人信息模板（图标 + 文本），一行两格。

    结构：
        self
        └─ {self.name}_profile_{index}_content : LayoutObject（FLOW）
             └─ ..._split : LayoutObject（横带，左侧缩进）
                  ├─ ..._icon_range → ..._icon : ImageObject
                  └─ ..._text_range → ..._text : TextObject

    Args:
        index: 实例索引（同一挂载点上多个实例必须互不相同）
        icon_style: 图标样式，默认 STYLES["name_image"]
        text_style: 文本样式，默认 STYLES["profile_text"]
        icon_width: 左格宽度 (mm)
        gap: 两格间距 (mm)
        content_height: 整行高度。None 表示按 text_style 字号推算
        row_inset: 行左侧缩进 (mm)，等价于旧版 split 容器的左内边距；
                   横带宽度会同步收窄，避免右侧溢出
        layer: 图层索引

    Returns:
        ProfileHandle
    """
    icon_style = STYLES["name_image"] if icon_style is None else icon_style
    text_style = STYLES["profile_text"] if text_style is None else text_style
    if content_height is None:
        content_height = profile_content_height(text_style, icon_width)

    prefix = f"{self.name}_profile_{index}"

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
    text = TextObject.from_style(
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
    # 横带的 x 已经右移了 row_inset，宽度必须同步收窄，否则右侧会溢出。
    band_w = max(content.get_content_area()[2] - row_inset, 0.0)
    cell_w = icon_width + gap
    if band_w > cell_w > 0:
        ratio = [cell_w, band_w - cell_w]
    else:
        ratio = [1.0, 1.0]

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
    # 旧版 split 容器带 Padding.left(3)：改为整条横带右移同样的量
    band.x = row_inset
    band.width = band_w

    icon_range, text_range = band.children[0], band.children[1]
    icon_range.add_child(icon)
    text_range.add_child(text)

    return ProfileHandle(
        node=content, split=band,
        icon_range=icon_range, icon=icon,
        text_range=text_range, text=text,
    )


def add_profile_photo(self: LayoutObject,
                      index: int = 0,
                      icon_style: Optional[Style] = None,
                      photo_width: float = DEFAULT_PHOTO_WIDTH,
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

    return PhotoHandle(node=content, photo=photo)


def add_section_title(self: LayoutObject,
                      index: int = 0,
                      icon_style: Optional[Style] = None,
                      text_style: Optional[Style] = None,
                      icon_width: float = DEFAULT_TITLE_ICON_WIDTH,
                      gap: float = 0,
                      height: float = DEFAULT_TITLE_HEIGHT,
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

    return TitleHandle(
        node=content, split=band,
        icon_range=icon_range, icon=icon,
        text_range=text_range, text=text,
        divider=divider,
    )


def add_details(self: LayoutObject,
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
                layer: int = 0) -> DetailsHandle:
    """
    生成一条节详情（关键词 / 时间 / 标签 / 描述）。

    结构：
        self
        └─ {self.name}_section_details_{index}_content
             ├─ ..._brief（三栏 2:1:2，高 brief_height）
             │    ├─ ..._brief_col_0 → ..._key          : TextObject(LEFT/VCENTER)
             │    ├─ ..._brief_col_1 → ..._during_time  : TextObject(CENTER/VCENTER)
             │    └─ ..._brief_col_2 → ..._tags         : TextObject(RIGHT/VCENTER)
             └─ ..._details
                  └─ ..._description : TextObject(multi_line，高度自动)

    描述高度不再硬编码 50，也不再由填充函数回写 `_height`：
    `SizeY.CONTENT` 让引擎按真实行数结算（批次 5 的真实测量）。

    传入 key / during_time / tags / description 即在本函数内完成填充。

    Args:
        index: 编号，出现在节点名中
        name_key: 命名键。给定时取代 index 参与命名，用于让**跨节**的详情
                  互不同名（如 `"{节号}_{节内序号}"`）。一个挂载点下若按
                  相同的 index 建了多个实例，它们会同名并互相覆盖注册表条目。

    Returns:
        DetailsHandle
    """
    key_style = STYLES["detail_key_1"] if key_style is None else key_style
    time_style = STYLES["detail_time_1"] if time_style is None else time_style
    tags_style = STYLES["detail_tags_1"] if tags_style is None else tags_style
    desc_style = STYLES["detail_description"] if desc_style is None else desc_style
    brief_ratio = _resolve_ratio(brief_ratio, DEFAULT_BRIEF_RATIO)
    if len(brief_ratio) != 3:
        raise ValueError(f"brief_ratio 必须恰好 3 个元素，当前 {brief_ratio}")

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

    # ---- 三栏（关键词 / 时间 / 标签）----
    brief = LayoutObject(
        name=f"{prefix}_brief",
        x=0, y=0, width=0, height=brief_height,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    content.add_child(brief)

    band = create_band(
        parent=brief,
        cells=list(brief_ratio),
        gap=0,
        padding=Padding.all(0),
        height=brief_height,
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
        padding=time_style.padding,   # 与历史行为一致：沿用样式内边距
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

    # ---- 描述 ----
    details = LayoutObject(
        name=f"{prefix}_details",
        x=0, y=0, width=0, height=0,
        color=White,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )
    # 同样必须由内容撑高。若留在 FILL，它处于 CONTENT 父之下会走"退化规则"
    # 去读子元素高度，而子元素此刻尚未测量 —— 整条详情会塌缩为 0 高。
    details.size_y = SizeY.CONTENT
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
        # line_height 不再显式传入：引擎按 line_height_ratio 推出行高
        layer=layer + 1,
    )
    details.add_child(desc_obj)

    handle = DetailsHandle(
        node=content, brief=brief,
        col_key=col_key, col_time=col_time, col_tags=col_tags,
        key=key_obj, during_time=time_obj, tags=tags_obj,
        details=details, description=desc_obj,
    )
    set_content_height(desc_obj, description_height)
    return handle


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
    content.add_child(block)
    return block


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
        title_detail_gap: 节标题与第一条详情之间的留白 (mm)
        between_details_gap: 相邻详情之间的留白 (mm)
        layer: 图层索引

    Returns:
        SectionHandle —— title 与 details 都是句柄，可直接改
    """
    get = _field_getter(section)
    title_text = get("title", "")
    icon_path = get("icon", "")
    items = list(get("details", []) or [])
    detail_styles = detail_styles or {}

    if not items:
        return SectionHandle(node=None, title=None, details=[])

    title_handle = self.add_section_title(
        index=index,
        icon_style=icon_style,
        text_style=title_style,
        layer=layer,
    ).fill(title=title_text, image_path=icon_path)

    if title_detail_gap > 0:
        self.add_spacer(f"Lead_Section_{index}_Title_Details", title_detail_gap)

    handles: List[DetailsHandle] = []
    for i, item in enumerate(items):
        handle = self.add_details(
            index=i,
            name_key=f"{index}_{i}",
            brief_ratio=brief_ratio,
            brief_height=brief_height,
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
        handle = self.add_details(index=index, **detail_kwargs).apply(item)
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
    "add_basic": add_basic,
    "add_profile": add_profile,
    "add_profile_photo": add_profile_photo,
    "add_section_title": add_section_title,
    "add_details": add_details,
    "add_details_list": add_details_list,
    "add_summary": add_summary,
    "add_section": add_section,
    "add_text_row": add_text_row,
    "add_spacer": add_spacer,
}


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
    basic = root.add_basic(
        ratio=[1.0, 2.5],
        left_padding=Padding.all(0),
        right_padding=Padding.left(8),
        layer=0,
    )
    left_column, right_column = basic.left, basic.right
    print(f"  ✅ 分栏容器: {basic.node.name}", flush=True)
    print(f"  ✅ 左栏: {left_column.name}, 右栏: {right_column.name}", flush=True)

    # ---- 5. 左栏：个人信息 ----
    print("\n【5. 生成个人信息模板】", flush=True)
    profile = left_column.add_profile(
        index=0,
        icon_style=STYLES["name_image"],
        text_style=STYLES["name_text"],
        icon_width=6,
        layer=1,
    ).fill(text="韩 梅 梅", image_path=".\\Resources\\icon.png")
    print(f"  ✅ 个人信息: {profile.node.name} → {profile.text.get_text()}", flush=True)

    # 联系方式：同一个蓝图复用 N 次
    contacts = [
        (".\\Resources\\telephone.png", "138-0000-0000"),
        (".\\Resources\\email.png", "hanmeimei@example.com"),
    ]
    for i, (icon_path, value) in enumerate(contacts, start=1):
        left_column.add_profile(
            index=i,
            content_height=profile_content_height(),
            layer=1,
        ).fill(text=value, image_path=icon_path)
    print(f"  ✅ 联系方式 {len(contacts)} 条（蓝图复用）", flush=True)

    # ---- 6. 右栏：节标题 + 节详情 ----
    print("\n【6. 生成右栏内容】", flush=True)

    edu_title = right_column.add_section_title(
        index=0,
        icon_style=STYLES["section_title_image"],
        text_style=STYLES["section_title_text"],
        layer=1,
    ).fill(title="教育背景", image_path=".\\Resources\\icon_Education_History.png")
    print(f"  ✅ 节标题: {edu_title.node.name} → {edu_title.text.get_text()}", flush=True)

    # 列表入口：一次给出多条详情
    edu_details = right_column.add_details_list(
        [
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
        ],
        between_gap=0,
        brief_ratio=[2.0, 1.0, 2.0],
        brief_height=DEFAULT_BRIEF_HEIGHT,
        layer=1,
        **BRIEF_DETAIL_STYLES,
    )
    print(f"  ✅ 教育经历 {len(edu_details)} 条（列表入口）", flush=True)

    proj_title = right_column.add_section_title(
        index=1,
        icon_style=STYLES["section_title_image"],
        text_style=STYLES["section_title_text"],
        layer=1,
    ).fill(title="项目经历", image_path=".\\Resources\\icon_Project_History.png")

    proj_details = right_column.add_details_list(
        [
            {
                "key": "基于PDF的简历自动生成系统",
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
        ],
        start_index=len(edu_details),
        brief_ratio=[2.0, 1.0, 2.0],
        layer=1,
        **BRIEF_DETAIL_STYLES,
    )
    print(f"  ✅ 项目经历 {len(proj_details)} 条", flush=True)

    # ---- 7. 渲染与高度结算 ----
    print("\n【7. 渲染 PDF】", flush=True)
    root.layout(pdf=pdf, force=True)
    root.render(pdf, is_fill=False)

    output_path = "resume_template_v2_test.pdf"
    pdf.output(output_path)
    print(f"\n✅ PDF 已生成: {output_path}", flush=True)

    # ---- 8. 回归契约断言 ----
    print("\n【8. 回归契约断言】", flush=True)

    # 8.1 方法已挂到 LayoutObject 上
    for _m in ("add_basic", "add_profile", "add_section_title",
               "add_details", "add_details_list", "add_summary",
               "add_section", "add_text_row", "add_spacer"):
        assert hasattr(LayoutObject, _m), f"LayoutObject 缺少方法 {_m}"
    print("  ✅ 方法挂载契约通过", flush=True)

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

    # 8.5 描述高度由内容结算
    _desc_h = edu_details[1].description.get_effective_height()
    assert _desc_h > 0, f"描述有效高应为正，实际 {_desc_h}"
    assert edu_details[1].description.size_y is SizeY.CONTENT, \
        "描述应处于 CONTENT 尺寸方式"
    print(f"  ✅ 描述高度自动结算：{_desc_h:.2f}mm（不再硬编码 50）", flush=True)

    # 8.6 行高走引擎默认：未显式写死 line_height
    assert edu_details[0].description._line_height is None, \
        "description 不应显式传入 line_height"
    print("  ✅ 行高走引擎默认（line_height_ratio=1.2）", flush=True)

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

    print("\n✅ 回归契约断言全部通过", flush=True)
    print("\n" + "=" * 60, flush=True)
    print(f"✅测试完成！测试PDF存储路径: {output_path}", flush=True)
    print("=" * 60, flush=True)
