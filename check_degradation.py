"""
资源降级验收（SKILLS.md G 节 · D 组）—— 缺资源时必须"要么继续、要么明确报错"。

验三条：
    D1  资源齐全            -> 两个入口能跑通
    D2  缺图片（字体在位）  -> 仍能跑通，图标位置留空（静默降级）
    D3  缺字体（图片挪开）  -> **明确报错**，信息可读；不得是 fpdf 底层异常裸奔

安全性
    · 资源一律用 `os.replace` 挪到同盘的临时目录，**不删除**；
    · 全部包在 try/finally 里，任何异常（含 Ctrl-C）都会把资源挪回原位；
    · 结尾校验文件数与开始一致，不一致就报警。

用法
    py check_degradation.py            # 全部三条
    py check_degradation.py --quick    # 只跑 D3（缺字体）
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, "Resources")
ENTRIES = ["ResumeTemplate.py", "ResumeCore.py"]
TIMEOUT = 600

FONTS = (".ttf",)
IMAGES = (".png", ".jpg", ".jpeg")


def snapshot():
    """当前 Resources 下的资源文件（按后缀分类）"""
    out = {"fonts": [], "images": []}
    for f in sorted(os.listdir(RES)):
        low = f.lower()
        if low.endswith(FONTS):
            out["fonts"].append(f)
        elif low.endswith(IMAGES):
            out["images"].append(f)
    return out


def run_entry(entry, smoke=True):
    """跑一个入口，返回 (返回码, 输出文本)"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = ROOT
    if smoke:
        env["DSH_RESUME_SMOKE"] = "1"
    p = subprocess.run([sys.executable, entry], cwd=ROOT, env=env,
                       capture_output=True, timeout=TIMEOUT)
    out = (p.stdout or b"").decode("utf-8", "replace") + \
          (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


class ResourceMover:
    """把指定后缀的资源挪到**同盘的**暂存目录，退出时必定挪回

    ⚠️ 暂存目录必须与 `Resources/` 同盘：`os.replace` 跨盘会抛
    `OSError: [WinError 17] 系统无法将文件移到不同的磁盘驱动器`。
    放在项目内还有个好处：`os.replace` 是原子改名，不复制 18MB 的字体。
    """

    def __init__(self, suffixes, tag):
        self.suffixes = suffixes
        self.tag = tag
        self.stash = os.path.join(ROOT, f"_degrade_{tag}_stash")
        self.moved = []

    def __enter__(self):
        os.makedirs(self.stash, exist_ok=True)
        try:
            for f in sorted(os.listdir(RES)):
                if f.lower().endswith(self.suffixes):
                    os.replace(os.path.join(RES, f), os.path.join(self.stash, f))
                    self.moved.append(f)
        except BaseException:
            # 中途失败也要把已挪走的放回去，绝不留下残缺的 Resources
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        for f in self.moved:
            src = os.path.join(self.stash, f)
            if os.path.exists(src):
                os.replace(src, os.path.join(RES, f))
        self.moved = []
        if os.path.isdir(self.stash) and not os.listdir(self.stash):
            os.rmdir(self.stash)
        return False


def main():
    quick = "--quick" in sys.argv
    base = snapshot()
    print("=" * 66)
    print("资源降级验收（G 节 D 组）")
    print(f"  Resources 现有：字体 {len(base['fonts'])} 个 / 图片 {len(base['images'])} 个")
    print("=" * 66)

    fails = []

    if not quick:
        print("\n【D1】资源齐全 —— 两个入口应跑通")
        for e in ENTRIES:
            rc, out = run_entry(e)
            ok = rc == 0
            print(f"  {'✅' if ok else '❌'} {e:<20} exit={rc}")
            if not ok:
                fails.append(("D1", e, rc, out))

        print("\n【D2】缺图片（字体在位）—— 应继续运行、图标留空")
        with ResourceMover(IMAGES, "images"):
            for e in ENTRIES:
                rc, out = run_entry(e)
                ok = rc == 0
                print(f"  {'✅' if ok else '❌'} {e:<20} exit={rc}")
                if not ok:
                    fails.append(("D2", e, rc, out))

    print("\n【D3】缺字体 —— 应**明确报错**，且信息可读")
    with ResourceMover(FONTS, "fonts"):
        for e in ENTRIES:
            rc, out = run_entry(e)
            # 期望：非 0，且输出里有可读的中文提示，且不是裸的 fpdf 异常
            readable = ("测量失败" in out) or ("字体" in out and "确认" in out)
            bare = ("FPDFUnicodeEncodingException" in out
                    and "测量失败" not in out)
            ok = rc != 0 and readable and not bare
            print(f"  {'✅' if ok else '❌'} {e:<20} exit={rc}  "
                  f"可读提示={'有' if readable else '无'}  "
                  f"底层异常裸奔={'是' if bare else '否'}")
            if not ok:
                fails.append(("D3", e, rc, out))

    # ---- 结束校验：资源必须回到原位 ----
    print("\n" + "=" * 66)
    after = snapshot()
    same = (sorted(after["fonts"]) == sorted(base["fonts"]) and
            sorted(after["images"]) == sorted(base["images"]))
    print(f"资源复位校验：{'✅ 与开始时一致' if same else '❌ 不一致，请检查 Resources/！'}")
    if not same:
        print(f"  开始: 字体 {len(base['fonts'])} / 图片 {len(base['images'])}")
        print(f"  现在: 字体 {len(after['fonts'])} / 图片 {len(after['images'])}")
        fails.append(("复位", "-", -1, ""))

    print("=" * 66)
    if fails:
        print(f"\n❌ 有 {len(fails)} 项未通过：")
        for tag, entry, rc, out in fails:
            print(f"\n--- {tag} / {entry} (exit={rc}) ---")
            for line in out.strip().splitlines()[-12:]:
                print(f"    {line}")
        return 1
    print("\n✅ D 组全部通过：缺图片→继续，缺字体→明确报错")
    return 0


if __name__ == "__main__":
    sys.exit(main())
