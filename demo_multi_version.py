"""
================================================================================
简历多版本管理（一份基础信息 → 投多个岗位）
================================================================================
这是顶层「批量生成」的落地示例，对应旧仓库里的
`BlankResumeTemplateWithTestData.py` + `Resume_MultiVersion_main.py` 的意图。

三份文件的分工（延续旧需求文档的设计）：

    1. ResumeCore.py      数据模型 + 渲染器（**已实现**）
    2. 本文件              素材与版本定义（**可复制改造成你自己的**）
    3. 版本装配/批量渲染   由 `ResumeBook` 承担（在 ResumeCore 里）

核心思想：**基础信息与节素材只写一遍，版本之间只差"选哪些节 + 配哪档留白"。**

跑法：
    py demo_multi_version.py
    py demo_multi_version.py --only 腾讯-后端

产物：output_multi/{姓名}_{职位}_{公司}.pdf
"""

import sys

from ResumeCore import (
    Details,
    Profiles,
    ResumeBook,
    ResumeVersion,
    Section,
    SkillsAwards,
)
from ResumeTemplate import Spacing

OUT = "./output_multi"


# ============================================================================
# 1. 基础信息（所有版本共享）
# ============================================================================

profile = Profiles(
    photo=r".\Resources\woman_student.png",
    name="张三",
    telephone="114 5114 9810",
    locate="江苏 · 南京",
    email="exzmple@qq.com",
    social_media_qq="example",
    # social_media_wechat="WeChat_114514",
    # contact_address="",
    website="",
    title="",
    # 个人评价 —— 渲染在左栏最后，视觉模板与技能/证书/荣誉相同
    evaluation="踏实、能啃硬骨头，喜欢把复杂问题拆成清单。",
)

skills_awards = SkillsAwards(
    skills=[
        "熟练 | Word",
        "熟练 | Excel",
        "熟练 | PowerPoint",
        "熟练 | Python",
        "熟练 | C++",
        "入门 | AI辅助程序开发",
    ],
    qualifications=["CET_4", "CET_6"],
    awards=["治国理政一等奖"],
)


# ============================================================================
# 2. 节素材池 —— 每个 Section 只定义一次，多个版本复用
# ============================================================================

求学履历 = Section(
    icon=r".\Resources\icon_Education_History.png",
    title="求学履历",
    details=[
        Details(
            key="示例学校",
            during_time="2023.09 - 2027.06（预计）",
            tags="示例专业| 本科",
            description="主修课程：高等数学、大学物理、工程图学、C++语言程序设计及课程设计、"
                        "理论力学、材料力学、电工与电子技术、机械原理。"
                        "",
        ),
    ],
)

项目经历 = Section(
    icon=r".\Resources\icon_Project_History.png",
    title="项目经历",
    details=[
        Details(
            key="机械设计：齿轮减速器",
            during_time="2025.12 - 2026.01",
            tags="机械设计课程设计",
            description="自主设计齿轮减速箱，产出国标 CAD 机械装配图与零件图。",
        ),
        Details(
            key="3D 打印工装夹具",
            during_time="2026.07 - 2026.08",
            tags="3D建模 | 增材制造 | 已结项",
            description="为解决超声电机制造企业夹具过于笨重的问题，团队合作利用 3D 建模软件设计、"
                        "FDM 熔融沉积增材制造技术制造新夹具，产出 3D 零件图两套、夹具实物两套，"
                        "生产线工人反馈良好。",
        ),
        Details(
            key="Python 文档排版系统",
            during_time="2026.08 - 2026.09",
            tags="AI | Python | 个人项目 | 进行中",
            description="为解决各种文档在编辑过程中的排版错乱问题，基于 Python 并借助大语言模型"
                        "编写一套完整的 PDF 排版系统；本简历即是该项目的产出之一。",
        ),
        Details(
            key="基于 C++ 的 3D 渲染引擎",
            during_time="2026.07 - 至今",
            tags="AI | C++ | 个人项目 | 进行中",
            description="为学习 AI 编程的基本流程，基于 C++ 编写一套 3D 渲染库；"
                        "截至目前产出可用头文件库一个，代码量 4000 行以上。",
        ),
    ],
)

技能证书 = Section(
    icon=r".\Resources\icon_Project_History.png",
    title="技能证书",
    details=[
        Details(
            key="语言与工具",
            during_time="",
            tags="长期使用",
            description="Python / C++ / Java；Word、Excel、PowerPoint 熟练；"
                        "熟悉 AI 辅助开发流程。",
        ),
        Details(
            key="证书",
            during_time="",
            tags="已取得",
            description="CET-4、CET-6。",
        ),
    ],
)


# ============================================================================
# 3. 素材库 + 版本定义
# ============================================================================

def build_book() -> ResumeBook:
    book = ResumeBook(
        profile=profile,
        skills_awards=skills_awards,
        spacing=Spacing(),
        output_dir=OUT,
    )
    # 放进素材池（按 title 取用；同名会报错，避免"池里到底是哪一份"不可知）
    book.add_section(求学履历)
    book.add_section(项目经历)
    book.add_section(技能证书)

    # ---- 版本 1：通用调试版（全部节，留白默认）----
    book.add_version(ResumeVersion(
        name="通用调试",
        company="通用调试版",
        job="通用调试版",
        sections=["求学履历", "项目经历"],
        summary="简历通用调试版本，用于检查版式。",
    ))

    # ---- 版本 2：偏机械/制造岗（突出现有工程经历，留白略紧）----
    book.add_version(ResumeVersion(
        name="机械设计岗",
        company="某装备制造公司",
        job="机械设计工程师",
        sections=["求学履历", "项目经历", "技能证书"],
        spacing=Spacing(between_details=4.0, between_sections=6.0),
        summary="飞行器环境与生命保障工程在读，具备机械设计与增材制造实践经验。",
    ))

    # ---- 版本 3：偏软件/后端岗（项目经历放前面，留白收紧以便塞下）----
    book.add_version(ResumeVersion(
        name="后端开发岗",
        company="某互联网公司",
        job="后端开发工程师",
        sections=["项目经历", "求学履历", "技能证书"],   # 顺序即呈现顺序
        spacing=Spacing.compact(),
        summary="具备 Python / C++ 工程实践，独立完成 PDF 排版系统与 3D 渲染库。",
    ))

    return book


# ============================================================================
# 4. 入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("简历多版本批量生成")
    print("=" * 70)

    book = build_book()

    # 体检：所有版本引用的节是否都在素材池里（避免渲染到一半才失败）
    problems = book.validate()
    if problems:
        print("❌ 装配前体检未通过：")
        for p in problems:
            print(f"    - {p}")
        raise SystemExit(1)
    print("✅ 装配前体检通过")

    # 只渲染指定版本：py demo_multi_version.py --only 后端开发岗
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 < len(sys.argv):
            only = [sys.argv[i + 1]]

    print(f"\n【渲染】{'全部版本' if not only else only}")
    rendered = book.render_all(only=only)

    print("\n【结果】")
    book.summarize(rendered)

    # 演示：版本之间互不干扰（改一个装配结果，不影响素材池与其它版本）
    print("\n【隔离性】装配结果是素材的深拷贝")
    r = book.build("通用调试")
    before = len(book.find_section("项目经历").details)
    r.sections[1].details.pop()
    after = len(book.find_section("项目经历").details)
    print(f"    改装配结果：该版本项目 {len(r.sections[1].details)} 条，"
          f"素材池仍 {after} 条 -> {'✅ 未污染' if before == after else '❌ 被污染'}")

    print(f"\n产物目录：{OUT}")
