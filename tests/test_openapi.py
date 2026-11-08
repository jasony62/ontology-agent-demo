"""OpenAPI 文档契约：/openapi.json 必须能作为「服务能力」面板的数据源。

工作台不再手写端点表，而是直接渲染这份规范。这里锁住最容易在新增路由
时被忘掉的约束：每个操作都有分组 tag 和中文 summary；tag 都在
openapi_tags 里声明过；规范版本是 OpenAPI 3.x；参数与请求体字段都有
说明；成功响应有业务说明与非空 schema；业务错误码与两个非 JSON 端点的
media type 与实际实现一致。
"""

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402

client = TestClient(app)

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def test_openapi_spec_is_openapi_3():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"]
    assert len(spec["paths"]) >= 29


# 领域模式专属端点：统一挂在 /api/domains/current/ 下（表 A）。
# 旧路径不做任何兼容——保留这份清单是为了在 OpenAPI 里断言它们真的消失了。
MOVED_PATHS = {
    "/api/ontology",
    "/api/ontology/graph-groups",
    "/api/capabilities/query",
    "/api/capabilities/apply",
    "/api/entities/schema",
    "/api/entities",
    "/api/explain",
    "/api/consistency",
    "/api/ontology/individual/{name}",
    "/api/ontology/revoke",
    "/api/ontology/import",
}


def test_domain_endpoints_are_namespaced_under_current():
    """领域端点统一前缀：11 个搬进 /api/domains/current/，旧路径一个不留。

    路径总数不变（11 搬 + 19 留 = 30），变的只是 key。旧路径必须从
    `spec["paths"]` 里彻底消失——不做别名、deprecated 或重定向。
    """
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    prefixed = {
        path for path in paths if path.startswith("/api/domains/current/")
    }
    assert len(prefixed) == len(MOVED_PATHS) == 11
    assert not MOVED_PATHS & set(paths), (
        f"旧路径仍在 OpenAPI 中：{sorted(MOVED_PATHS & set(paths))}"
    )
    assert len(paths) == 30


def test_every_operation_is_tagged_and_summarised():
    spec = client.get("/openapi.json").json()
    declared = {tag["name"] for tag in spec.get("tags", [])}
    assert declared, "openapi_tags 未声明，前端无法按使用场景分组"

    missing = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in _HTTP_METHODS:
                continue
            if not op.get("tags") or not op.get("summary"):
                missing.append(f"{method.upper()} {path}")
            for tag in op.get("tags", []):
                assert tag in declared, f"{method.upper()} {path} 使用了未声明的 tag: {tag}"

    assert missing == [], f"以下端点缺少 tag/summary：{missing}"


def test_request_parameters_and_fields_have_descriptions():
    """参数说明必须来自 OpenAPI 本身，而不是前端另写一份。

    `/api-docs` 的「请求字段说明」直接读 `schema.properties[*].description`，
    这里守住：所有路由参数都有 description，所有自定义请求模型的字段都有
    description（FastAPI 自带的 ValidationError 除外）。
    """
    spec = client.get("/openapi.json").json()

    missing_params = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in _HTTP_METHODS:
                continue
            for param in op.get("parameters", []):
                if not param.get("description"):
                    missing_params.append(f"{method.upper()} {path} → {param.get('in')}:{param.get('name')}")
    assert missing_params == [], f"以下参数缺少说明：{missing_params}"

    skipped = {"HTTPValidationError", "ValidationError"}
    missing_fields = []
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if name in skipped:
            continue
        for field, prop in schema.get("properties", {}).items():
            if not prop.get("description"):
                missing_fields.append(f"{name}.{field}")
    assert missing_fields == [], f"以下请求字段缺少说明：{missing_fields}"


def test_request_body_description_lists_fields():
    """请求体描述要能直接看到字段说明，而不是只藏在 Schema 标签页。

    Swagger UI 的请求体默认渲染「Example Value」，字段说明只在「Schema」
    标签页；`_describe_request_bodies` 把同一份字段说明提升到
    `requestBody.description`，这里守住它真的生成了。
    """
    spec = client.get("/openapi.json").json()

    body = spec["paths"]["/api/domains/current/capabilities/query"]["post"]["requestBody"]
    desc = body.get("description", "")
    for field in ("kind", "task", "agent", "params"):
        assert f"`{field}`" in desc, f"请求体说明缺少字段 {field}"
    assert "查询" in desc

    apply_body = spec["paths"]["/api/domains/current/capabilities/apply"]["post"]["requestBody"]
    apply_desc = apply_body.get("description", "")
    for field in ("kind", "task", "agent", "persist", "params"):
        assert f"`{field}`" in apply_desc, f"请求体说明缺少字段 {field}"
    assert "persist" in apply_desc

    # 每个有字段说明的 JSON 请求体都应带描述，否则又回到「打开端点看不到说明」
    missing = []
    schemas = spec.get("components", {}).get("schemas", {})
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in _HTTP_METHODS or not op.get("requestBody"):
                continue
            body = op["requestBody"]
            for media in body.get("content", {}).values():
                schema = media.get("schema", {})
                if "$ref" in schema:
                    schema = schemas.get(schema["$ref"].rsplit("/", 1)[-1], {})
                described = [
                    name for name, prop in schema.get("properties", {}).items()
                    if prop.get("description")
                ]
                if not described:
                    continue
                text = body.get("description", "")
                for name in described:
                    if f"`{name}`" not in text:
                        missing.append(f"{method.upper()} {path} → {name}")
    assert missing == [], f"以下请求体字段没有出现在请求体说明里：{missing}"


def test_success_responses_are_described():
    """成功响应必须有面向调用方的中文说明，不能停在 FastAPI 默认文案。

    参数侧已经有三条测试守着；返回侧此前是 29/29 的
    `Successful Response` + 空 schema，工作台因此根本没有「响应」区可渲染。
    """
    spec = client.get("/openapi.json").json()
    bad = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in _HTTP_METHODS:
                continue
            r200 = op["responses"]["200"]
            if r200.get("description") == "Successful Response":
                bad.append(f"{method.upper()} {path}: 默认文案")
            for media in r200.get("content", {}).values():
                if not media.get("schema"):
                    bad.append(f"{method.upper()} {path}: 空 schema")
    assert bad == [], f"成功响应缺说明：{bad}"


def test_business_error_codes_are_declared():
    """业务错误码要写进规范，而不是只存在于源码的 HTTPException 里。"""
    spec = client.get("/openapi.json").json()
    declared = {
        code
        for item in spec["paths"].values()
        for op in item.values()
        if isinstance(op, dict)
        for code in op.get("responses", {})
    }
    assert {"400", "404", "408", "501"} <= declared
    assert "ErrorResponse" in spec["components"]["schemas"]


def test_non_json_endpoints_declare_real_media_types():
    """两个文件/文本端点必须声明真实 media type，不能写成 application/json。

    按规范生成客户端的调用方会拿 JSON 解析器去读 Turtle / RDF/XML，
    这比「缺说明」更严重。
    """
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/api/ontology/export"]["get"]["responses"]["200"]["content"]
    assert "text/turtle" in content and "application/json" not in content
    dl = spec["paths"]["/api/ontology/download"]["get"]["responses"]["200"]["content"]
    assert "application/rdf+xml" in dl and "application/json" not in dl


def test_every_operation_has_description():
    """端点级说明：展开任一端点都应能看到「这个接口是做什么的」。"""
    spec = client.get("/openapi.json").json()
    missing = [
        f"{method.upper()} {path}"
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in _HTTP_METHODS and not op.get("description")
    ]
    assert missing == [], f"缺端点说明：{missing}"


def test_docs_responses_are_not_cached():
    """文档响应不缓存：补了说明后刷新就能看到，而不是浏览器给旧规范。"""
    for path in ("/openapi.json", "/docs"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-store", path


def test_swagger_ui_shows_schema_by_default():
    """/docs 的 Swagger UI 配置：默认渲染 Schema，并显示请求耗时。

    这不是唯一保障（requestBody.description 才是主路径），但它能减少
    「字段说明在另一个标签页」的困惑。
    """
    r = client.get("/docs")
    assert r.status_code == 200
    assert '"defaultModelRendering": "model"' in r.text
    assert "displayRequestDuration" in r.text


def test_swagger_ui_is_served():
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()


def test_frontend_index_is_revalidated():
    """index.html 引用带哈希的 /assets/*，重新构建后必须让浏览器重新校验。

    否则浏览器拿旧 index.html 去请求已删除的旧哈希资源 → 404 → 整页空白
    （表现为「工作台进不去」）。未构建前端时 `/` 返回提示 JSON，跳过。
    """
    r = client.get("/")
    if r.headers.get("content-type", "").startswith("application/json"):
        return
    assert r.headers.get("cache-control") == "no-cache"


def test_redoc_is_disabled():
    """只保留 /docs 与 /api-docs 两个文档入口。

    /redoc 依赖 CDN 且对 OpenAPI 3.1 支持不完整；若哪天被重新开启，
    这里红灯，而不是等离线部署时才发现页面是空的。
    """
    r = client.get("/redoc")
    assert r.status_code == 404


def test_api_docs_page_is_standalone():
    """独立文档页复用 SPA 入口：直接打开 /api-docs 不应 404。

    CI 可能没有构建前端，此时与 `/` 一样返回构建提示 JSON；本地构建后
    则是同一份 index.html，由前端按 pathname 渲染 ApiDocsPage。
    """
    r = client.get("/api-docs")
    assert r.status_code == 200
    home = client.get("/")
    assert r.headers.get("content-type") == home.headers.get("content-type")
