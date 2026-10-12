"""
==============================================================================
PDF 逐字节回归比对工具 (verify_pdfs.py)
==============================================================================
用途：
    对比"改动前"与"改动后"生成的 PDF，在**剥离易变字段**后做逐字节比较。
    生成的 PDF 内含 CreationDate / ModDate / ID / Producer 等每次都不同的字段，
    直接字节比对永远失败，因此必须先规范化。

用法：
    # 1. 改动前，把产物另存到工作区外的临时目录
    py LayoutEngine.py
    py ResumeTemplate.py
    py ResumeCore.py
    md %TEMP%\\baseline
    copy test_layout_engine_cached.pdf %TEMP%\\baseline\\engine.pdf
    copy resume_template_v2_test.pdf %TEMP%\\baseline\\template.pdf
    copy output\\*.pdf %TEMP%\\baseline\\resume.pdf

    # 2. 改动后，对比
    py verify_pdfs.py --baseline %TEMP%\\baseline

退出码：
    0 = 全部一致
    1 = 存在差异（或文件缺失）

说明：
    本工具只读文件，不生成也不修改任何内容。它不替代"逐条解释差异"的验收方式 ——
    从批次 4 起，布局行为会**有意**变化，此时应把差异逐条对应到预期修复项，
    而不是要求完全一致。
==============================================================================
"""

import argparse
import hashlib
import os
import re
import sys

# 易变字段的规范化规则：(正则, 替换)
VOLATILE_FIELDS = [
    (rb"/CreationDate\s*\(D:[^)]*\)", rb"/CreationDate(D:X)"),
    (rb"/ModDate\s*\(D:[^)]*\)", rb"/ModDate(D:X)"),
    (rb"/ID\s*\[<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\]", rb"/ID[<X><X>]"),
    (rb"/Producer\s*\([^)]*\)", rb"/Producer(X)"),
]


def normalize(path: str) -> bytes:
    """读入 PDF 并剥离易变字段"""
    with open(path, "rb") as f:
        data = f.read()
    for pat, rep in VOLATILE_FIELDS:
        data = re.sub(pat, rep, data)
    return data


def digest(path: str) -> str:
    return hashlib.md5(normalize(path)).hexdigest()


# 默认配对：基线文件名 -> 当前产物路径
DEFAULT_PAIRS = {
    "engine.pdf": "test_layout_engine_cached.pdf",
    "template.pdf": "resume_template_v2_test.pdf",
    "resume.pdf": os.path.join("output", "利姆露_后端开发工程师_腾讯科技.pdf"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 逐字节回归比对")
    ap.add_argument("--baseline", required=True, help="基线 PDF 所在目录")
    ap.add_argument("--pairs", nargs="*", default=None,
                    help="自定义配对，格式 基线文件名=当前路径")
    args = ap.parse_args()

    pairs = dict(DEFAULT_PAIRS)
    if args.pairs:
        pairs = {}
        for item in args.pairs:
            if "=" not in item:
                print(f"参数格式错误（应形如 ref.pdf=cur.pdf）: {item}")
                return 1
            k, v = item.split("=", 1)
            pairs[k] = v

    print("=" * 74)
    print("PDF 逐字节回归比对（已剥离 CreationDate / ModDate / ID / Producer）")
    print("=" * 74)
    print(f"基线目录: {os.path.abspath(args.baseline)}")
    print()

    all_same = True
    missing = []
    for ref_name, cur_path in pairs.items():
        ref_path = os.path.join(args.baseline, ref_name)
        label = os.path.splitext(ref_name)[0]

        if not os.path.exists(ref_path):
            print(f"  {label:<10} 基线缺失: {ref_path}")
            missing.append(ref_path)
            all_same = False
            continue
        if not os.path.exists(cur_path):
            print(f"  {label:<10} 产物缺失: {cur_path}")
            missing.append(cur_path)
            all_same = False
            continue

        hr, hc = digest(ref_path), digest(cur_path)
        sr, sc = os.path.getsize(ref_path), os.path.getsize(cur_path)
        verdict = "IDENTICAL" if hr == hc else "DIFFERENT"
        mark = "OK " if hr == hc else "!! "
        print(f"  {mark}{label:<10} ref={sr:>7} new={sc:>7}  {verdict}")
        if hr != hc:
            all_same = False
            print(f"      ref hash: {hr}")
            print(f"      new hash: {hc}")

    print()
    if missing:
        print(f"失败：缺少 {len(missing)} 个文件")
        return 1
    if all_same:
        print("全部一致。若本批次是等价重构，这即是预期结果。")
        print("若本批次有意改变行为，请把差异逐条对应到预期修复项。")
        return 0
    print("存在差异 —— 请逐条解释，确认没有预期之外的连带变化。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
