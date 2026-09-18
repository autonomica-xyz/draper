#!/usr/bin/env python3
"""End-to-end MCP server verification via stdio (line-delimited JSON)."""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

proc = subprocess.Popen(
    [sys.executable, "-m", "mcp_server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=REPO_ROOT,
)

_req_id = 0
passed = 0
failed = 0


def send(msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def recv():
    line = proc.stdout.readline().decode().strip()
    if not line:
        raise RuntimeError("MCP server closed stdout")
    return json.loads(line)


def call_tool(name, args):
    global _req_id
    _req_id += 1
    send({"jsonrpc": "2.0", "id": _req_id, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    resp = recv()
    text = resp["result"]["content"][0]["text"]
    return json.loads(text)


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label} — {detail}")


try:
    # 1. Initialize
    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    })
    resp = recv()
    info = resp["result"]["serverInfo"]
    check("Initialize handshake", info["name"] == "Draper Marketing Pipeline")
    check("Protocol version", resp["result"]["protocolVersion"] == "2024-11-05")
    check("Tools capability declared", "tools" in resp["result"]["capabilities"])

    # 2. Initialized notification
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # 3. List tools
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    resp = recv()
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    check("39 tools registered", len(tools) == 39, f"got {len(tools)}")

    required = [
        "list_projects", "get_current_project", "create_project",
        "generate_content", "generate_long_form",
        "list_content", "get_content", "approve_content", "decline_content", "request_fix",
        "add_source_material", "list_source_materials", "enrich_source_material",
        "generate_ideas", "add_content_idea", "list_content_ideas",
        "approve_and_generate_from_idea", "evaluate_idea",
        "run_mining", "publish_content", "get_analytics",
        "get_content_plan", "update_content_plan", "get_brand_voice",
        "get_system_status", "list_jobs",
    ]
    for t in required:
        check(f"Tool '{t}' present", t in tool_names)

    # 4. get_system_status
    result = call_tool("get_system_status", {})
    check("get_system_status returns ok", result["status"] == "ok")
    check("get_system_status has project_count", isinstance(result["project_count"], int))

    # 5. list_projects
    projects = call_tool("list_projects", {})
    check("list_projects returns dict with items", "items" in projects)
    check("list_projects has projects", projects["count"] >= 1)
    if projects["items"]:
        check("Project has project_id", "project_id" in projects["items"][0])

    # 6. list_content
    content = call_tool("list_content", {"status": "declined", "limit": 3})
    check("list_content returns items", content["count"] > 0, f"count={content['count']}")
    if content["items"]:
        check("Content item has review_id", "review_id" in content["items"][0])

    # 7. get_analytics
    analytics = call_tool("get_analytics", {})
    check("get_analytics has total_content", "total_content" in analytics)
    check("get_analytics has by_status", "by_status" in analytics)

    # 8. get_content_plan
    plan = call_tool("get_content_plan", {})
    check("get_content_plan returns dict", "content_plan" in plan)

    # 9. list_source_materials
    mats = call_tool("list_source_materials", {"limit": 5})
    check("list_source_materials returns items", mats["count"] >= 0)

    # 10. list_content_ideas
    ideas = call_tool("list_content_ideas", {"limit": 5})
    check("list_content_ideas returns items", ideas["count"] >= 0)

    # 11. get_brand_voice
    voice = call_tool("get_brand_voice", {})
    check("get_brand_voice returns dict", "brand_voice" in voice)

    # 12. list_jobs
    jobs = call_tool("list_jobs", {})
    check("list_jobs returns items", "items" in jobs)

    # 13. get_project_settings
    settings = call_tool("get_project_settings", {})
    check("get_project_settings returns dict", "settings" in settings)

    # 14. Error case: get_content with invalid ID
    send({"jsonrpc": "2.0", "id": 100, "method": "tools/call",
          "params": {"name": "get_content", "arguments": {"review_id": "nonexistent"}}})
    resp = recv()
    check("Error returns isError", resp["result"].get("isError") is True,
          f"isError={resp['result'].get('isError')}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)

finally:
    proc.terminate()
    proc.wait()
