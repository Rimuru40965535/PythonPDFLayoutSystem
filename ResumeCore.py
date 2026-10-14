"""
================================================================================
简历核心模块  (Resume Core) —— 顶层
================================================================================
定位：**面向使用者与开发人员的领域模型 + 无副作用渲染器**。

本文件按"认识什么"分四段，靠**函数边界**分层（不是文件边界）：

    1. 数据模型    Profiles / SkillsAwards / Details / Section / Resume
                   纯数据类型与容器。**不认识 PDF、不做 I/O**。
                   这一整段可以原样复制到别处复用。
    2. 版式配置    Theme（样式与图标）
                   只放**跨简历稳定**的呈现信息；能随简历变的文案属内容，不放这里。
    3. 排版构建    build_layout(resume, theme, spacing) -> LayoutObject
                   唯一认识中层模板词汇的地方。
    4. 渲染        render(resume, ...) / render_many(...)
                   **只读数据**：不改 resume、不改参数对象。

分层依赖（只向下依赖，不反向）：
    ResumeCore.py  →  ResumeTemplate.py  →  LayoutEngine.py

## 快速开始

    from ResumeCore import Profiles, Section, Details, Resume, render

    me = Profiles(name="张三", telephone="138-0000-0000", email="a@b.com")
    edu = Section(title="教育背景")
    edu.add_detail(Details(key="某大学", during_time="2020-2024",
                           tags="计算机 | 本科", description="主修课程：…\\n绩点 3.8。"))
    resume = Resume(profile=me, sections=[edu], summary="五年后端开发经验。")

    render(resume, output_dir="output")                  # 生成 PDF
    render(resume, output_dir="out2")                    # 同一容器可反复渲染

## 复用与批量

    # 同一份数据可以渲染成多种留白松紧，或反复渲染互不影响
    render(resume, spacing=Spacing.compact(), output_dir="tight")
    render(resume, spacing=Spacing.loose(),   output_dir="loose")

    # 一个 PDF 装多份（pdf= 传入同一个文档对象）
    pdf = make_pdf()
    for r in resumes:
        render(r, pdf=pdf)
    pdf.output("合集.pdf")

## 确定性

    render(resume, creation_date="D:20260101000000Z")     # 同数据 → 逐字节相同

================================================================================
"""

import copy
import os
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from fpdf import FPDF

from LayoutEngine import (
    AlignX,
    Color,
    AlignY,
    LayoutObject,
    PT_TO_MM,
    Padding,
    Style,
    White,
)

from ResumeTemplate import (
    BRIEF_DETAIL_STYLES,
    DEFAULT_BRIEF_HEIGHT,
    STYLES,
    Spacing,
    skills_row_height,
)


# ============================================================================
# 1. 数据模型（纯数据：不认识 PDF、不做 I/O）
# ============================================================================

@dataclass
class Profiles:
    """
    个人信息。

    只存"这个人是谁、怎么联系他"。**不含任何版式信息**
    （"个人总结"标题怎么写属版式，见 `Theme.summary_title`）。
    """
    photo: str = ""                     # 证件照资源路径
    name: str = ""
    telephone: str = ""
    locate: str = ""                    # 现居城市
    email: str = ""
    social_media_qq: str = ""
    social_media_wechat: str = ""
    contact_address: str = ""
    title: str = ""                     # 求职头衔
    website: str = ""                   # 个人网站 / GitHub
    # 个人评价 —— 渲染在**左栏最后**，视觉模板与技能/证书/荣誉相同。
    # 标题由 Theme.evaluation_title 决定（默认「个人评价」）。
    # 与 Resume.summary 是两回事：那个渲染在右栏，是个人总结。
    evaluation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "photo": self.photo,
            "name": self.name,
            "telephone": self.telephone,
            "locate": self.locate,
            "email": self.email,
            "social_media_qq": self.social_media_qq,
            "social_media_wechat": self.social_media_wechat,
            "contact_address": self.contact_address,
            "title": self.title,
            "website": self.website,
            "evaluation": self.evaluation,
        }

    def is_empty(self) -> bool:
        """姓名与全部联系方式都为空才算空"""
        return not any([self.name, self.telephone, self.email,
                        self.social_media_qq, self.social_media_wechat,
                        self.contact_address, self.website])

    def contact_rows(self, theme: Optional['Theme'] = None) -> List[tuple]:
        """
        产出 `[(图标路径, 文本), ...]` —— 按固定顺序排列的**非空**联系方式。

        顺序：电话 → 邮箱 → 城市 → QQ → 微信 → 地址 → 网站

        Args:
            theme: 取图标路径用（可用 `Theme(contact_icons={...})` 覆盖）。
                   `None` 时用内置默认图标。
        """
        ic = (lambda k: theme.icon(k)) if theme is not None \
            else (lambda k: DEFAULT_CONTACT_ICONS.get(k, ""))
        rows: List[tuple] = []
        if self.telephone:
            rows.append((ic("telephone"), self.telephone))
        if self.email:
            rows.append((ic("email"), self.email))
        if self.locate:
            rows.append((ic("locate"), self.locate))
        if self.social_media_qq:
            rows.append((ic("social"), f"QQ：{self.social_media_qq}"))
        if self.social_media_wechat:
            rows.append((ic("social"), f"微信：{self.social_media_wechat}"))
        if self.contact_address:
            rows.append((ic("address"), self.contact_address))
        if self.website:
            rows.append((ic("website"), self.website))
        return rows


class SkillsAwards:
    """
    技能 / 证书 / 荣誉。

    三块的**条目**是内容；三块的**标题文案**默认在这里（便于按简历定制），
    但 `Theme` 里的同名标题优先，用来做全局统一（见 `Theme.skills_title` 等）。

    ⚠️ 刻意**不**把每个条目做成一个模板实例：中层 `measure_text` 会按 `\\n`
       硬换行 + 逐字断行，单块多行文本更省空间也更省布局开销。
    """

    def __init__(
        self,
        skills: Optional[List[str]] = None,
        qualifications: Optional[List[str]] = None,
        awards: Optional[List[str]] = None,
        skills_title: Optional[str] = None,
        qualifications_title: Optional[str] = None,
        awards_title: Optional[str] = None,
    ):
        self.skills: List[str] = list(skills) if skills else []
        self.qualifications: List[str] = list(qualifications) if qualifications else []
        self.awards: List[str] = list(awards) if awards else []
        # None = "不表态"，由 Theme 决定标题；给了就用它（逐简历定制）
        self.skills_title = skills_title
        self.qualifications_title = qualifications_title
        self.awards_title = awards_title

    def is_empty(self) -> bool:
        return not (self.skills or self.qualifications or self.awards)

    def blocks(self, theme: Optional['Theme'] = None) -> List[tuple]:
        """
        产出 `[(块名, 标题, 条目列表), ...]`，只含非空块。

        标题取值优先级：**本对象显式给的** > `theme` 的 > 内置默认。
        """
        th = theme if theme is not None else Theme()
        candidates = [
            ("skills", self.skills_title or th.skills_title, self.skills),
            ("qualifications",
             self.qualifications_title or th.qualifications_title, self.qualifications),
            ("awards", self.awards_title or th.awards_title, self.awards),
        ]
        return [(n, t, v) for (n, t, v) in candidates if v]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skills": list(self.skills),
            "qualifications": list(self.qualifications),
            "awards": list(self.awards),
            "skills_title": self.skills_title,
            "qualifications_title": self.qualifications_title,
            "awards_title": self.awards_title,
        }


@dataclass
class Details:
    """单条详情，对应中层 `add_detail` 子模板。"""
    key: str = ""                       # 关键词（学校 / 项目 / 公司）
    during_time: str = ""               # 起讫时间
    tags: str = ""                      # 补充信息（专业 / 技术栈）
    description: str = ""               # 详情描述（支持 \\n 分段与内联 Markdown）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "during_time": self.during_time,
            "tags": self.tags,
            "description": self.description,
        }

    def is_empty(self) -> bool:
        return not any([self.key, self.during_time, self.tags, self.description])


@dataclass
class Section:
    """
    一节 = 节标题 + N 条详情。

    `icon` / `title` / `details` 三个字段**正好就是中层 `add_section` 的鸭子契约**
    （它用 `_field_getter` 读这三个名字），所以本对象可以整个交给它。
    """
    title: str = ""
    icon: str = ""                      # 节标题图标（逐节可变 → 属内容侧）
    details: List[Details] = field(default_factory=list)

    def add_detail(self, detail: Details) -> 'Section':
        self.details.append(detail)
        return self

    def remove_detail(self, index: int) -> bool:
        if 0 <= index < len(self.details):
            self.details.pop(index)
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "icon": self.icon,
            "details": [d.to_dict() for d in self.details],
        }

    def is_empty(self) -> bool:
        return not self.title and not self.details


class Resume:
    """
    整份简历 —— **纯数据容器**。

    刻意不提供任何渲染方法：渲染是 `render()` 的事。
    这样同一个实例可以被反复渲染、被不同留白配置渲染、被批量填充，
    而不会被写入任何"上一次渲染"的残留状态（旧实现会写 `_root` / `_pdf_path`）。
    """

    def __init__(
        self,
        intend_company: str = "",
        intend_job: str = "",
        profile: Optional[Profiles] = None,
        skills_awards: Optional[SkillsAwards] = None,
        sections: Optional[List[Section]] = None,
        summary: str = "",
    ):
        self.intend_company = intend_company
        self.intend_job = intend_job
        self.profile: Profiles = profile if profile is not None else Profiles()
        self.skills_awards: SkillsAwards = (
            skills_awards if skills_awards is not None else SkillsAwards())
        self.sections: List[Section] = list(sections) if sections else []
        self.summary = summary

    # ---- 章节管理 ----

    def add_section(self, section: Section) -> 'Resume':
        self.sections.append(section)
        return self

    def remove_section(self, index: int) -> bool:
        if 0 <= index < len(self.sections):
            self.sections.pop(index)
            return True
        return False

    # ---- 纯函数：从数据算文件名（不涉及渲染）----

    def get_file_name(self) -> str:
        """`{姓名}_{职位}_{公司}.pdf`，非法字符替换为下划线"""
        def clean(text: str) -> str:
            for ch in '\\/:*?"<>|':
                text = text.replace(ch, "_")
            return text.strip() or "Unknown"

        return (f"{clean(self.profile.name)}_{clean(self.intend_job)}"
                f"_{clean(self.intend_company)}.pdf")

    def is_empty(self) -> bool:
        """没有任何可渲染的内容"""
        return (self.profile.is_empty()
                and not self.sections
                and self.skills_awards.is_empty()
                and not self.summary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intend_company": self.intend_company,
            "intend_job": self.intend_job,
            "profile": self.profile.to_dict(),
            "skills_awards": self.skills_awards.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
            "summary": self.summary,
        }


# ============================================================================
# ============================================================================
# 2. 版式配置（跨简历稳定的呈现信息）
# ============================================================================

@dataclass
class ValidationReport:
    """
    配置校验结果。**区分硬错误与警告** —— 见 `Theme.validate()` 的说明。
    """
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """只有硬错误才算不通过；警告不影响通过"""
        return not self.problems

    def __bool__(self) -> bool:
        return self.ok

    def __iter__(self):
        """允许 `for p in report` 直接遍历硬错误（兼容旧的列表用法）"""
        return iter(self.problems)

    def __len__(self) -> int:
        return len(self.problems)

    def format(self) -> str:
        lines = []
        for p in self.problems:
            lines.append(f"❌ {p}")
        for w in self.warnings:
            lines.append(f"⚠️  {w}")
        return "\n".join(lines)


@dataclass
class Theme:
    """
    版式配置：**跨简历稳定**的呈现信息。

    分界原则：**能随简历变的是内容（放数据类），跨简历稳定的是呈现（放这里）。**
    所以这里只有样式与图标，以及那三个"版面标签"文案
    （`summary_title` / `skills_title` / ...）—— 它们的默认值就是历史文案，
    逐简历要改时给 `SkillsAwards(skills_title=...)` 即可，那个优先级更高。

    ## 版面结构常量

    这些是"版面骨架"，改动会移动所有元素，所以集中在这里而不是散在函数体里。
    """
    # ---- 纸张与分栏骨架 ----
    page_width: float = 210.0
    page_height: float = 297.0
    page_padding: float = 10.0
    column_ratio: Sequence[float] = (1.0, 2.5)   # 左 : 右
    right_column_padding_left: float = 8.0

    # ---- 样式 ----
    section_title_style: Optional[Style] = None
    section_title_icon_style: Optional[Style] = None
    detail_styles: Optional[dict] = None
    summary_style: Optional[Style] = None
    skills_title_style: Optional[Style] = None
    skills_text_style: Optional[Style] = None
    name_icon_style: Optional[Style] = None
    name_text_style: Optional[Style] = None
    contact_text_style: Optional[Style] = None
    photo_style: Optional[Style] = None

    # ---- 联系方式的图标段落参数（`add_para`）----
    # 行高由内容决定，图标只影响左栏宽；图标边长须 ≤ 文本首行高
    # （12pt × 1.2 = 5.08mm），否则中层会明确报错。
    contact_icon_width: float = 4.0
    contact_icon_gap: float = 2.0
    # 图标左缩进。**必须 > 0**：`add_para` 的 indent 为 0 时图标会精确贴在
    # 蓝底左栏的边界上（实测 x = 10.00 = 蓝底 abs_x），目视就是"顶到边了"。
    # 取 3.0 与姓名行（`add_info` 的 row_inset=3.0）左对齐。
    contact_left_indent: float = 3.0
    # 联系方式之间的留白（mm）。决定行间距 = 行高 + 本值。
    # 12pt 文本行高 5.08mm，故 3.0 → 行间距 8.08mm。
    # ⚠️ 这是**顶层**的疏密选择，没有改中层 `Spacing.between_contacts` 的默认值
    #    （那个是中层的通用默认，保持 5.0 不动）。
    contact_gap: float = 3.0

    # ---- 技能/证书/荣誉的左缩进 ----
    # 标题行与正文行必须用**同一个值**，否则标题比正文更靠右、参差不齐。
    skills_left_indent: float = 3.0

    # ---- 左栏底色 ----
    # None = 用中层 STYLES[left_column].fill_color（历史观感）。
    # 显式给 Color 即可换配色，**不需要改中层的共享 STYLES**。
    left_column_color: Optional[Color] = None

    # ---- 版面标签文案（逐简历可被数据类覆盖）----
    summary_title: str = "个人总结"
    # 左栏个人评价块的标题文案（与技能/证书/荣誉同一视觉模板）
    evaluation_title: str = "个人评价"
    skills_title: str = "掌握技能"
    qualifications_title: str = "获得证书"
    awards_title: str = "获得荣誉"

    # ---- 图标（空串 = 该位置留空）----
    summary_icon: str = ""
    name_icon: str = r".\Resources\woman_student.png"
    section_icon_fallback: str = ""

    # ---- 详情区的排版参数 ----
    brief_ratio: Sequence[float] = (2.0, 1.0, 2.0)
    brief_height: float = DEFAULT_BRIEF_HEIGHT
    desc_mode: str = "para"             # "para" 图标段落 / "inline" 整段文本
    para_icon_width: float = 4.0
    para_icon_gap: float = 2.0
    # 描述体自身内边距。None = 用中层默认（Padding.all(2)）；
    # 传 Padding.all(0) 可关闭，让盒高等于纯文本高（调试对齐时有用）
    body_inner_padding: Optional[Padding] = None

    # ---- 联系方式图标（`Profiles.contact_rows()` 用）----
    # ⚠️ 必须能从构造参数传入。此前是 6 个 `init=False` 字段，
    #    想换图标只能改类属性 —— 那是模块级共享状态，不是配置。
    contact_icons: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_CONTACT_ICONS))

    # 真值表，同时作为"类属性可读"的兼容面（`Theme.ICON_TELEPHONE` 仍可用）
    ICON_TELEPHONE: str = field(default=r".\Resources\telephone.png", init=False)
    ICON_EMAIL: str = field(default=r".\Resources\email.png", init=False)
    ICON_LOCATE: str = field(default=r".\Resources\locate.png", init=False)
    ICON_SOCIAL: str = field(default=r".\Resources\social_media.png", init=False)
    ICON_ADDRESS: str = field(default=r".\Resources\contact_address.png", init=False)
    ICON_WEBSITE: str = field(default=r".\Resources\website.png", init=False)

    def icon(self, key: str) -> str:
        """取某个联系方式的图标路径（可在实例上用 `contact_icons` 覆盖）"""
        return self.contact_icons.get(key, DEFAULT_CONTACT_ICONS.get(key, ""))

    def skills_body_padding(self) -> Padding:
        """
        技能正文的文本块内边距 = 左缩进 + 上下沿用 `body_inner_padding`。

        ⚠️ 不能直接把 `body_inner_padding` 传下去：那样正文左缩进为 0，
        而标题行有缩进，两者左边缘会差一个缩进值。
        """
        base = self.body_inner_padding
        if base is None:
            base = Padding.all(2)       # 与中层默认一致
        return Padding(left=self.skills_left_indent,
                       right=base.right, top=base.top, bottom=base.bottom)

    def __post_init__(self):
        # 样式默认值从 STYLES 取 —— 这样中层的样式改动会自动跟过来
        if self.section_title_style is None:
            self.section_title_style = STYLES["section_title_text"]
        if self.section_title_icon_style is None:
            self.section_title_icon_style = STYLES["section_title_image"]
        if self.detail_styles is None:
            self.detail_styles = dict(BRIEF_DETAIL_STYLES)
        if self.summary_style is None:
            self.summary_style = STYLES["summary_text"]
        if self.skills_title_style is None:
            # **加粗**：中层 `STYLES["skillsawards_title"]` 的 bold=False，
            # 但 14pt 非粗体做块标题偏弱（用户反馈"取消粗体后观感变差"）。
            # 这是**顶层**的呈现决定，用 replace 派生，不改中层的共享 STYLES。
            self.skills_title_style = STYLES["skillsawards_title"].replace(bold=True)
        if self.skills_text_style is None:
            self.skills_text_style = STYLES["skillsawards_text"]
        if self.name_icon_style is None:
            self.name_icon_style = STYLES["name_image"]
        if self.name_text_style is None:
            self.name_text_style = STYLES["name_text"]
        if self.contact_text_style is None:
            # 联系方式沿用旧观感的字号（`profile_text` = 12pt）。
            # 若换成 `contact_text`（10pt）会更紧凑，但联系方式会比现在小一号。
            self.contact_text_style = STYLES["profile_text"]
        if self.photo_style is None:
            self.photo_style = STYLES["profile_photo"]

    def validate(self,
                 resume: Optional['Resume'] = None) -> 'ValidationReport':
        """
        检查本配置内部是否有**互相打架**或**不可能成立**的设置。

        **区分两类结果**（这是有意的）：

            problems（硬错误）—— 配置本身不成立，渲染必然失败或明显错误。
                                调用方应当视作失败。
            warnings（警告）  —— 能跑，但结果可能不是你要的。
                                典型：引用的图片不存在 ——
                                按 `SKILLS.md` 的 G.4/D2 **缺图片是允许的**
                                （引擎静默降级、该位置留空），
                                所以**绝不能**把它当硬失败，否则新克隆仓库直接跑不起来。

        一次报全，而不是改一个报一个。

        Args:
            resume: 给了就一并做"内容与版式是否匹配"的检查
        """
        problems: List[str] = []
        warnings: List[str] = []
        if self.contact_left_indent <= 0:
            problems.append(
                f"contact_left_indent={self.contact_left_indent} 必须 > 0，"
                f"否则联系方式图标会贴在蓝底左栏边界上")
        if self.skills_left_indent < 0:
            problems.append(f"skills_left_indent={self.skills_left_indent} 不能为负")
        if self.column_ratio and sum(self.column_ratio) <= 0:
            problems.append(f"column_ratio={list(self.column_ratio)} 之和必须为正")
        if self.page_padding * 2 >= min(self.page_width, self.page_height):
            problems.append(
                f"page_padding={self.page_padding} 过大：两倍已超过页面短边")
        if not self.evaluation_title.strip():
            problems.append(
                "evaluation_title 为空 —— 个人评价块会渲染成没有标题的一行")
        if self.desc_mode not in ("inline", "para"):
            problems.append(
                f"desc_mode={self.desc_mode!r} 只能是 'inline' 或 'para'")

        # 联系方式图标边长必须 ≤ 联系方式文本的首行高
        # （中层 add_para 的 icon_anchor="first_line" 契约）
        st = self.contact_text_style
        if st is not None:
            first_h = st.font_size * (st.line_height_ratio or 1.2) * PT_TO_MM
            if self.contact_icon_width > first_h + 1e-9:
                problems.append(
                    f"contact_icon_width={self.contact_icon_width}mm > "
                    f"contact_text_style 首行高 {first_h:.2f}mm —— "
                    f"中层会拒绝（icon_anchor='first_line' 要求图标 ≤ 首行高）；"
                    f"把图标调小、或提高该样式的字号/行高系数")

        # 必须有姓名（否则渲染器会拒绝，且文件名无意义）
        if resume is not None:
            if not resume.profile.name:
                problems.append("resume.profile.name 为空 —— 渲染器会拒绝")
            if not resume.sections and not resume.summary:
                problems.append("resume 既无 sections 也无 summary —— 渲染器会拒绝")

        # 图标文件不存在 -> **警告**，不是硬错误。
        # 依据 SKILLS.md G.4/D2：缺图片是允许的降级路径（引擎渲染时留空），
        # 把它当失败会让"新克隆的仓库（Resources/ 为空）"完全跑不起来。
        missing = [f"{k}={p}" for k, p in self.contact_icons.items()
                   if p and not os.path.exists(p)]
        section_missing = []
        if resume is not None:
            section_missing = [sec.title or "(无标题)"
                               for sec in resume.sections
                               if sec.icon and not os.path.exists(sec.icon)]
        if missing or section_missing:
            detail = []
            if missing:
                detail.append(f"联系方式图标缺失 {len(missing)} 个：{missing}")
            if section_missing:
                detail.append(f"节标题图标缺失的节：{section_missing}")
            warnings.append("；".join(detail) +
                            "（按 G.4/D2，缺图片会静默降级为留空，不影响渲染）")
        return ValidationReport(problems=problems, warnings=warnings)


# ============================================================================
# 3+4. 排版构建与渲染
# ============================================================================

# 联系方式图标的真值表（模块级：允许在 class body 里被 default_factory 引用）
DEFAULT_CONTACT_ICONS: Dict[str, str] = {
    "telephone": r".\\Resources\\telephone.png",
    "email": r".\\Resources\\email.png",
    "locate": r".\\Resources\\locate.png",
    "social": r".\\Resources\\social_media.png",
    "address": r".\\Resources\\contact_address.png",
    "website": r".\\Resources\\website.png",
}


class RenderError(RuntimeError):
    """渲染前置条件不满足（数据不足、无法产出有效版面）"""


def make_pdf(theme: Optional[Theme] = None) -> FPDF:
    """建一个空白 PDF 并注册中文字体（缺字体时退回内置字体，不抛异常）"""
    th = theme if theme is not None else Theme()
    pdf = FPDF()
    pdf.add_page()
    for style in ("", "B"):
        path = (r".\Resources\LXGWWenkai-Regular.ttf" if style == ""
                else r".\Resources\LXGWWenkai-Bold.ttf")
        try:
            pdf.add_font("LXGW", style, path)
        except Exception:
            try:
                pdf.add_font("LXGW", style, path, subset=False)
            except Exception:
                pass  # 缺字体：让上层报错（见 check_degradation.py 的 D3）
    return pdf


def _spacer(root: LayoutObject, name: str, height: float, layer: int = 1) -> None:
    """值 <= 0 时不留白（与中层 add_spacer 的约定一致）"""
    if height > 0:
        root.add_spacer(name, height, layer=layer)


def _fill_left_column(column: LayoutObject, resume: Resume,
                      theme: Theme, spacing: Spacing) -> None:
    """左栏：证件照 / 姓名 / 联系方式 / 技能证书荣誉"""
    profile = resume.profile

    _spacer(column, "Lead_Left_Above_All", spacing.left_top)

    if profile.photo:
        column.add_photo(index=0, image_path=profile.photo,
                         icon_style=theme.photo_style, layer=1)
        _spacer(column, "Lead_Left_Photo_Name", spacing.photo_name)

    if profile.name:
        column.add_info(index=0, variant="name", text=profile.name,
                        image_path=theme.name_icon,
                        icon_style=theme.name_icon_style,
                        text_style=theme.name_text_style,
                        layer=1)
        _spacer(column, "Lead_Left_Name_Contacts", spacing.name_contacts)

    contacts = profile.contact_rows(theme)
    for i, (icon_path, value) in enumerate(contacts):
        # ⚠️ 联系方式用 **`add_para`（图标段落）**，不是 `add_info`。
        #    原因：`add_info` 的整行高 = max(文本最小高, 图标占高)，
        #    图标 4mm 把行高顶到 `4+3 = 7mm`，而文字实高只有 5.08mm ——
        #    上下各空近 1mm，再叠 5mm 留白，行间距达 **12mm（≈ 文字高的 2.4 倍）**，
        #    目视就是"联系方式行距太大"。
        #    `add_para` 的行高**由内容决定**（图标按"首行中心"锚定），
        #    行高 = 文本行高 5.08mm、行间距 10.08mm。
        column.add_para(
            text=value,
            icon=icon_path,
            icon_width=theme.contact_icon_width,
            indent=theme.contact_left_indent,
            gap=theme.contact_icon_gap,
            style=theme.contact_text_style,
            layer=1,
        )
        # N 条之间只应有 N-1 个留白
        if i < len(contacts) - 1:
            _spacer(column, f"Lead_Left_Contact_{i}", theme.contact_gap)

    if contacts:
        _spacer(column, "Lead_Left_Contacts_Skills", spacing.contacts_skills)

    _fill_skills_awards(column, resume, theme, spacing)
    # 个人评价放在左栏**最后**（技能块之后、底部留白之前）
    _fill_evaluation(column, resume, theme, spacing)
    _spacer(column, "Lead_Left_Below_All", spacing.left_bottom)


def _add_left_block(column: LayoutObject, theme: Theme,
                    block_name: str, block_title: str,
                    description: str) -> None:
    """
    左栏里的一个"文本块" = **一行加粗标题 + 一行自适应正文**。

    这是「技能 / 证书 / 荣誉」与「个人评价」**共用的视觉模板**
    —— 所以它们看起来是同一套排版，改样式时也只需改一处。

    ⚠️ 正文用 `add_detail_body(height=None)` 让它**按内容自动结算**，
    不再用历史上那个 `高度 = 条目数 × 6` 的硬编码估算 ——
    那个估算在条目文字较长（折行）时会算少，导致文字溢出或与下一块重叠。

    ⚠️ 标题行与正文的左缩进**必须同值**：标题用 `row_padding`，
    正文用文本块 `inner_padding`（见 `Theme.skills_body_padding`）。
    """
    column.add_text_row(
        name=f"{column.name}_{block_name}_title",
        text=block_title,
        style=theme.skills_title_style,
        height=skills_row_height(theme.skills_title_style),
        row_padding=Padding.left(theme.skills_left_indent),
        text_padding=Padding.all(0),
        align_x=AlignX.LEFT, align_y=AlignY.VCENTER, layer=1,
    )
    column.add_detail_body(
        prefix=f"{column.name}_{block_name}",
        description=description,
        style=theme.skills_text_style,
        height=None,                       # ← 由内容结算
        # 左缩进做进文本块内边距，与标题行对齐；
        # 上下内边距沿用 body_inner_padding（None = 中层默认 2mm）
        inner_padding=theme.skills_body_padding(),
        layer=1,
    )


def _fill_skills_awards(column: LayoutObject, resume: Resume,
                        theme: Theme, spacing: Spacing) -> None:
    """技能 / 证书 / 荣誉：每块用 `_add_left_block` 落地，块间留白"""
    if resume.skills_awards.is_empty():
        return

    blocks = resume.skills_awards.blocks(theme)
    for i, (block_name, block_title, items) in enumerate(blocks):
        _add_left_block(column, theme, block_name, block_title, "\n".join(items))
        if i < len(blocks) - 1:
            _spacer(column, f"Lead_Left_SkillsBlock_{i+1}", spacing.between_skills)


def _fill_evaluation(column: LayoutObject, resume: Resume,
                     theme: Theme, spacing: Spacing) -> None:
    """
    个人评价：**与技能/证书/荣誉完全相同的视觉模板**（复用 `_add_left_block`）。

    数据来自 `Profiles.evaluation`。为空则整块不渲染。

    放在左栏**最后**（技能块之后、底部留白之前）。
    右栏的个人总结（`Resume.summary`）是另一回事，两者可以同时存在，
    也可以只用其中一个 —— 互不影响。
    """
    text = resume.profile.evaluation
    if not text:
        return
    # 与前一"块"之间留白：复用 between_skills，
    # 因为评价在视觉上就是"技能的下一块"，同间距最自然（且无需中层新增字段）
    if not resume.skills_awards.is_empty():
        _spacer(column, "Lead_Left_SkillsBlock_eval", spacing.between_skills)
    _add_left_block(column, theme, "evaluation", theme.evaluation_title, text)


def _fill_right_column(column: LayoutObject, resume: Resume,
                       theme: Theme, spacing: Spacing) -> None:
    """右栏：各章节（节标题 + 详情）+ 个人总结"""
    _spacer(column, "Lead_Right_Above_All", spacing.right_top)

    rendered = 0
    for section in resume.sections:
        if not section.details:
            continue
        column.add_section(
            section,
            index=rendered,
            title_style=theme.section_title_style,
            icon_style=theme.section_title_icon_style,
            detail_styles=theme.detail_styles,
            brief_ratio=theme.brief_ratio,
            brief_height=theme.brief_height,
            desc_mode=theme.desc_mode,
            para_gap=spacing.between_paras,
            para_kwargs={
                "icon_width": theme.para_icon_width,
                "indent": 0.0,
                "gap": theme.para_icon_gap,
            },
            title_detail_gap=spacing.section_title_to_body,
            between_details_gap=spacing.between_details,
            layer=1,
        )
        _spacer(column, f"Lead_Right_Section_{rendered}", spacing.between_sections)
        rendered += 1

    if resume.summary:
        # 节标题 + 总结正文；用 title_detail_gap 承载"标题↔正文"的留白
        column.add_section_heading(
            index=rendered,
            icon_style=theme.section_title_icon_style,
            text_style=theme.section_title_style,
            title=theme.summary_title,
            image_path=theme.summary_icon,
            gap_after=spacing.section_title_to_body,
            layer=1,
        )
        column.add_detail_body(
            prefix=f"{column.name}_summary_body_0",
            description=resume.summary,
            style=theme.summary_style,
            height=None,
            inner_padding=theme.body_inner_padding,
            layer=1,
        )

    _spacer(column, "Lead_Right_Below_All", spacing.right_bottom)


def build_layout(resume: Resume,
                 theme: Optional[Theme] = None,
                 spacing: Optional[Spacing] = None) -> LayoutObject:
    """
    把一份 `Resume` 落成排版树。**只读 `resume`，绝不写它。**

    这是唯一认识中层模板词汇的地方；数据模型与 Theme 都不认识渲染。

    Args:
        resume: 简历数据（渲染过程不会修改它）
        theme: 版式配置，None 用默认
        spacing: 留白配置（中层 `Spacing`），None 用默认

    Returns:
        已 `layout()` 结算过的 `LayoutObject` 根节点（**尚未渲染**）
    """
    th = theme if theme is not None else Theme()
    sp = spacing if spacing is not None else Spacing()

    root = LayoutObject(
        name="Root",
        x=0, y=0,
        width=th.page_width, height=th.page_height,
        color=White,
        padding=Padding.all(th.page_padding),
        layer=0,
    )
    basic = root.add_basic(
        ratio=list(th.column_ratio),
        left_padding=Padding.all(0),
        right_padding=Padding.left(th.right_column_padding_left),
        color=th.left_column_color,
        layer=0,
    )
    _fill_left_column(basic.left, resume, th, sp)
    _fill_right_column(basic.right, resume, th, sp)
    return root


def _validate(resume: Resume) -> None:
    """渲染前置校验。数据不足时明确报错，而不是产出空页或异常版面"""
    if not resume.profile.name:
        raise RenderError(
            "个人信息缺少姓名（profile.name）。姓名用于文件名与左栏标题，必需。")
    if not resume.sections and not resume.summary:
        raise RenderError(
            "没有任何可渲染的章节或总结：请给 sections 或 summary 至少一项。")


def render(resume: Resume,
           output_dir: str = "./output",
           *,
           spacing: Optional[Spacing] = None,
           theme: Optional[Theme] = None,
           debug: int = 0,
           creation_date: Optional[datetime] = None,
           filename: Optional[str] = None,
           pdf: Optional[FPDF] = None) -> str:
    """
    把一份简历渲染成 PDF。**无副作用：不修改 `resume` / `spacing` / `theme`。**

    Args:
        resume: 简历数据
        output_dir: 输出目录
        spacing: 留白配置（`ResumeTemplate.Spacing`）。想整体调松紧就传
                 `Spacing.compact()` / `Spacing.loose()` / `Spacing().scaled(k)`
        theme: 版式配置
        debug: 0 只渲染内容；1 只渲染调试框；其他值两者都渲染
        creation_date: PDF 创建时间，须为 `datetime` 对象。
                       **给了就能逐字节复现**（批量与回归比对用）。
                       ⚠️ 必须传 `datetime`，传字符串 fpdf 会抛 `TypeError`
                       （见下面的显式校验 —— 早前用 `except: pass` 吞掉过它，
                       导致"固定时间"静默失效）
        filename: 覆盖输出文件名（默认由 `resume.get_file_name()` 推出）
        pdf: 传入现成的 PDF 文档对象，可把多份简历装进同一个 PDF

    Returns:
        str: 生成的 PDF 文件路径（`pdf=` 为传入对象时返回 ""）

    Raises:
        RenderError: 数据不足（缺姓名、无章节且无总结）
        TypeError: `creation_date` 不是 `datetime`
    """
    th = theme if theme is not None else Theme()
    sp = spacing if spacing is not None else Spacing()
    _validate(resume)

    # 显式校验，不用 except 吞掉 —— 否则"固定时间"会静默失效
    if creation_date is not None and not isinstance(creation_date, datetime):
        raise TypeError(
            f"creation_date 应为 datetime 对象，收到 {type(creation_date).__name__}。"
            f"例如 datetime(2026, 1, 1, tzinfo=timezone.utc)")

    own_pdf = pdf is None
    doc = make_pdf(th) if own_pdf else pdf

    if creation_date is not None:
        doc.set_creation_date(creation_date)

    root = build_layout(resume, th, sp)
    # 传 pdf 才能用真实行数测量文本（CONTENT 高度必须在这里定下来）
    root.layout(pdf=doc, force=True)

    if debug == 1:
        root.render_debug(doc, is_fill=True, has_border=True,
                          show_name=True, show_bounds=True)
    elif debug == 0:
        root.render(doc, is_fill=False)
    else:
        root.render_debug(doc, is_fill=True, has_border=True,
                          show_name=True, show_bounds=True)
        root.render(doc, is_fill=False)

    if not own_pdf:
        return ""       # 调用方管输出（一个 PDF 装多份的场景）

    os.makedirs(output_dir, exist_ok=True)
    out_name = filename if filename else resume.get_file_name()
    out_path = os.path.join(output_dir, out_name)
    doc.output(out_path)
    return out_path


def render_many(resumes: Sequence[Resume],
                output_dir: str = "./output",
                *,
                spacing: Optional[Spacing] = None,
                theme: Optional[Theme] = None,
                creation_date: Optional[str] = None,
                **kwargs) -> List[str]:
    """
    批量渲染。**每个 Resume 用同一个 `spacing` / `theme`，互不影响。**

    这正是"同一个数据容器被复用多次"的落地形式：`spacing` / `theme`
    在多次渲染之间共享且不被修改。

    Returns:
        生成的文件路径列表（按输入顺序）
    """
    return [render(r, output_dir, spacing=spacing, theme=theme,
                   creation_date=creation_date, **kwargs)
            for r in resumes]


def render_into(pdf: FPDF,
                resumes: Sequence[Resume],
                *,
                spacing: Optional[Spacing] = None,
                theme: Optional[Theme] = None) -> FPDF:
    """
    把多份简历渲染进**同一个** PDF，每份占一页；返回该 PDF（调用方负责 output）。

    ⚠️ 每份之前会 `add_page()` —— 调用方只需给一个已 `add_page()` 的空文档
    （`make_pdf()` 返回的就是），本函数负责后续分页。
    """
    for i, r in enumerate(resumes):
        if i > 0:
            pdf.add_page()
        render(r, spacing=spacing, theme=theme, pdf=pdf)
    return pdf


# ============================================================================
# 5. 自检入口
# ============================================================================

# ---------------------------------------------------------------------------
# 5.1 内容配置 —— 一份简历"写了什么"
# ---------------------------------------------------------------------------

@dataclass
class ContentConfig:
    """
    一份简历的**全部内容**，集中在一处。

    与 `RenderConfig` 分工：**本类是"写什么"（内容），那个是"怎么排"（呈现）。**
    同一个内容可以配不同呈现渲染多次；同一个呈现也可以套不同内容批量生成。

    `to_resume()` 把它落成 `Resume` 数据容器 —— 之后渲染**只读**它，不改。
    """
    intend_company: str = ""
    intend_job: str = ""
    profile: Profiles = field(default_factory=Profiles)
    skills_awards: SkillsAwards = field(default_factory=SkillsAwards)
    sections: List[Section] = field(default_factory=list)
    summary: str = ""

    def to_resume(self) -> Resume:
        return Resume(
            intend_company=self.intend_company,
            intend_job=self.intend_job,
            profile=self.profile,
            skills_awards=self.skills_awards,
            sections=self.sections,
            summary=self.summary,
        )

    def describe(self) -> str:
        n_details = sum(len(sec.details) for sec in self.sections)
        blocks = len(self.skills_awards.blocks())
        return (f"姓名={self.profile.name or '（空）'}  "
                f"章节={len(self.sections)}（详情 {n_details} 条）  "
                f"技能块={blocks}  总结={'有' if self.summary else '无'}")


# ---------------------------------------------------------------------------
# 5.2 渲染配置 —— 一份简历"怎么排"
# ---------------------------------------------------------------------------

@dataclass
class RenderConfig:
    """
    把「生成一份 PDF 需要的全部可调项」集中到一处：

        内容      -> ContentConfig（另一个类，见上）
        留白疏密  -> spacing（中层 `Spacing`）
        呈现版式  -> theme（`Theme`）
        输出      -> output_dir / filename
        渲染开关  -> debug / creation_date

    用法：

        cfg = RenderConfig()
        problems = cfg.validate(content)          # 一次报全所有问题
        path = cfg.render(content)                # 或 cfg.render(resume)

    **与 `build_layout` 的区别**：这里是"配置对象"，那里是"构建函数"。
    """
    spacing: Spacing = field(default_factory=Spacing)
    theme: Theme = field(default_factory=Theme)
    output_dir: str = "./output"
    filename: Optional[str] = None
    debug: int = 0
    creation_date: Optional[datetime] = None

    # ---- 校验 ----

    def validate(self, content: Union[ContentConfig, Resume]) -> ValidationReport:
        """返回全部问题（空 = 没问题）。一次报全，不是改一个报一个。"""
        resume = content.to_resume() if isinstance(content, ContentConfig) \
            else content
        return self.theme.validate(resume)

    # ---- 渲染 ----

    def render(self, content: Union[ContentConfig, Resume],
               **overrides) -> str:
        """
        渲染。`content` 可以是 `ContentConfig` 或已经建好的 `Resume`。

        `**overrides` 透传给 `render()`（如 `spacing=` / `theme=` /
        `creation_date=`），便于在不改配置对象的前提下临时覆盖。
        """
        resume = content.to_resume() if isinstance(content, ContentConfig) \
            else content
        kw = dict(output_dir=self.output_dir,
                  spacing=self.spacing, theme=self.theme,
                  debug=self.debug, creation_date=self.creation_date,
                  filename=self.filename)
        kw.update(overrides)
        out_dir = kw.pop("output_dir")
        return render(resume, out_dir, **kw)

    def to_dict(self) -> Dict[str, Any]:
        """可序列化的快照（为阶段二的外部配置文件铺路）"""
        return {
            "spacing": dataclasses.asdict(self.spacing),
            "theme": {
                "page_width": self.theme.page_width,
                "page_height": self.theme.page_height,
                "page_padding": self.theme.page_padding,
                "column_ratio": list(self.theme.column_ratio),
                "right_column_padding_left": self.theme.right_column_padding_left,
                "summary_title": self.theme.summary_title,
                "evaluation_title": self.theme.evaluation_title,
                "skills_title": self.theme.skills_title,
                "qualifications_title": self.theme.qualifications_title,
                "awards_title": self.theme.awards_title,
                "summary_icon": self.theme.summary_icon,
                "name_icon": self.theme.name_icon,
                "brief_ratio": list(self.theme.brief_ratio),
                "brief_height": self.theme.brief_height,
                "desc_mode": self.theme.desc_mode,
                "para_icon_width": self.theme.para_icon_width,
                "para_icon_gap": self.theme.para_icon_gap,
                "contact_icon_width": self.theme.contact_icon_width,
                "contact_icon_gap": self.theme.contact_icon_gap,
                "contact_left_indent": self.theme.contact_left_indent,
                "contact_gap": self.theme.contact_gap,
                "skills_left_indent": self.theme.skills_left_indent,
                "contact_icons": dict(self.theme.contact_icons),
            },
            "output_dir": self.output_dir,
            "filename": self.filename,
            "debug": self.debug,
        }


# ---------------------------------------------------------------------------
# 5.3 默认内容 —— 覆盖全部字段的一份样例
# ---------------------------------------------------------------------------

def default_content() -> ContentConfig:
    """
    默认内容：**故意把 Profiles / SkillsAwards / Section / Details 的每个字段都填上**，
    这样"生成一份简历需要什么"在源码里一目了然，也顺带覆盖渲染路径。
    """
    me = Profiles(
        photo=r".\Resources\woman_student.png",
        name="利姆露",
        telephone="138-0000-0000",
        email="limuru@example.com",
        locate="中央都市",
        social_media_qq="1145141919",
        social_media_wechat="limuru_wx",
        contact_address="中央都市魔王大道 1 号",
        title="后端开发工程师",
        website="github.com/limuru",
        # 个人评价 —— 渲染在左栏最后，视觉模板与技能/证书/荣誉相同
        evaluation="五年全栈开发经验，习惯把复杂问题拆成可验证的小步。\n"
                   "重视可维护性与工程质量。",
    )

    edu = Section(title="教育背景",
                  icon=r".\Resources\icon_Education_History.png")
    edu.add_detail(Details(
        key="日本农业苞谷大学",
        during_time="2020.09 - 2024.06",
        tags="金坷垃制造与苞米发酵工程 | 本科",
        description="主修课程：<c:CC0000>数据结构与算法</c>、操作系统、计算机网络、数据库原理、软件工程。\n"
                    "毕业论文：基于深度学习的图像分类算法研究。\n"
                    "连续三年获得专业奖学金，GPA 3.8/4.0。"))
    edu.add_detail(Details(
        key="交换生项目",
        during_time="2022.09 - 2023.01",
        tags="海外交流",
        description="赴某大学交换一学期，主修分布式系统与编译原理。"))

    proj = Section(title="项目经历",
                   icon=r".\Resources\icon_Project_History.png")
    proj.add_detail(Details(
        key="基于 PDF 的简历自动生成系统",
        during_time="2025.03 - 2025.06",
        tags="Python, FPDF, 排版引擎",
        description="设计并实现了一套基于 Python 的 PDF 简历自动生成系统。\n"
                    "系统采用分层排版引擎，支持样式定制、多模板切换、自动分栏等高级功能。\n"
                    "实现了简历元件的模块化管理，支持快速生成针对不同岗位的定制化简历。"))
    proj.add_detail(Details(
        key="数据可视化看板",
        during_time="2024.09 - 2024.12",
        tags="Vue.js, ECharts, Flask",
        description="为某电商公司开发实时数据监控看板，展示销售、流量、转化等核心指标。\n"
                    "使用 WebSocket 实现实时更新，日活用户 200+。"))

    return ContentConfig(
        intend_company="腾讯科技",
        intend_job="后端开发工程师",
        profile=me,
        skills_awards=SkillsAwards(
            skills=["Python / Java / Go", "FPDF 排版引擎", "Vue.js / Flask"],
            qualifications=["CET-6", "软件设计师"],
            awards=["校级一等奖学金", "ACM 校赛二等奖"],
        ),
        sections=[edu, proj],
        summary="五年全栈开发经验，关注排版可维护性与工程质量。",
    )


def _sample(seed: str = "甲") -> Resume:
    """构造一份覆盖全部字段的样例简历（自检与文档示例共用）"""
    me = Profiles(
        photo="",                      # 不依赖证件照素材
        name=f"测试{seed}",
        telephone="138-0000-0000",
        email="a@b.com",
        locate="某市",
        social_media_qq="123456",
        social_media_wechat="wx_id",
        contact_address="某路 1 号",
        title="后端开发",
        website="github.com/x",
        evaluation="五年全栈开发经验。",
    )
    edu = Section(title="教育背景",
                  icon=r".\Resources\icon_Education_History.png")
    edu.add_detail(Details(
        key="日本农业苞谷大学", during_time="2020.09 - 2024.06",
        tags="本科 | 计算机",
        description="主修课程：数据结构与算法、操作系统、计算机网络。\n"
                    "毕业论文：基于深度学习的图像分类算法研究。"))
    proj = Section(title="项目经历",
                   icon=r".\Resources\icon_Project_History.png")
    proj.add_detail(Details(
        key="Python 简历生成系统", during_time="2025.03 - 2025.06",
        tags="Python, FPDF",
        description="设计并实现了一套基于 Python 的 PDF 简历自动生成系统。\n"
                    "系统采用分层排版引擎，支持多模板切换、自动分栏。"))
    return Resume(
        intend_company="腾讯", intend_job="后端开发工程师", profile=me,
        skills_awards=SkillsAwards(
            skills=["Python / Java / Go", "FPDF 排版引擎"],
            qualifications=["CET-6"], awards=["一等奖学金"]),
        sections=[edu, proj],
        summary="五年全栈开发经验，关注排版可维护性。",
    )


def _snapshot(resume: Resume) -> dict:
    """
    数据容器快照 —— 用于证明"渲染不修改数据"。

    用 `vars()` 而不是 `dataclasses.asdict()`：要能发现**新增的属性**
    （旧实现的缺陷正是渲染时往 Resume 上写 `_root` / `_pdf_path`）。
    """
    def obj(o):
        out = {}
        for k, v in vars(o).items():
            if isinstance(v, (list, tuple)):
                out[k] = [obj(x) if hasattr(x, "__dict__") else x for x in v]
            elif hasattr(v, "__dict__"):
                out[k] = obj(v)
            else:
                out[k] = v
        return out
    return obj(resume)


def main() -> int:
    """
    顶层整合入口：**一份简历从配置到产物，全在这里**。

    结构：

        5.1 ContentConfig   写什么（内容）
        5.2 RenderConfig    怎么排（留白 + 版式 + 输出）
        5.3 default_content 覆盖全部字段的默认内容
        5.4 本函数          校验 -> 渲染 -> 验收断言

    跑法：`py ResumeCore.py`
    """
    import contextlib
    import io

    print("=" * 66)
    print("ResumeCore 顶层整合入口")
    print("=" * 66)

    # ---- 1. 配置：内容 + 呈现 ----
    content = default_content()
    cfg = RenderConfig()
    print(f"\n【1. 内容】{content.describe()}")
    print(f"【2. 留白】{cfg.spacing.describe()}")
    print(f"【3. 版式】{cfg.theme.page_width:.0f}×{cfg.theme.page_height:.0f}mm  "
          f"分栏比 {list(cfg.theme.column_ratio)}  "
          f"描述体 {cfg.theme.desc_mode}  "
          f"联系方式图标 {cfg.theme.contact_icon_width}mm/缩进 "
          f"{cfg.theme.contact_left_indent}mm/行距 {cfg.theme.contact_gap}mm")

    # ---- 2. 校验：一次报全所有问题；**警告不阻断** ----
    report = cfg.validate(content)
    if not report.ok:
        print(f"\n【4. 校验】❌ 发现 {len(report.problems)} 个硬错误：")
        for p in report.problems:
            print(f"    - {p}")
        return 1
    print(f"\n【4. 校验】✅ 配置无冲突"
          f"{f'（{len(report.warnings)} 条警告）' if report.warnings else ''}")
    for w in report.warnings:
        print(f"    ⚠️  {w}")

    # ---- 3. 渲染 ----
    resume = content.to_resume()
    with contextlib.redirect_stdout(io.StringIO()):
        path = cfg.render(resume)
    size = os.path.getsize(path)
    print(f"【5. 渲染】✅ {path}  ({size} 字节)")

    # ---- 4. 渲染不修改数据（整合路径也要守）----
    check_resume = content.to_resume()
    before = _snapshot(check_resume)
    with contextlib.redirect_stdout(io.StringIO()):
        cfg.render(check_resume, output_dir=os.path.join(
            os.path.dirname(path), "again"))
    after = _snapshot(check_resume)
    same = before == after
    print(f"【6. 幂等】{'✅' if same else '❌'} 渲染未修改内容容器")

    # ---- 5. 同一内容 × 不同留白：批量能力的演示 ----
    print("\n【7. 同一内容 × 三种留白】")
    for label, sp in (("compact", Spacing.compact()),
                      ("默认", Spacing()),
                      ("loose", Spacing.loose())):
        sub = os.path.join(os.path.dirname(path), f"spacing_{label}")
        with contextlib.redirect_stdout(io.StringIO()):
            p2 = cfg.render(content, output_dir=sub, spacing=sp)
        print(f"    {label:<9} {os.path.getsize(p2):>7} 字节  {p2}")

    print("\n【8. 配置快照（为阶段二的外部配置文件铺路）】")
    snap = cfg.to_dict()
    print(f"    留白 {len(snap['spacing'])} 项 / 版式 {len(snap['theme'])} 项")

    print("\n" + "=" * 66)
    if not same:
        print("❌ 整合路径有问题（渲染修改了内容）")
        return 1
    print("✅ 整合入口通过；下面继续跑验收断言 V1–V10")
    print("=" * 66)
    return _selftest()


def _selftest() -> int:
    """顶层验收自检（返回进程退出码）"""
    import contextlib
    import hashlib
    import io
    import tempfile
    import dataclasses

    # 自检产物目录。默认写到工作区的 ./output/_resumecore_selftest/，
    # 便于直接翻看每个断言的产物。
    # 想不污染工作区就设环境变量：DSH_RESUME_SELFTEST_TMP=1
    if os.environ.get("DSH_RESUME_SELFTEST_TMP") == "1":
        out_root = os.path.join(tempfile.gettempdir(), "_resumecore_selftest")
    else:
        out_root = os.path.join("./output", "_resumecore_selftest")

    os.makedirs(out_root, exist_ok=True)
    ok = True

    def check(tag: str, cond: bool, msg: str = "") -> None:
        nonlocal ok
        print(f"  {'✅' if cond else '❌'} {tag}" + (f" —— {msg}" if msg else ""))
        if not cond:
            ok = False

    def quiet(fn, *a, **k):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*a, **k)

    def digest(path: str) -> str:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    print("=" * 66)
    print("ResumeCore 顶层自检")
    print("=" * 66)
    from datetime import timezone
    DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)   # 固定创建时间 → 才可能逐字节复现

    # ---- V1 渲染不修改数据（含不新增属性）----
    print("\n【V1】渲染不得修改数据容器")
    r = _sample("甲")
    before = _snapshot(r)
    p1 = quiet(render, r, out_root, creation_date=DATE, filename="v1.pdf")
    after = _snapshot(r)
    check("vars(resume) 渲染前后完全一致", before == after,
          "渲染写回了数据" if before != after else "")
    if before != after:
        extra = set(after) - set(before)
        if extra:
            print(f"      多出的属性：{sorted(extra)}")
        for k in set(before) & set(after):
            if before[k] != after[k]:
                print(f"      变化的属性：{k}")
    check("未新增 _root / _pdf_path 之类的渲染残留",
          not hasattr(r, "_root") and not hasattr(r, "_pdf_path"))

    # ---- V8 creation_date 生效：同数据逐字节相同 ----
    print("\n【V8】固定创建时间 → 逐字节可复现")
    r2 = _sample("甲")
    pa = quiet(render, r2, out_root, creation_date=DATE, filename="v8a.pdf")
    pb = quiet(render, r2, out_root, creation_date=DATE, filename="v8b.pdf")
    check("同一对象两次渲染逐字节相同", digest(pa) == digest(pb),
          f"{digest(pa)[:12]} vs {digest(pb)[:12]}")

    # ---- V2/V3 幂等与无跨实例污染 ----
    print("\n【V2/V3】幂等性与跨实例隔离")
    outs = [quiet(render, _sample("甲"), out_root, creation_date=DATE,
                  filename=f"v3_{i}.pdf") for i in range(3)]
    ds = {digest(p) for p in outs}
    check("三个独立对象渲三次结果一致", len(ds) == 1, f"得到 {len(ds)} 种结果")

    # ---- V4 空字段降级 ----
    print("\n【V4】空字段不产出异常版面、不抛异常")
    lean = Resume(intend_job="工程师",
                  profile=Profiles(name="只有名字"),
                  sections=[Section(title="教育背景", details=[
                      Details(key="某校", description="")])])
    try:
        quiet(render, lean, out_root, creation_date=DATE, filename="v4.pdf")
        check("只有姓名 + 一条空描述：可渲染", True)
    except Exception as e:
        check("只有姓名 + 一条空描述：可渲染", False, f"{type(e).__name__}: {e}")
    try:
        quiet(render, Resume(profile=Profiles(name="X")), out_root)
        check("无章节且无总结：应明确报错", False, "没有报错")
    except RenderError:
        check("无章节且无总结：明确报错", True)
    except Exception as e:
        check("无章节且无总结：明确报错", False, f"报错类型不对：{type(e).__name__}")
    try:
        quiet(render, Resume(profile=Profiles(telephone="1"),
                             summary="x"), out_root)
        check("缺姓名：应明确报错", False, "没有报错")
    except RenderError:
        check("缺姓名：明确报错", True)
    except Exception as e:
        check("缺姓名：明确报错", False, f"报错类型不对：{type(e).__name__}")

    # ---- V9 联系方式：行高必须由文字决定，不得被图标撑起 ----
    # 起因（用户目视发现）：联系方式行距太大。
    # 根因是 `add_info` 的整行高 = max(文本最小高, 图标占高)，图标 4mm 把行高顶到
    # 7mm（文本只有 5.08mm），再叠 5mm 留白 → 行间距 12mm ≈ 文字高的 2.4 倍。
    # 现改用 `add_para`（行高由内容决定 + 图标锚定首行中心）。
    print("\n【V9】联系方式行高由文字决定（不被图标撑起）")
    r9 = Resume(intend_job="工程师",
                profile=Profiles(name="测试", telephone="138-0000-0000",
                                 email="a@b.com", locate="某市"))
    r9.add_section(Section(title="X", details=[Details(key="k")]))
    th9 = Theme()
    root9 = quiet(build_layout, r9, th9, Spacing())
    lc9 = root9.find_by_name("Root_left_column")
    paras9 = [c for c in lc9.children if "_para_" in c.name]
    check("联系方式用 add_para 生成（找到 _para_ 节点）", len(paras9) == 3,
          f"实际 {len(paras9)} 条")
    line_h9 = (th9.contact_text_style.font_size
               * (th9.contact_text_style.line_height_ratio or 1.2) * PT_TO_MM)
    row_h9 = paras9[0].get_effective_height() if paras9 else 0.0
    # 行高应等于文本行高；若被图标撑起会明显大于它（旧实现 7.00 vs 5.08）
    check(f"行高 = 文本行高（{row_h9:.3f} vs {line_h9:.3f}）",
          abs(row_h9 - line_h9) < 0.01,
          "行高被图标撑起" if abs(row_h9 - line_h9) >= 0.01 else "")
    # 相邻两条的间距必须 = 行高 + theme.contact_gap
    if len(paras9) >= 2:
        pitch9 = paras9[1].get_absolute_y() - paras9[0].get_absolute_y()
        want9 = line_h9 + th9.contact_gap
        check(f"行间距 = 行高 + contact_gap（{pitch9:.3f} vs {want9:.3f}）",
              abs(pitch9 - want9) < 0.01)
    # 图标左缩进必须 > 0，否则图标贴在蓝底左栏边界上（用户目视发现过）
    if paras9:
        icon_x9 = min(
            (g.get_layout_info()["effective"]["x"]
             for c in paras9[0].children for g in c.children
             if type(g).__name__ == "ImageObject"),
            default=None)
        lc_x9 = lc9.get_layout_info()["effective"]["x"]
        if icon_x9 is None:
            check("能在段落里找到图标对象", False)
        else:
            check(f"图标有左缩进（{icon_x9 - lc_x9:.2f}mm > 0）",
                  icon_x9 - lc_x9 > 0.5,
                  "图标贴在蓝底边界上" if icon_x9 - lc_x9 <= 0.5 else "")
    # 图标必须锚定在**首行中心**（不是整块中心）
    if paras9:
        p0 = paras9[0]
        icon0 = None
        for c in p0.children:
            for g in c.children:
                if type(g).__name__ == "ImageObject":
                    icon0 = g
        if icon0 is not None:
            dy0 = p0.get_absolute_y()
            ic_c = icon0.get_absolute_y() + icon0.get_effective_height() / 2 - dy0
            check(f"图标中心 = 首行中心（{ic_c:.4f} vs {line_h9/2:.4f}）",
                  abs(ic_c - line_h9 / 2) < 0.001)
        else:
            check("能在段落里找到图标对象", False)

    # ---- V10 左栏左边缘对齐 + 技能标题加粗 ----
    # 起因（用户目视发现）：技能标题是 2mm、正文 0mm、联系方式 0mm（贴蓝底），
    # 三者参差不齐；且技能标题非粗体，观感偏弱。
    print("\n【V10】左栏左边缘对齐 + 技能标题加粗")
    th10 = Theme()
    check("技能标题为粗体", th10.skills_title_style.bold is True,
          f"bold={th10.skills_title_style.bold}")
    check("技能标题字号未被改动（14pt）",
          th10.skills_title_style.font_size == STYLES["skillsawards_title"].font_size,
          f"{th10.skills_title_style.font_size} vs "
          f"{STYLES['skillsawards_title'].font_size}")
    check("中层的 skillsawards_title 未被污染（仍非粗体）",
          STYLES["skillsawards_title"].bold is False,
          "顶层 replace 应派生新对象，不能改共享 STYLES")
    # 技能标题与正文的左边缘必须一致
    root10 = quiet(build_layout, _sample("甲"), th10, Spacing())
    lc10 = root10.find_by_name("Root_left_column")
    base_x10 = lc10.get_layout_info()["effective"]["x"]

    def text_x10(o):
        xs = []
        if type(o).__name__ == "TextObject":
            xs.append(o.get_layout_info()["effective"]["x"] + o.padding.left)
        for c in o.children:
            xs += text_x10(c)
        return xs

    t_x = text_x10(lc10.find_by_name(f"{lc10.name}_skills_title_content"))
    b_x = text_x10(lc10.find_by_name(f"{lc10.name}_skills_details"))
    if t_x and b_x:
        off_t, off_b = min(t_x) - base_x10, min(b_x) - base_x10
        check(f"技能标题与正文左边缘一致（{off_t:.2f} vs {off_b:.2f}）",
              abs(off_t - off_b) < 0.01 and off_t > 0.5)
    else:
        check("能找到技能标题与正文的文字对象", False)

    # ---- V11 多版本管理：素材共享 + 装配隔离 ----
    # 起因：旧仓库的 `BlankResumeTemplateWithTestData.py` / `Resume_MultiVersion_main.py`
    # 要的就是"一份基础信息 → 投多个岗位"。核心风险是**素材被装配过程污染** ——
    # 一旦污染，第二个版本就会悄悄变形，而且很难查。
    print("\n【V11】多版本：素材共享 + 装配隔离")
    _v11_sec = Section(title="测试节")
    _v11_sec.add_detail(Details(key="A"))
    _v11_sec.add_detail(Details(key="B"))
    _book = ResumeBook(profile=Profiles(name="测试"),
                       output_dir=os.path.join(out_root, "v11"))
    _book.add_section(_v11_sec)
    # 同名节默认必须报错（静默覆盖会让"池里到底是哪一份"不可知）
    try:
        _book.add_section(Section(title="测试节"))
        check("同名节默认报错", False, "没有报错")
    except ValueError:
        check("同名节默认报错（要覆盖须显式 replace=True）", True)
    # 引用不存在的节必须被体检抓到
    _bad_book = ResumeBook(profile=Profiles(name="X"))
    _bad_book.add_version(ResumeVersion(name="bad", sections=["不存在"]))
    check("引用不存在的节会被体检抓到", len(_bad_book.validate()) == 1,
          str(_bad_book.validate()))
    _book.add_version(ResumeVersion(name="v1", job="J1",
                                    sections=["测试节"], summary="s1"))
    _book.add_version(ResumeVersion(name="v2", job="J2",
                                    sections=["测试节"], summary="s2"))
    check("装配前体检通过", _book.validate() == [], str(_book.validate()))

    # 关键：装配结果是**深拷贝**，改它不影响素材池，也不影响另一个版本
    _r1 = _book.build("v1")
    _r2 = _book.build("v2")
    check("装配结果不是素材本身（深拷贝）",
          _r1.sections[0] is not _book.find_section("测试节"))
    _before = len(_book.find_section("测试节").details)
    _r1.sections[0].details.pop()
    _after = len(_book.find_section("测试节").details)
    check(f"改装配结果不污染素材池（{_before} -> {_after}）", _before == _after)
    check("另一个版本不受影响", len(_r2.sections[0].details) == _before)
    check("不同版本文件名不冲突",
          _r1.get_file_name() != _r2.get_file_name(),
          f"{_r1.get_file_name()} vs {_r2.get_file_name()}")

    # ---- V12 个人评价：与技能块同视觉模板，放在左栏最后 ----
    # 需求："用与技能与荣誉同样的视觉模板与代码写法写个人评价"。
    # 所以这里卡两件事：**位置对**（左栏最后、底部留白之前）与
    # **模板等价**（标题行高、正文自适应与技能块逐项相同）。
    print("\n【V12】个人评价（左栏，复用技能块的视觉模板）")
    _ev12 = Resume(
        profile=Profiles(name="测试", telephone="1",
                         evaluation="第一行评价。\n第二行评价。"),
        skills_awards=SkillsAwards(skills=["技能一"], awards=["荣誉一"]),
        sections=[Section(title="S", details=[Details(key="k")])])
    _root12 = quiet(build_layout, _ev12, Theme(), Spacing())
    _lc12 = _root12.find_by_name("Root_left_column")
    _names12 = [c.name for c in _lc12.children]
    check("个人评价渲染在左栏", any("evaluation_title" in n for n in _names12))
    _i_eval = next((i for i, n in enumerate(_names12)
                    if "evaluation_title" in n), None)
    _i_bot = _names12.index("Lead_Left_Below_All")
    check("评价在底部留白之前", _i_eval is not None and _i_eval < _i_bot,
          f"评价在索引 {_i_eval}，底部留白在 {_i_bot}")
    check("底部留白是左栏最后一个元素", _i_bot == len(_names12) - 1)

    def _block_h12(prefix):
        got = {}
        for c in _lc12.children:
            if c.name.startswith(prefix):
                got[c.name.rsplit("_", 1)[-1]] = round(c.get_effective_height(), 4)
        return got

    _sk12 = _block_h12("Root_left_column_skills")
    _ev_blk = _block_h12("Root_left_column_evaluation")
    check("标题行高与技能块一致",
          _sk12.get("content") == _ev_blk.get("content"),
          f"{_sk12.get('content')} vs {_ev_blk.get('content')}")
    check("正文高度与技能块一致（同为内容结算）",
          _sk12.get("details") == _ev_blk.get("details"),
          f"{_sk12.get('details')} vs {_ev_blk.get('details')}")

    _empty12 = Resume(profile=Profiles(name="测试", telephone="1"),
                      sections=[Section(title="S", details=[Details(key="k")])])
    _root12b = quiet(build_layout, _empty12, Theme(), Spacing())
    _lc12b = _root12b.find_by_name("Root_left_column")
    check("空评价整块不渲染",
          not any("evaluation" in c.name for c in _lc12b.children))
    check("空评价不留多余空隙（不得多出 spacer）",
          not any("eval" in c.name for c in _lc12b.children))

    _both12 = Resume(profile=Profiles(name="测试", telephone="1",
                                      evaluation="左栏评价。"),
                     sections=[Section(title="S", details=[Details(key="k")])],
                     summary="右栏总结。")
    _root12c = quiet(build_layout, _both12, Theme(), Spacing())
    check("左栏评价与右栏总结可共存",
          any("evaluation" in c.name
              for c in _root12c.find_by_name("Root_left_column").children)
          and any("summary" in c.name
                  for c in _root12c.find_by_name("Root_right_column").children))
    check("Theme.evaluation_title 默认为「个人评价」",
          Theme().evaluation_title == "个人评价")
    check("Profiles 已去掉从不渲染的 summary 字段",
          not hasattr(Profiles(), "summary"))

    # ---- V5 不溢出 ----
    # ⚠️ 两层检查都要做：
    #   ① 页面边界 —— 元素绝对框不得越出纸面
    #   ② 父内容区包含 —— 子元素不得越出父的**内容区**（去掉 padding）
    #   只做①会漏掉"父没撑够高、子溢到父外但仍在纸内"这类缺陷。
    print("\n【V5】元素不得溢出（页面边界 + 父内容区包含）")
    root = quiet(build_layout, _sample("甲"))
    th0 = Theme()
    page_r = th0.page_width
    page_b = th0.page_height

    worst = {"x": (0.0, ""), "y": (0.0, "")}
    contain = {"r": (0.0, ""), "b": (0.0, "")}

    def scan(o, parent=None):
        i = o.get_layout_info()["effective"]
        ox, oy = i["x"] + i["w"], i["y"] + i["h"]
        if ox - page_r > worst["x"][0]:
            worst["x"] = (ox - page_r, o.name)
        if oy - page_b > worst["y"][0]:
            worst["y"] = (oy - page_b, o.name)
        if parent is not None:
            pi = parent.get_layout_info()["effective"]
            pp = parent.padding
            pr = pi["x"] + pi["w"] - pp.right      # 父内容区右界
            pb = pi["y"] + pi["h"] - pp.bottom     # 父内容区下界
            if ox - pr > contain["r"][0]:
                contain["r"] = (ox - pr, f"{o.name} ⊄ {parent.name}")
            if oy - pb > contain["b"][0]:
                contain["b"] = (oy - pb, f"{o.name} ⊄ {parent.name}")
        for c in o.children:
            scan(c, o)

    scan(root)
    check("不越出纸面（右/下）",
          worst["x"][0] <= 0.01 and worst["y"][0] <= 0.01,
          f"右 {worst['x'][0]:+.2f}（{worst['x'][1]}）"
          f" 下 {worst['y'][0]:+.2f}（{worst['y'][1]}）"
          if max(worst["x"][0], worst["y"][0]) > 0.01 else "")
    check("子元素被父内容区包含",
          contain["r"][0] <= 0.01 and contain["b"][0] <= 0.01,
          f"右 {contain['r'][0]:+.2f}（{contain['r'][1]}）"
          f" 下 {contain['b'][0]:+.2f}（{contain['b'][1]}）"
          if max(contain["r"][0], contain["b"][0]) > 0.01 else "")

    # ---- V6 数据模型段零引擎依赖 ----
    print("\n【V6】数据模型不认识引擎/PDF")
    banned = (LayoutObject, Style, Padding, FPDF)
    offenders = []
    for cls in (Profiles, SkillsAwards, Details, Section, Resume):
        for k, v in vars(cls()).items() if not dataclasses.is_dataclass(cls) else []:
            if isinstance(v, banned):
                offenders.append(f"{cls.__name__}.{k}")
        for f_ in dataclasses.fields(cls) if dataclasses.is_dataclass(cls) else []:
            if f_.type in ("LayoutObject", "Style", "Padding", "FPDF"):
                offenders.append(f"{cls.__name__}.{f_.name}")
    check("数据类的字段里没有排版对象", not offenders, ", ".join(offenders))
    check("Resume 上没有渲染方法",
          not any(hasattr(Resume, n) for n in
                  ("Generate", "render", "_fill_left_column", "get_root")))

    # ---- V7 一个 PDF 装多份 ----
    print("\n【V7】一个 PDF 可装多份简历")
    doc = make_pdf()
    render_into(doc, [_sample("甲"), _sample("乙")])
    multi = os.path.join(out_root, "v7.pdf")
    doc.output(multi)
    n_pages = open(multi, "rb").read().count(b"/Type /Page") - \
        open(multi, "rb").read().count(b"/Type /Pages")
    check("两份简历 → 2 页", n_pages == 2, f"实际 {n_pages} 页")

    # ---- 附加：批量渲染互不影响 ----
    print("\n【附加】render_many 批量：共享 spacing 不被修改")
    sp = Spacing()
    sp_before = dataclasses.asdict(sp)
    paths = quiet(render_many, [_sample("甲"), _sample("乙"), _sample("丙")],
                  out_root, spacing=sp, creation_date=DATE)
    check("批量产出 3 份", len(paths) == 3)
    check("共享的 spacing 未被修改", dataclasses.asdict(sp) == sp_before)
    check("批量各份互不相同", len({digest(p) for p in paths}) == 3)

    print("\n" + "=" * 66)
    print("✅ 顶层验收自检全部通过" if ok else "❌ 顶层验收自检有失败项")
    print(f"   产物目录：{out_root}")
    return 0 if ok else 1


# ============================================================================
# 6. 多版本管理（一份基础信息 → 投多个岗位）
# ============================================================================

@dataclass
class ResumeVersion:
    """
    一个**投递版本**：同一份基础信息（`Profiles` / `SkillsAwards`）下，
    挑选哪些节、配哪一档留白。

    存在意义：投不同公司时，改动很小（挑几节、换留白、改标题），
    但直接复制整份 `Resume` 会导致"改一处要改 N 处"。
    这里把差异压缩到"选节 + 留白"两件事上，基础信息与节素材都**共享**。

    用法（详见 `demo_multi_version.py`）：

        v = ResumeVersion(name="腾讯", company="腾讯科技", job="后端开发工程师",
                          sections=["教育背景", "项目经历"],
                          summary="…")
    """
    name: str = ""                                  # 版本名（仅用于日志）
    company: str = ""
    job: str = ""
    sections: List[str] = field(default_factory=list)   # 节的标题，按序取用
    summary: str = ""
    spacing: Optional[Spacing] = None               # None = 用 ResumeBook 的默认
    theme: Optional[Theme] = None                   # None = 用 ResumeBook 的默认
    extra_sections: List[Section] = field(default_factory=list)  # 本版本独有的节

    def describe(self) -> str:
        return (f"{self.name or self.job or '未命名'}："
                f"{len(self.sections)} 节 + {len(self.extra_sections)} 独有节"
                f"（{self.company or '未指定公司'} / {self.job or '未指定职位'}）")


@dataclass
class ResumeBook:
    """
    简历素材库 + 多版本装配台。**这是"批量生成"的落地形式。**

    三件事：

        1. `profile` / `skills_awards`  —— 基础信息，所有版本共享
        2. `section_pool`               —— 节素材池，按 `Section.title` 取用
        3. `versions`                   —— 各投递版本（选节 + 留白）

    装配时**深拷贝**选中的节，所以多个版本之间互不干扰
    —— 一个版本里删掉一条详情，不会影响另一个版本。

    用法：

        book = ResumeBook(profile=me, skills_awards=sa, spacing=Spacing())
        book.add_section(edu)            # 放进素材池
        book.add_version(ResumeVersion(name="腾讯", sections=["教育背景"], ...))
        report = book.render_all(output_dir="output")
        book.summarize(report)           # 一行一版地打印结果

    只渲染某几个版本：

        book.render_all(only=["腾讯", "华为"])
        book.enabled = ["腾讯"]          # 或在 book 上设白名单
    """

    profile: Profiles = field(default_factory=Profiles)
    skills_awards: SkillsAwards = field(default_factory=SkillsAwards)
    section_pool: List[Section] = field(default_factory=list)
    versions: List[ResumeVersion] = field(default_factory=list)
    spacing: Spacing = field(default_factory=Spacing)
    theme: Theme = field(default_factory=Theme)
    output_dir: str = "./output"
    enabled: Optional[List[str]] = None      # None = 全部；否则只渲染列出的版本名

    # ---- 素材 ----

    def add_section(self, section: Section, *, replace: bool = False) -> 'ResumeBook':
        """
        把一节放进素材池（按 `title` 索引），返回 self 以便链式调用。

        Args:
            replace: 已存在同名节时是否覆盖。默认 False 会**报错** ——
                     静默覆盖会让"素材池里到底是哪一份"变得不可知。
        """
        title = section.title
        if not title:
            raise ValueError("ResumeBook.add_section: 节的 title 不能为空（用作取用键）")
        existing = self.find_section(title)
        if existing is not None and not replace:
            raise ValueError(
                f"ResumeBook.add_section: 素材池里已有标题为 {title!r} 的节。"
                f"要覆盖请传 replace=True")
        if existing is not None:
            self.section_pool[self.section_pool.index(existing)] = section
        else:
            self.section_pool.append(section)
        return self

    def find_section(self, title: str) -> Optional[Section]:
        """按标题取素材池里的节（没有则 None）"""
        for sec in self.section_pool:
            if sec.title == title:
                return sec
        return None

    def add_version(self, version: ResumeVersion) -> 'ResumeBook':
        self.versions.append(version)
        return self

    # ---- 装配 ----

    def build(self, version: Union[ResumeVersion, str]) -> Resume:
        """
        把一个版本装配成 `Resume`（**深拷贝**节，版本之间互不干扰）。

        Args:
            version: `ResumeVersion` 对象，或版本名（在 `versions` 里查）
        """
        if isinstance(version, str):
            found = self.find_version(version)
            if found is None:
                raise KeyError(f"ResumeBook.build: 找不到名为 {version!r} 的版本")
            version = found

        sections: List[Section] = []
        for title in version.sections:
            sec = self.find_section(title)
            if sec is None:
                raise KeyError(
                    f"ResumeBook.build: 版本 {version.name!r} 引用了素材池里没有的节 "
                    f"{title!r}；池中现有：{[x.title for x in self.section_pool]}")
            sections.append(copy.deepcopy(sec))
        for sec in version.extra_sections:
            sections.append(copy.deepcopy(sec))

        return Resume(
            intend_company=version.company,
            intend_job=version.job,
            profile=copy.deepcopy(self.profile),
            skills_awards=copy.deepcopy(self.skills_awards),
            sections=sections,
            summary=version.summary,
        )

    def find_version(self, name: str) -> Optional[ResumeVersion]:
        for v in self.versions:
            if v.name == name:
                return v
        return None

    def active_versions(self, only: Optional[Sequence[str]] = None
                        ) -> List[ResumeVersion]:
        """要渲染哪些版本：`only` 优先，其次 `self.enabled`，都没有则全部"""
        names = list(only) if only else self.enabled
        if not names:
            return list(self.versions)
        return [v for v in self.versions if v.name in names]

    # ---- 渲染 ----

    def render_all(self, output_dir: Optional[str] = None, *,
                   only: Optional[Sequence[str]] = None,
                   creation_date: Optional[datetime] = None,
                   debug: int = 0) -> List[tuple]:
        """
        渲染选中的全部版本。

        Returns:
            `[(版本, Resume, 产物路径), ...]`
        """
        out = output_dir if output_dir is not None else self.output_dir
        result: List[tuple] = []
        for v in self.active_versions(only):
            resume = self.build(v)
            kw = {}
            if v.spacing is not None:
                kw["spacing"] = v.spacing
            if v.theme is not None:
                kw["theme"] = v.theme
            path = render(resume, out, creation_date=creation_date,
                          debug=debug, **kw)
            result.append((v, resume, path))
        return result

    def validate(self) -> List[str]:
        """
        装配前检查：所有版本引用的节是否都在素材池里。

        返回问题清单（空 = 没问题）。这就是"投递前先体检"，
        避免渲染到一半才发现某个版本引用了不存在的节。
        """
        pool = {sec.title for sec in self.section_pool}
        problems: List[str] = []
        seen: Dict[str, int] = {}
        for v in self.versions:
            if not v.name:
                problems.append("有一个版本没有 name")
            seen[v.name] = seen.get(v.name, 0) + 1
            missing = [t for t in v.sections if t not in pool]
            if missing:
                problems.append(
                    f"版本 {v.name!r} 引用了素材池里没有的节：{missing}")
            if not v.sections and not v.extra_sections:
                problems.append(f"版本 {v.name!r} 一节都没有")
        for name, n in seen.items():
            if n > 1:
                problems.append(f"版本名 {name!r} 重复出现 {n} 次（会互相覆盖产物文件名）")
        return problems

    def summarize(self, rendered: Optional[Sequence[tuple]] = None) -> None:
        """打印素材池与渲染结果（一行一版）"""
        print(f"  素材池：{len(self.section_pool)} 节 "
              f"{[s.title for s in self.section_pool]}")
        print(f"  版本数：{len(self.versions)}")
        if rendered is None:
            return
        for v, resume, path in rendered:
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
            print(f"    ✅ {v.describe():<52} {size:>7} 字节  {path}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "skills_awards": self.skills_awards.to_dict(),
            "section_pool": [s.to_dict() for s in self.section_pool],
            "versions": [dataclasses.asdict(v) if not isinstance(v, ResumeVersion)
                         else {
                             "name": v.name, "company": v.company, "job": v.job,
                             "sections": list(v.sections), "summary": v.summary,
                             "has_spacing": v.spacing is not None,
                             "has_theme": v.theme is not None,
                             "extra_sections": [s.to_dict() for s in v.extra_sections],
                         } for v in self.versions],
        }


if __name__ == "__main__":
    raise SystemExit(main())

