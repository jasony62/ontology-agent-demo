"""运行态配置：领域加载根、默认领域、watch 参数。

只描述「运行态从哪加载领域」，不涉及示例目录——示例仅通过
`ontologyctl domain install --from <path>` 显式安装后才生效。

优先级（高 → 低）：
    1. CLI 参数（--domains-root / --domain）
    2. 环境变量 ONTOLOGY_DOMAINS_ROOT / ONTOLOGY_DOMAIN
    3. config/domain.json        本地部署配置，不入库
    4. config/domain.example.json 随仓库分发的模板
    5. 内置默认（root=domains，default=None）

第 3、4 层按**字段**合并：domain.json 只需写出与模板不同的字段。
相对路径基准是**项目根**（不是 CWD），保证从任意目录启动行为一致。

用法：
    from config import load_config, ConfigError
    cfg = load_config(cli_root="domains", cli_domain="agent_task")
    cfg.root                  # 已 resolve 的绝对路径
    cfg.effective_default()   # 显式配置优先；否则 root 下唯一包自动选用
    cfg.domain_dir("x")       # 校验并拼出包目录（防路径逃逸）
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "ConfigError",
    "DomainConfig",
    "ENV_DOMAIN",
    "ENV_ROOT",
    "PROJECT_ROOT",
    "RESERVED_DOMAIN_NAMES",
    "check_domain_name",
    "load_config",
]

logger = logging.getLogger(__name__)
_fallback_notified = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIRNAME = "config"
LOCAL_FILENAME = "domain.json"
TEMPLATE_FILENAME = "domain.example.json"

ENV_ROOT = "ONTOLOGY_DOMAINS_ROOT"
ENV_DOMAIN = "ONTOLOGY_DOMAIN"

# 各配置层标识（写入 sources，便于 /api/health 与排查"到底读的哪个文件"）
LAYER_BUILTIN = "builtin"
LAYER_TEMPLATE = TEMPLATE_FILENAME
LAYER_LOCAL = LOCAL_FILENAME
LAYER_ENV = "env"
LAYER_CLI = "cli"

BUILTIN_DEFAULTS: dict[str, Any] = {
    "domains": {
        "root": "domains",
        "default": None,
        "watch": {"enabled": False, "interval": 2.0},
    },
    "servers": {"api_port": 8000, "mcp_port": 9000},
}


class ConfigError(RuntimeError):
    """配置文件损坏、字段非法或路径越界。"""


# 保留领域名：`current` 是 API 的单例路径段（/api/domains/current/...）。
# 若允许同名领域包，`/api/domains/current/...` 会同时像「当前领域」和
# 「名为 current 的领域」，同一 URL 指向两个东西。安装期与加载期都拒绝。
# current：API 用 /api/domains/current/... 表示当前运行态领域
# imported：框架内置「导入的本体」领域的内部标识（#119），不能由磁盘包顶替
RESERVED_DOMAIN_NAMES = frozenset({"current", "imported"})


def check_domain_name(name: Any) -> str:
    """校验领域标识：必须是合法 Python 标识符。

    为什么要求标识符：安装名会成为模块全名的一部分（`domains.<name>`），
    `my-domain` 这类名字在 sys.modules 里能凑合，但包内相对导入、
    `import domains.my-domain` 等路径都会失效，问题会延后到运行期才暴露。
    """
    if not isinstance(name, str):
        raise ConfigError(f"领域名必须是字符串，实际为 {type(name).__name__}")
    name = name.strip()
    if not name:
        raise ConfigError("领域名不能为空")
    if not name.isidentifier():
        raise ConfigError(
            f"非法领域名 {name!r}：必须是合法 Python 标识符"
            "（字母或下划线开头，只含字母、数字、下划线；不能有路径分隔符、横线、点）"
        )
    if name in RESERVED_DOMAIN_NAMES:
        raise ConfigError(
            f"领域名 {name!r} 为保留字：API 用 /api/domains/{name}/... 表示当前运行态领域，"
            "同名领域包会让路径产生歧义，请换一个名字"
        )
    return name


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"配置文件 {path.name} JSON 语法错误"
            f"（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"配置文件 {path.name} 顶层必须是对象，实际为 {type(data).__name__}"
        )
    return data


def _apply_layer(
    merged: dict, origins: dict[str, str], data: dict, layer: str
) -> tuple[dict, dict[str, str]]:
    """合并一层配置，并把该层实际写到的字段记进 origins。"""
    merged = _deep_merge(merged, data)
    domains = data.get("domains")
    if isinstance(domains, dict):
        for key in ("root", "default", "watch"):
            if key in domains:
                origins[key] = layer
    return merged, origins


def _load_layers(config_dir: Path) -> tuple[dict, dict[str, str]]:
    """按 内置默认 → 模板 → 本地 逐层合并，返回（配置, 各字段来源）。

    模板作基线、本地按字段覆盖：domain.json 只需写与模板不同的字段，
    模板后续新增字段能被本地自动继承。
    """
    merged = dict(BUILTIN_DEFAULTS)
    origins = {key: LAYER_BUILTIN for key in ("root", "default", "watch")}
    local = config_dir / LOCAL_FILENAME
    template = config_dir / TEMPLATE_FILENAME

    has_template = template.is_file()
    if has_template:
        merged, origins = _apply_layer(
            merged, origins, _read_json(template), LAYER_TEMPLATE
        )

    if local.is_file():
        return _apply_layer(merged, origins, _read_json(local), LAYER_LOCAL)

    # 回退模板/内置默认是开发期的正常状态，不是错误：用 info 且只提示一次。
    # 之前用 warning + 每次调用都打，导致 `ontologyctl --json` 的 stderr/stdout
    # 噪声和 CI 日志污染。
    global _fallback_notified
    if not _fallback_notified:
        if has_template:
            logger.info(
                "未找到 %s，回退模板 %s（部署时应复制为 %s 后本地化修改）",
                LOCAL_FILENAME,
                TEMPLATE_FILENAME,
                LOCAL_FILENAME,
            )
        else:
            logger.info(
                "未找到 %s 与 %s，使用内置默认（root=domains, default=None）",
                LOCAL_FILENAME,
                TEMPLATE_FILENAME,
            )
        _fallback_notified = True
    return merged, origins


def _resolve_root(raw: Any, project_root: Path) -> Path:
    if not isinstance(raw, (str, os.PathLike)) or not str(raw).strip():
        raise ConfigError(f"domains.root 必须是非空字符串，实际为 {raw!r}")
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _as_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{field_name} 必须是 true/false，实际为 {value!r}")


def _as_positive_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} 必须是数字，实际为 {value!r}") from exc
    if number <= 0:
        raise ConfigError(f"{field_name} 必须大于 0，实际为 {number}")
    return number


@dataclass(frozen=True)
class DomainConfig:
    """已解析、已校验的运行态配置。"""

    root: Path
    default: str | None
    watch_enabled: bool
    watch_interval: float
    sources: Mapping[str, str]
    servers: Mapping[str, Any]

    # ---------- 派生能力 ----------

    def domain_dir(self, name: str) -> Path:
        """拼出领域包目录，并确保仍在 root 之内（防 ../ 逃逸）。"""
        checked = check_domain_name(name)
        candidate = (self.root / checked).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ConfigError(
                f"领域目录越界：{candidate} 不在 {self.root} 之内"
            ) from exc
        return candidate

    def is_installed(self, name: str) -> bool:
        try:
            return (self.domain_dir(name) / "__init__.py").is_file()
        except ConfigError:
            return False

    def installed(self) -> list[str]:
        """root 下已安装的领域（目录名，按字母序）。"""
        if not self.root.is_dir():
            return []
        found = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            if entry.name in RESERVED_DOMAIN_NAMES:
                continue                  # 与 /api/domains/current/... 争义，忽略
            if (entry / "__init__.py").is_file():
                found.append(entry.name)
        return found

    def effective_default(self) -> str | None:
        """实际使用的默认领域。

        显式配置了 default 就用它（是否真的存在由加载器负责报错）；
        未配置时，root 下恰好一个已安装领域则自动选用，否则返回 None
        （零个 → 通用模式；多个 → 必须显式指定）。
        """
        if self.default:
            return self.default
        installed = self.installed()
        return installed[0] if len(installed) == 1 else None

    def server_port(self, key: str, fallback: int) -> int:
        try:
            return int(self.servers.get(key, fallback))
        except (TypeError, ValueError):
            logger.warning("servers.%s 不是整数（%r），回退 %s", key, self.servers.get(key), fallback)
            return fallback


def load_config(
    *,
    cli_root: str | None = None,
    cli_domain: str | None = None,
    config_dir: str | os.PathLike | None = None,
    project_root: str | os.PathLike | None = None,
    env: Mapping[str, str] | None = None,
) -> DomainConfig:
    """按优先级装配配置。所有输入可注入，便于测试完全隔离。"""
    root_base = Path(project_root).resolve() if project_root else PROJECT_ROOT
    cdir = Path(config_dir) if config_dir else root_base / CONFIG_DIRNAME
    env_map: Mapping[str, str] = os.environ if env is None else env

    data, sources = _load_layers(cdir)

    domains = data.get("domains")
    if not isinstance(domains, dict):
        raise ConfigError(f"domains 段必须是对象，实际为 {type(domains).__name__}")

    raw_root = domains.get("root", BUILTIN_DEFAULTS["domains"]["root"])
    raw_default = domains.get("default")
    if raw_default is not None:
        raw_default = check_domain_name(raw_default)

    watch = domains.get("watch") or {}
    if not isinstance(watch, dict):
        raise ConfigError(f"domains.watch 必须是对象，实际为 {type(watch).__name__}")
    watch_enabled = _as_bool(watch.get("enabled", False), "domains.watch.enabled")
    watch_interval = _as_positive_float(
        watch.get("interval", 2.0), "domains.watch.interval"
    )

    servers = data.get("servers") or {}
    if not isinstance(servers, dict):
        raise ConfigError(f"servers 段必须是对象，实际为 {type(servers).__name__}")

    # 环境变量层
    env_root = env_map.get(ENV_ROOT)
    if env_root:
        raw_root = env_root
        sources["root"] = LAYER_ENV
    env_domain = env_map.get(ENV_DOMAIN)
    if env_domain:
        raw_default = check_domain_name(env_domain)
        sources["default"] = LAYER_ENV

    # CLI 层（最高）
    if cli_root:
        raw_root = cli_root
        sources["root"] = LAYER_CLI
    if cli_domain:
        raw_default = check_domain_name(cli_domain)
        sources["default"] = LAYER_CLI

    return DomainConfig(
        root=_resolve_root(raw_root, root_base),
        default=raw_default,
        watch_enabled=watch_enabled,
        watch_interval=watch_interval,
        sources=sources,
        servers=servers,
    )
