"""
================================================================================
我的简历（个人数据 —— 本文件已被 .gitignore 排除，不会被提交）
================================================================================
用法：

    1. 把下面 [填写] 标记处换成你的信息
    2. 跑：py my_resumes.py
    3. 产物在 ./output_multi/

想只生成某几个版本：

    py my_resumes.py --only 后端开发岗

参考：demo_multi_version.py 是一份**虚构的**完整示例（含三个真实感版本）。
可调项总表见 SKILLS.md 的 H 节；计划中的改动见 I 节。

三件事只需理解一次：

    Profiles / SkillsAwards      —— 基础信息，所有版本共享，只写一遍
    Section（素材池）            —— 每一节素材只定义一次，多个版本复用
    ResumeVersion                —— 一个投递版本 = 选哪些节 + 配哪档留白

所以"投不同公司"通常**只需要加一个 ResumeVersion**，不用复制任何内容。
================================================================================
"""

import sys

from ResumeCore import (
    Details,
    Profiles,
    ResumeBook,
    ResumeVersion,
    Section,
    SkillsAwards,
    Theme,          # 版式（页面、边距、缩进、配色…）—— 逐版本可传
)
from ResumeTemplate import Spacing   # 留白（节间距、详情间距…）—— 逐版本可传

OUT = "./output_multi"


# ============================================================================
# 1. 基础信息（所有版本共享）—— 只改这一处
# ============================================================================

profile = Profiles(
    photo=r".\Resources\woman_student.png",   # 证件照，不需要就留空串
    name="[填写] 姓名",
    telephone="[填写] 电话",
    email="[填写] 邮箱",
    locate="[填写] 现居城市",
    social_media_qq="",                       # 不需要就留空串（留空则整行不渲染）
    social_media_wechat="",
    contact_address="",
    title="[填写] 求职头衔",                   # 可留空
    website="",
    # 个人评价 —— 渲染在左栏**最后**，视觉模板与技能/证书/荣誉相同。
    # 留空则整块不渲染。标题文案由 Theme.evaluation_title 决定（默认「个人评价」）。
    # 注意：这与 Resume.summary（渲染在**右栏**的个人总结）是两回事。
    evaluation="[填写] 一句话评价，或留空串。",
)

skills_awards = SkillsAwards(
    # 三块标题：留 None 用 Theme 的默认（掌握技能 / 获得证书 / 获得荣誉）
    skills=[
        "[填写] 熟练 | 技能一",
        "[填写] 熟练 | 技能二",
    ],
    qualifications=[
        "[填写] 证书",
    ],
    awards=[
        "[填写] 荣誉",
    ],
)


# ============================================================================
# 2. 素材池 —— 每一节只定义一次，多个版本复用
# ============================================================================

# 给每条 Details 填：key（学校/项目/公司名）、during_time（起讫时间）、
# tags（专业/技术栈）、description（描述，支持 \n 分段）
# ⚠️ 不需要写 description_height —— 高度由内容自动结算

教育背景 = Section(
    icon=r".\Resources\icon_Education_History.png",   # 节标题图标，可换
    title="教育背景",                                  # ← 这个 title 就是版本里引用它的键
    details=[
        Details(
            key="[填写] 学校名",
            during_time="[填写] 2020.09 - 2024.06",
            tags="[填写] 专业 | 本科",
            description="[填写] 主修课程：…\n[填写] 毕业论文：…",
        ),
    ],
)

项目经历 = Section(
    icon=r".\Resources\icon_Project_History.png",
    title="项目经历",
    details=[
        Details(
            key="[填写] 项目名",
            during_time="[填写] 2025.03 - 2025.06",
            tags="[填写] 技术栈",
            description="[填写] 做了什么、用了什么、结果如何。\n[填写] 第二行。",
        ),
        Details(
            key="[填写] 项目名二",
            during_time="[填写] 2024.09 - 2024.12",
            tags="[填写] 技术栈",
            description="[填写] 描述。",
        ),
    ],
)

实习经历 = Section(
    icon=r".\Resources\icon_Project_History.png",
    title="实习经历",
    details=[
        Details(
            key="[填写] 公司名",
            during_time="[填写] 2024.07 - 2024.09",
            tags="[填写] 岗位",
            description="[填写] 职责与产出。",
        ),
    ],
)


# ============================================================================
# 3. 版本定义 —— 投不同公司通常只需加一个 ResumeVersion
# ============================================================================

def build_book() -> ResumeBook:
    book = ResumeBook(
        profile=profile,
        skills_awards=skills_awards,
        spacing=Spacing(),          # ← 全局默认留白；想整体调松紧改这里
        # theme=Theme(),            # ← 全局默认版式；想整体改配色/边距加这行
        output_dir=OUT,
    )

    # ---- 素材入池（按 title 取用；同名会报错，避免"池里到底是哪一份"不可知）----
    book.add_section(教育背景)
    book.add_section(项目经历)
    # book.add_section(实习经历)      # 有需要就打开

    # ---- 版本 1：通用调试版（建议留着，用于快速检查版式）----
    book.add_version(ResumeVersion(
        name="通用调试",
        company="通用调试版",
        job="通用调试版",
        sections=["教育背景", "项目经历"],
        summary="[填写] 一句话总结，或留空串。",
    ))

    # ---- 版本 2：投某公司 A ----
    book.add_version(ResumeVersion(
        name="公司A-岗位名",
        company="[填写] 公司A",
        job="[填写] 岗位名",
        # sections 的**顺序 = 呈现顺序**：想突出项目就把"项目经历"放前面
        sections=["项目经历", "教育背景"],
        # 逐版本调留白（不写则用 book.spacing）：
        #   Spacing.compact()            整体收紧 ×0.7
        #   Spacing.loose()              整体放松 ×1.3
        #   Spacing(between_details=4.0) 单项微调
        # spacing=Spacing(between_details=4.0, between_sections=6.0),
        summary="[填写] 针对该岗位的一句话总结。",
    ))

    # ---- 版本 3：投某公司 B（演示逐版本换版式）----
    book.add_version(ResumeVersion(
        name="公司B-岗位名",
        company="[填写] 公司B",
        job="[填写] 岗位名",
        sections=["项目经历", "教育背景"],
        # 逐版本调版式（不写则用 book.theme）：
        #   Theme(page_padding=14,                      # 页边距
        #         column_ratio=(1.0, 2.2),              # 左右栏比例
        #         right_column_padding_left=10,         # 右栏左内边距
        #         contact_left_indent=4,                # 联系方式图标左缩进
        #         contact_gap=2.5,                      # 联系方式行距
        #         skills_left_indent=4,                 # 技能块左缩进
        #         desc_mode="inline",                   # 描述体：inline 整段 / para 分段
        #         left_column_color=Color(0, 128, 96),  # 左栏底色（需 from LayoutEngine import Color）
        #         contact_icons={"email": r".\Resources\email.png"})
        summary="[填写] 总结。",
    ))

    # 加更多版本就继续 add_version，模板同上。
    return book


# ============================================================================
# 4. 入口（一般不用改）
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("我的简历 —— 批量生成")
    print("=" * 70)

    book = build_book()

    # 装配前体检：版本引用的节是否都在素材池里、版本名是否重复
    problems = book.validate()
    if problems:
        print("❌ 装配前体检未通过：")
        for p in problems:
            print(f"    - {p}")
        print("\n提示：sections=[...] 里写的是 Section 的 title，必须先在素材池里 add_section。")
        raise SystemExit(1)
    print("✅ 装配前体检通过")

    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 < len(sys.argv):
            only = [sys.argv[i + 1]]

    print(f"\n【渲染】{'全部版本' if not only else only}")
    rendered = book.render_all(only=only)

    print("\n【结果】")
    book.summarize(rendered)
    print(f"\n产物目录：{OUT}")
    print("提示：改留白看 SKILLS.md 的 H 节；改版式同理。")
