"""skills/ 目录防漂移校验（方案 018）：frontmatter / 死链 / 子命令级命令比对 / 行数上限。

技能内容引用的 make 目标与 CLI 子命令以源码为唯一事实源，此处静态比对，
抓「脚本还在但命令改名了」这类存在性断言抓不到的漂移。零执行开销、确定性。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))
ENTRY = SKILLS_DIR / "README.md"


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^(name|description):\s*(.+)$", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def _extract_commands(text: str) -> list[tuple[str, str]]:
    """从 ```bash 围栏里抽取 (工具, 令牌) 对：make 目标 / ontologyctl·query.py 子命令。"""
    pairs = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            m = re.search(
                r"(?:^|/|\s)(ontologyctl\.py)\s+([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?", line
            )
            if m:
                pairs.append((m.group(1), m.group(2)))
                if m.group(2) == "domain" and m.group(3):  # domain 叶子动作
                    pairs.append((m.group(1), m.group(3)))
                continue
            m = re.search(r"(?:^|\s)query\.py\s+([a-z][a-z-]*)", line)
            if m:
                pairs.append(("query.py", m.group(1)))
                continue
            m = re.search(r"(?:^|\s)make\s+([a-z][a-z-]*)", line)
            if m:
                pairs.append(("make", m.group(1)))
    return pairs


def _known_commands() -> dict[str, set]:
    known: dict[str, set] = {"make": set(), "ontologyctl.py": set(), "query.py": set()}
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    for m in re.finditer(r"^([a-zA-Z][a-zA-Z_-]*):(?!=)", mk, re.M):
        known["make"].add(m.group(1))
    for script in ("scripts/ontologyctl.py", "scripts/query.py"):
        src = (ROOT / script).read_text(encoding="utf-8")
        subs = set(re.findall(r'add_parser\(\s*"([a-z][a-z-]+)"', src))
        subs.update(re.findall(r'"([a-z][a-z-]+)":\s*\(cmd_', src))  # ontologyctl SUBCOMMANDS
        subs.update(
            w
            for m in re.finditer(r"for name in \(([^)]*)\)", src)  # query.py 元组注册
            for w in re.findall(r'"([a-z][a-z-]+)"', m.group(1))
        )
        known[Path(script).name] = subs
    return known


def test_frontmatter_and_size_limits():
    assert SKILL_FILES, "skills/*/SKILL.md 一个都没有"
    for path in SKILL_FILES:
        text = path.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        assert fm.get("name") == path.parent.name, f"{path}: name 必须等于目录名"
        assert len(fm.get("description", "")) >= 20, f"{path}: description 不能为空或过短"
        assert len(text.splitlines()) <= 300, f"{path}: 超过 300 行上限（防膨胀）"
    assert ENTRY.exists(), "skills/README.md 入口缺失"
    assert len(ENTRY.read_text(encoding="utf-8").splitlines()) <= 150, "入口索引超过 150 行上限"


def test_relative_links_resolve():
    targets = SKILL_FILES + [ENTRY]
    assert targets
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\]\((?!https?://|#|mailto:)([^)#\s]+)", text):
            rel = m.group(1)
            candidates = [ROOT / rel, path.parent / rel]
            assert any(c.exists() for c in candidates), f"{path}: 死链 {rel}"


def test_inline_commands_exist():
    known = _known_commands()
    assert known["make"], "Makefile 目标解析失败（测试自身问题）"
    checked = 0
    for path in SKILL_FILES + [ENTRY]:
        for tool, token in _extract_commands(path.read_text(encoding="utf-8")):
            assert token in known[tool], (
                f"{path}: 命令漂移 —— {tool} {token} 不在源码注册表中"
            )
            checked += 1
    assert checked >= 10, f"命令抽取量异常（{checked} < 10），测试覆盖不足"
