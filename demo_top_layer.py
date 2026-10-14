"""新顶层的使用示例 —— 生成一份样例简历，演示两种使用方式。

    py demo_top_layer.py

产物：output_demo/{姓名}_{职位}_{公司}.pdf
"""
import os

from ResumeCore import (
    Details,
    Padding,
    Profiles,
    Resume,
    Section,
    SkillsAwards,
    Theme,
    render,
    render_many,
)
from ResumeTemplate import Spacing

OUT = "./output_demo"


def build_resume() -> Resume:
    """方式一：在源文件里直接构造数据容器"""
    me = Profiles(
        name="利姆露",
        telephone="138-0000-0000",
        email="limuru@example.com",
        locate="中央都市",
        social_media_qq="1145141919",
        title="后端开发工程师",
        website="github.com/limuru",
        # 个人评价 —— 渲染在左栏最后，视觉模板与技能/证书/荣誉相同
        evaluation="五年全栈开发经验，习惯把复杂问题拆成可验证的小步。",
    )

    edu = Section(title="教育背景",
                  icon=r".\Resources\icon_Education_History.png")
    edu.add_detail(Details(
        key="日本农业苞谷大学",
        during_time="2020.09 - 2024.06",
        tags="金坷垃制造与苞米发酵工程 | 本科",
        description="主修课程：数据结构与算法、操作系统、计算机网络、数据库原理、软件工程。\n"
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

    return Resume(
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


if __name__ == "__main__":
    print("=" * 60)
    print("新顶层示例")
    print("=" * 60)

    resume = build_resume()

    # ---- 默认版式 ----
    p = render(resume, output_dir=OUT)
    print(f"\n✅ 默认版式     -> {p}  ({os.path.getsize(p)} 字节)")

    # ---- 同一容器换留白松紧（数据不变）----
    for label, sp in (("紧凑 compact", Spacing.compact()),
                      ("宽松 loose", Spacing.loose())):
        sub = os.path.join(OUT, label.split()[0])
        p = render(resume, output_dir=sub, spacing=sp)
        print(f"✅ {label:<14} -> {p}  ({os.path.getsize(p)} 字节)")

    # ---- 关闭描述体内边距（调试对齐用）----
    # ⚠️ body_inner_padding=None 表示"用中层默认"（= Padding.all(2)），
    #    要真正关闭必须显式传 Padding.all(0)
    p = render(resume, output_dir=os.path.join(OUT, "无内边距"),
               theme=Theme(body_inner_padding=Padding.all(0)))
    print(f"✅ 关闭内边距   -> {p}  ({os.path.getsize(p)} 字节)")

    # ---- 批量：多份简历共用同一套留白 ----
    many = [build_resume() for _ in range(3)]
    paths = render_many(many, output_dir=os.path.join(OUT, "批量"),
                        spacing=Spacing())
    print(f"✅ 批量渲染 {len(paths)} 份 -> {os.path.join(OUT, '批量')}")
    print(f"\n产物目录：{os.path.abspath(OUT)}")
