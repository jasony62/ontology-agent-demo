"""前端静态资源挂载修复（issue #4）回归测试。

背景：api/main.py 原先在【模块导入时】一次性判断 frontend/app/dist/assets 是否存在，
API 先于前端构建启动时挂载被永久跳过 → 构建完成后 /assets/* 仍 404 → 工作台白屏。

修复：/assets 始终挂载；目录检查下沉为延迟生效——
1) 新版 Starlette 的 check_dir=False 仅跳过构造期检查，lifespan 启动仍会 os.stat
   目录并抛 RuntimeError（服务启动即崩），故用 LazyStaticFiles 覆盖 check_config；
2) index() 在 dist 未构建时返回明确提示，不再静默回退旧单页。
"""

import api.main as m
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount


def test_assets_mount_always_registered_with_lazy_static_files():
    """/assets 挂载必须始终注册且使用 LazyStaticFiles（修复前：dist 不存在时整个挂载被跳过）。"""
    mounts = [r for r in m.app.routes if isinstance(r, Mount) and r.path == "/assets"]
    assert len(mounts) == 1
    static = mounts[0].app
    assert isinstance(static, m.LazyStaticFiles)
    assert static.directory == str(m.APP_DIST / "assets")


def test_lazy_static_files_serves_after_dir_appears(tmp_path):
    """核心语义：目录先不存在也能完成挂载与启动；目录出现后请求即 200，无需重启。"""
    assets = tmp_path / "assets"
    app = FastAPI()
    app.mount("/assets", m.LazyStaticFiles(directory=str(assets), check_dir=False), name="assets")
    client = TestClient(app)

    # 目录尚不存在：请求 404（而不是启动期抛 RuntimeError 崩溃）
    resp = client.get("/assets/index.js")
    assert resp.status_code == 404

    # 目录随后出现（模拟 npm run build 完成）：同一进程内直接可服务
    (assets / "index.js").parent.mkdir(parents=True)
    (assets / "index.js").write_text("console.log('workbench')", encoding="utf-8")
    resp = client.get("/assets/index.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_index_returns_explicit_hint_when_dist_missing(tmp_path, monkeypatch):
    """dist 未构建时 index() 返回明确提示（不再静默回退旧单页），避免「像 demo 页」误解。"""
    monkeypatch.setattr(m, "APP_DIST", tmp_path)
    resp = m.index()
    assert resp["message"].startswith("工作台前端未构建")
    assert "npm run build" in resp["message"]


def test_index_serves_dist_html_when_built(tmp_path, monkeypatch):
    """dist 已构建时 index() 返回工作台 HTML（200）。"""
    (tmp_path / "index.html").write_text("<title>本体图谱工作台</title>", encoding="utf-8")
    monkeypatch.setattr(m, "APP_DIST", tmp_path)
    client = TestClient(m.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<title>本体图谱工作台</title>" in resp.text
