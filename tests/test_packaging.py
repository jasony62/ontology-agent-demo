"""镜像构建上下文的打包约束：框架自带的代码不能落在 .dockerignore 的白名单外。

这条断言来自一次真实故障：`api/main.py` 开始直接 import `domains.imported`
后，CI 的 docker job 起不来——`.dockerignore` 以 `domains/*` 排除了运行态
领域包，只把框架文件逐个放回，而新增的 `domains/imported.py` 没有进白名单。
本地与 pytest 都读得到仓库文件，只有镜像里缺，健康检查表现为
「connection refused」。这里把约束写成断言，下次再加 `domains/` 下的框架
模块时不必靠人记得改白名单。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dockerignore_rules() -> tuple[list[str], set[str]]:
    """返回（排除规则，白名单）；只处理本仓库实际使用的 `domains/*` 形态。"""
    lines = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ]
    lines = [line for line in lines if line and not line.startswith("#")]
    keep = {line[1:] for line in lines if line.startswith("!")}
    excludes = [line for line in lines if not line.startswith("!")]
    return excludes, keep


def test_dockerignore_keeps_every_framework_domain_module():
    """`domains/<module>.py` 都是框架代码，镜像里必须存在。"""
    excludes, keep = _dockerignore_rules()
    if "domains/*" not in excludes:
        return  # 规则变了（例如整体放行），本断言的前提不成立
    missing = [
        module.name
        for module in sorted((ROOT / "domains").glob("*.py"))
        if f"domains/{module.name}" not in keep
    ]
    assert not missing, (
        ".dockerignore 的 domains/* 排除规则没有放回这些框架模块："
        f"{missing}（镜像里 import api.main 或切换导入领域会失败）"
    )


def test_dockerignore_still_excludes_runtime_state():
    """白名单只放框架文件：运行态领域包、本地上传与配置不能进镜像。"""
    excludes, keep = _dockerignore_rules()
    for pattern in ("domains/*", "config/domain.json", "data/", "backups/"):
        assert pattern in excludes
    # 白名单里不应出现运行态目录（领域包由 domain ensure 在镜像内重建）
    assert not any(item.startswith("domains/") and item.endswith("/") for item in keep)
