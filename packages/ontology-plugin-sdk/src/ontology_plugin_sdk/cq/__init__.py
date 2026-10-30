"""CQ（Competency Question）通用工位：出题、质检、TBox 草稿引导与校验。

本包是 P1-3 从 agent_task 领域包上移的部分——它只用到 rdflib/owlrl 与引擎原语，
唯一带领域色彩的是 prompts（术语、措辞、公理提示），改为注入。

P4 又从宿主 `reasoner/cq/` 搬到了这里。那次搬迁的理由不是"再整理一下"：它曾是
领域包唯一允许 import 的宿主模块，也就是"领域可脱离主仓库"这条路上的最后一道坎。
搬完后领域包对这部分的依赖与对其他能力一样，全部走 `ontology_plugin_sdk`。

用法（领域包）：
    from ontology_plugin_sdk.cq import gen, tbox, load_prompts
    P = load_prompts(os.path.join(_DIR, "cq_prompts.json"))
    gen.guide_cq_generation(P, engine=engine)
    gen.validate_cqs(cqs, P, bank_path=os.path.join(_DIR, "cq_tests.json"))
    tbox.validate_tbox_draft(ttl, cqs, P)

不提供 prompts 时用框架中立默认模板（同目录 default_prompts.json），
新领域零配置即可跑通 CQ 流程。
"""

from . import gen, tbox
from .prompts import DEFAULT_PROMPTS_PATH, load_prompts

__all__ = ["gen", "tbox", "load_prompts", "DEFAULT_PROMPTS_PATH"]
