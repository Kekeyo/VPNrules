#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clash Verge 节点编排与 VIP 分组可视化管理服务
"""

import os
import sys
import json
import yaml
import re
import shutil
import hashlib
import subprocess
import socket
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# Windows 控制台标准输出与后台守护进程兼容性加固
PORT = 8899
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
BACKUP_DIR = BASE_DIR / "backup"
# Windows 后台标准输出重定向与守护 (Auto-flush logger)
class AutoFlushLogger:
    def __init__(self, filepath, stdout_mirror=None):
        self.filepath = filepath
        self.stdout_mirror = stdout_mirror
        self._fp = None
    def _get_fp(self):
        if self._fp is None:
            self._fp = open(self.filepath, "a", encoding="utf-8")
        return self._fp
    def write(self, s):
        try:
            fp = self._get_fp()
            fp.write(s)
            fp.flush()
        except Exception:
            pass
        if self.stdout_mirror:
            try:
                self.stdout_mirror.write(s)
                self.stdout_mirror.flush()
            except Exception:
                pass
    def flush(self):
        try:
            if self._fp: self._fp.flush()
        except Exception:
            pass

logger = AutoFlushLogger(BASE_DIR / "server.log", sys.stdout if (sys.stdout and hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()) else None)
sys.stdout = logger
sys.stderr = logger
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR.mkdir(parents=True, exist_ok=True)

# 默认 Clash Verge 配置路径
VERGE_PROFILES_DIR = Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev" / "profiles"
VERGE_APP_DIR = VERGE_PROFILES_DIR.parent
VERGE_PROFILES_YAML = Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev" / "profiles.yaml"
USER_WORKSPACE_DIR = BASE_DIR / "workspace"

def guess_region(name: str):
    """根据节点名称推断地区及国旗"""
    n = name.upper()
    if any(k in n for k in ["JP", "JAPAN", "日本", "🇯🇵", "东京", "大阪"]):
        return {"code": "JP", "flag": "🇯🇵", "name": "日本"}
    if any(k in n for k in ["SG", "SINGAPORE", "新加坡", "🇸🇬", "狮城"]):
        return {"code": "SG", "flag": "🇸🇬", "name": "新加坡"}
    if any(k in n for k in ["HK", "HONGKONG", "香港", "🇭🇰"]):
        return {"code": "HK", "flag": "🇭🇰", "name": "香港"}
    if any(k in n for k in ["TW", "TAIWAN", "台湾", "🇹🇼", "台北"]):
        return {"code": "TW", "flag": "🇹🇼", "name": "台湾"}
    if any(k in n for k in ["US", "USA", "美国", "🇺🇸", "洛杉矶", "硅谷", "西雅图"]):
        return {"code": "US", "flag": "🇺🇸", "name": "美国"}
    if any(k in n for k in ["KR", "KOREA", "韩国", "🇰🇷", "首尔"]):
        return {"code": "KR", "flag": "🇰🇷", "name": "韩国"}
    if any(k in n for k in ["GB", "UK", "英国", "🇬🇧", "伦敦"]):
        return {"code": "GB", "flag": "🇬🇧", "name": "英国"}
    if any(k in n for k in ["DE", "GERMANY", "德国", "🇩🇪", "法兰克福"]):
        return {"code": "DE", "flag": "🇩🇪", "name": "德国"}
    if any(k in n for k in ["FR", "FRANCE", "法国", "🇫🇷", "巴黎"]):
        return {"code": "FR", "flag": "🇫🇷", "name": "法国"}
    return {"code": "OTHER", "flag": "🌐", "name": "其他"}

def guess_tags(name: str):
    """提取节点的特性标签"""
    tags = []
    if "IEPL" in name.upper():
        tags.append("IEPL专线")
    if "原生" in name:
        tags.append("原生IP")
    if "家宽" in name:
        tags.append("家庭宽带")
    if "中转" in name:
        tags.append("中转优化")
    if "直连" in name:
        tags.append("直连")
    if "5倍" in name or "5X" in name.upper():
        tags.append("高倍率")
    if "星链" in name or "STARLINK" in name.upper():
        tags.append("星链")
    return tags

def parse_yaml_profiles():
    """解析 profiles.yaml，结构化提取各项及 option 属性"""
    if not VERGE_PROFILES_YAML.exists():
        return {"current": "", "items": []}
    try:
        content = VERGE_PROFILES_YAML.read_text(encoding="utf-8", errors="ignore")
        pdata = yaml.safe_load(content) or {}
        current_uid = pdata.get("current", "")
        items = []
        for raw_item in pdata.get("items", []):
            if not isinstance(raw_item, dict):
                continue
            itype = raw_item.get("type")
            if itype in ["remote", "local"]:
                uid = raw_item.get("uid", "")
                opt = raw_item.get("option", {}) or {}
                items.append({
                    "uid": uid,
                    "name": raw_item.get("name", uid),
                    "type": itype,
                    "file": raw_item.get("file", f"{uid}.yaml"),
                    "is_current": (uid == current_uid),
                    "groups": opt.get("groups") or raw_item.get("groups", ""),
                    "rules": opt.get("rules") or raw_item.get("rules", ""),
                    "script": opt.get("script") or raw_item.get("script", ""),
                    "proxies": opt.get("proxies") or raw_item.get("proxies", "")
                })
        return {"current": current_uid, "items": items}
    except Exception as e:
        print(f"[ERROR] Failed to parse profiles.yaml: {e}")
        return {"current": "", "items": []}

def extract_host_and_root(input_str: str):
    """从输入的 URL 或域名清洗出纯净 host 及根域名"""
    s = (input_str or "").strip()
    if "://" in s:
        try:
            s = urllib.parse.urlparse(s).netloc
        except Exception:
            pass
    s = s.split("/")[0].split(":")[0].strip().lower()
    parts = s.split(".")
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] in ["com", "net", "org", "gov", "edu", "co", "io"]:
            root = ".".join(parts[-3:])
        else:
            root = ".".join(parts[-2:])
    else:
        root = s
    return s, root

def get_profiles_selected_map(uid: str = None):
    """解析 profiles.yaml 中各策略组当前选中的出网节点"""
    if not VERGE_PROFILES_YAML.exists():
        return {}
    content = VERGE_PROFILES_YAML.read_text(encoding="utf-8", errors="ignore")
    selected_map = {}
    matches = re.findall(r"-\s+name:\s*(.*?)\r?\n\s+now:\s*(.*?)(?:\r?\n|$)", content)
    for name, now in matches:
        selected_map[name.strip()] = now.strip()
    return selected_map

def simulate_rule_match(host: str, uid: str = None, custom_rules: list = None):
    """仿真 Clash 规则引擎，计算目标域名命中的规则、策略组及最终物理出口节点"""
    import time
    t0 = time.time()
    host_lower = host.lower()
    selected_map = get_profiles_selected_map(uid)

    def resolve_final_node(target_name: str):
        if target_name == "DIRECT":
            return "本地网络宽带直连"
        if target_name == "REJECT":
            return "⛔ 拦截丢弃"
        visited = set()
        curr = target_name
        while curr in selected_map and curr not in visited:
            visited.add(curr)
            curr = selected_map[curr]
        return curr if curr else target_name

    rules_chain = []
    # 1. 优先放入前置自定义规则 (Prepend Rules)
    if custom_rules is not None and isinstance(custom_rules, list):
        for r in custom_rules:
            rules_chain.append({
                "type": r.get("type", "DOMAIN-SUFFIX"),
                "payload": r.get("payload", "").strip(),
                "target": r.get("target", "节点选择"),
                "raw": r.get("raw") or f"{r.get('type')},{r.get('payload')},{r.get('target')}",
                "is_custom": True,
                "source": "前置自定义规则 (最高优先级)"
            })
    else:
        profiles_info = parse_yaml_profiles()
        target_prof = next((item for item in profiles_info.get("items", []) if item.get("uid") == uid), None)
        if not target_prof:
            cur_uid = profiles_info.get("current")
            target_prof = next((item for item in profiles_info.get("items", []) if item.get("uid") == cur_uid), None)
        if target_prof and target_prof.get("rules"):
            rf = VERGE_PROFILES_DIR / f"{target_prof['rules']}.yaml"
            if rf.exists():
                lines = rf.read_text(encoding="utf-8", errors="ignore").splitlines()
                in_prepend = False
                for line in lines:
                    l = line.strip()
                    if l == "prepend:":
                        in_prepend = True
                        continue
                    elif l.endswith(":") and not l.startswith("-"):
                        in_prepend = False
                    if in_prepend and l.startswith("-"):
                        rule_str = re.sub(r"^-\s*['\"]?(.*?)['\"]?\s*$", r"\1", l)
                        parts = [p.strip() for p in rule_str.split(",")]
                        if len(parts) >= 2:
                            rules_chain.append({
                                "type": parts[0],
                                "payload": parts[1] if len(parts) >= 3 else "",
                                "target": parts[2] if len(parts) >= 3 else parts[1],
                                "raw": rule_str,
                                "is_custom": True,
                                "source": "前置自定义规则 (最高优先级)"
                            })

    # 2. 读取运行态 clash-verge.yaml 的后续规则 (作为内置底层和 MATCH 兜底)
    clash_verge_yaml = Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev" / "clash-verge.yaml"
    if clash_verge_yaml.exists():
        in_r = False
        for line in clash_verge_yaml.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped == "rules:":
                in_r = True
                continue
            if in_r:
                if stripped.startswith("- "):
                    r_str = stripped[2:].strip().strip("'\"")
                    parts = [p.strip() for p in r_str.split(",")]
                    rtype = parts[0].upper()
                    payload = parts[1] if len(parts) >= 3 else ""
                    target = parts[2] if len(parts) >= 3 else (parts[1] if len(parts) == 2 else "DIRECT")
                    rules_chain.append({
                        "type": rtype,
                        "payload": payload,
                        "target": target,
                        "raw": r_str,
                        "is_custom": False,
                        "source": "兜底规则 (MATCH)" if rtype == "MATCH" else "订阅内置底层规则"
                    })
                elif line.startswith(" ") or not line:
                    continue
                else:
                    break

    # 3. 逐行匹配
    matched_rule = None
    matched_idx = -1
    for idx, r in enumerate(rules_chain):
        rtype = r["type"].upper()
        payload = r["payload"].lower()
        if rtype == "DOMAIN":
            if host_lower == payload:
                matched_rule = r; matched_idx = idx + 1; break
        elif rtype == "DOMAIN-SUFFIX":
            if host_lower == payload or host_lower.endswith("." + payload):
                matched_rule = r; matched_idx = idx + 1; break
        elif rtype == "DOMAIN-KEYWORD":
            if payload and payload in host_lower:
                matched_rule = r; matched_idx = idx + 1; break
        elif rtype == "MATCH":
            matched_rule = r; matched_idx = idx + 1; break

    match_time_ms = round((time.time() - t0) * 1000, 3)
    if not matched_rule:
        matched_rule = {
            "type": "MATCH",
            "payload": "",
            "target": "DIRECT",
            "raw": "MATCH,DIRECT",
            "is_custom": False,
            "source": "系统默认兜底"
        }
        matched_idx = len(rules_chain) + 1

    final_node = resolve_final_node(matched_rule["target"])
    return {
        "success": True,
        "host": host_lower,
        "matched": True,
        "rule_index": matched_idx,
        "total_rules": len(rules_chain),
        "rule": matched_rule,
        "target": matched_rule["target"],
        "final_node": final_node,
        "match_time_ms": match_time_ms
    }

def get_profile_nodes(profile_file_name: str):
    """从订阅文件解析节点列表（绝不返回任何密码和服务器凭据）"""
    file_path = VERGE_PROFILES_DIR / profile_file_name
    if not file_path.exists():
        return []
    
    nodes = []
    seen = set()
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return []

    # 正常情况直接按 YAML 读 proxies，分组（自动选择、故障转移等）不会混进来
    try:
        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict) and isinstance(parsed.get("proxies"), list):
            for p in parsed["proxies"]:
                n = str(p.get("name") or "").strip() if isinstance(p, dict) else ""
                if n and n not in seen:
                    seen.add(n)
                    is_info = bool(re.search(r"(剩余流量|套餐到期|重置|官网|群组|距离下次)", n))
                    reg = {"code": "INFO", "flag": "📊", "name": "提示"} if is_info else guess_region(n)
                    nodes.append({"name": n, "is_info": is_info, "region": reg, "tags": guess_tags(n)})
            return nodes
    except Exception:
        pass

    # 提取 proxies: 下的每项 name
    # 兼容两种常见格式:
    # 1. - { name: 'xxx', ... }
    # 2. - name: 'xxx'
    matches1 = re.findall(r"-\s*\{\s*name:\s*(['\"]?)(.*?)\1\s*,", content)
    for m in matches1:
        n = m[1].strip()
        if n and n not in seen:
            seen.add(n)
            is_info = bool(re.search(r"(剩余流量|套餐到期|重置|官网|群组|距离下次)", n))
            reg = {"code": "INFO", "flag": "📊", "name": "提示"} if is_info else guess_region(n)
            tags = guess_tags(n)
            nodes.append({
                "name": n,
                "is_info": is_info,
                "region": reg,
                "tags": tags
            })

    if not nodes:
        matches2 = re.findall(r"-\s+name:\s*(['\"]?)(.*?)\1\s*(?:\r?\n|$)", content)
        for m in matches2:
            n = m[1].strip()
            if n and n not in seen:
                seen.add(n)
                is_info = bool(re.search(r"(剩余流量|套餐到期|重置|官网|群组|距离下次)", n))
                reg = {"code": "INFO", "flag": "📊", "name": "提示"} if is_info else guess_region(n)
                tags = guess_tags(n)
                nodes.append({
                    "name": n,
                    "is_info": is_info,
                    "region": reg,
                    "tags": tags
                })

    return nodes


def launch_clash_verge():
    """打开或唤起 Clash Verge 客户端窗口"""
    exe_candidates = [
        Path.home() / "Clash Verge" / "clash-verge.exe",
        Path(r"C:\Program Files\Clash Verge\clash-verge.exe"),
    ]
    for exe in exe_candidates:
        if exe.exists():
            try:
                # 启动客户端，若已在运行则其单实例机制会自动置顶激活主窗口
                subprocess.Popen([str(exe)], shell=False)
                return True
            except Exception as e:
                print(f"[WARN] Failed to launch {exe}: {e}")
    return False

def get_current_groups_override(groups_file_name: str, sub_file_name: str = "", use_runtime: bool = True):
    """读取当前的分组覆写文件和运行时配置，分析所有分组（节点选择、Cloud专线、Google专线等）包含的节点列表"""
    custom_groups = []
    seen_names = set()

    # 1. 首先尝试从运行态 clash-verge.yaml 获取最新真实的策略组
    rt_file = VERGE_APP_DIR / "clash-verge.yaml"
    if use_runtime and rt_file.exists():
        try:
            rt_dict = yaml.safe_load(rt_file.read_text(encoding="utf-8", errors="ignore")) or {}
            for g in rt_dict.get("proxy-groups", []):
                if isinstance(g, dict) and "name" in g:
                    gn = g["name"]
                    # 排除自动测速与故障转移等非业务选择组
                    if gn == "GLOBAL":
                        continue
                    proxies = [p for p in g.get("proxies", []) if p not in ["DIRECT", "REJECT", "节点选择", "自动选择", "故障转移"]]
                    custom_groups.append({
                        "name": gn,
                        "type": g.get("type", "select"),
                        "proxies": proxies,
                        "count": len(proxies)
                    })
                    seen_names.add(gn)
        except Exception as e:
            print(f"[WARN] Error loading runtime groups: {e}")

    # 2. 如果还有特定 groups 文件补充
    file_path = VERGE_PROFILES_DIR / groups_file_name
    if file_path.exists():
        try:
            gdata = yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")) or {}
            for block_key in ["prepend", "append"]:
                for g in gdata.get(block_key, []):
                    if isinstance(g, dict) and "name" in g:
                        gn = g["name"]
                        if gn not in seen_names and gn not in ["自动选择", "故障转移", "GLOBAL"]:
                            proxies = [p for p in g.get("proxies", []) if p not in ["DIRECT", "REJECT", "节点选择", "自动选择", "故障转移"]]
                            custom_groups.append({
                                "name": gn,
                                "type": g.get("type", "select"),
                                "proxies": proxies,
                                "count": len(proxies)
                            })
                            seen_names.add(gn)
        except Exception as e:
            pass

    # 2.5 订阅自带的分组由全局脚本去掉，这里只留核心分组和分组覆写里自己建的
    keep = {"节点选择", "Google 专线", "Claude 专线", "搭载"}
    try:
        gd2 = (yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")) or {}) if file_path.is_file() else {}
        keep |= {g.get("name") for k in ("prepend", "append") for g in (gd2.get(k) or []) if isinstance(g, dict)}
    except Exception:
        pass
    custom_groups = [g for g in custom_groups if g["name"] in keep]

    # 3. 确保核心三大分组有序排在最前
    priority = ["节点选择", "Claude 专线", "Google 专线"]
    sorted_groups = []
    for p in priority:
        found = next((g for g in custom_groups if g["name"] == p), None)
        if found:
            sorted_groups.append(found)
        else:
            sorted_groups.append({
                "name": p,
                "type": "select",
                "proxies": [],
                "count": 0
            })
    for g in custom_groups:
        if g["name"] not in priority:
            sorted_groups.append(g)

    return {"custom_groups": sorted_groups}


CARRIER_GROUP = "搭载"
RES_SCRIPT = """// 住宅链路：把带 dialer-proxy 的住宅节点放进每个选择组最前面（搭载组本身除外，避免成环）
function main(config) {
  var res = (Array.isArray(config.proxies) ? config.proxies : [])
    .filter(function (p) { return p && p['dialer-proxy']; })
    .map(function (p) { return p.name; });
  if (!res.length || !Array.isArray(config['proxy-groups'])) return config;
  config['proxy-groups'].forEach(function (g) {
    if (!g || g.name === '搭载' || !Array.isArray(g.proxies)) return;
    if (g.type !== 'select') return;
    for (var i = res.length - 1; i >= 0; i--) {
      if (g.proxies.indexOf(res[i]) === -1) g.proxies.unshift(res[i]);
    }
  });
  return config;
}
"""

def _yaml_dump(d):
    return "# Profile Enhancement Template for Clash Verge" + chr(10) + yaml.safe_dump(d, allow_unicode=True, sort_keys=False)

def _load_ext(path):
    if path.exists():
        try:
            d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _item_span(content, uid):
    """返回 profiles.yaml 里该订阅条目的 (起, 止) 位置"""
    m = re.search(r"(?m)^- uid: " + re.escape(uid) + r"[ \t]*\r?$", content)
    if not m:
        return None
    n = re.search(r"(?m)^- uid: ", content[m.end():])
    end = m.end() + n.start() if n else len(content)
    return m.start(), end

def ensure_profile_ext(uid, key, ext_type, ext):
    """订阅还没有某种扩展文件（proxies/groups/script）时，自动建一个并绑定到该订阅。返回新 uid。"""
    import random, string, time
    new_uid = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(12))
    fname = f"{new_uid}.{ext}"
    if ext_type == "script":
        body = "function main(config) {" + chr(10) + "  return config;" + chr(10) + "}" + chr(10)
    else:
        body = ("prepend: []" + chr(10) + "append: []" + chr(10) + "delete: []" + chr(10))
    (VERGE_PROFILES_DIR / fname).write_text(body, encoding="utf-8")

    content = VERGE_PROFILES_YAML.read_text(encoding="utf-8")
    shutil.copy2(VERGE_PROFILES_YAML, BACKUP_DIR / f"profiles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml")
    span = _item_span(content, uid)
    if not span:
        raise RuntimeError("profiles.yaml 里找不到这个订阅")
    a, b = span
    block = content[a:b]
    nl = chr(13) + chr(10) if chr(13) in block else chr(10)
    om = re.search(r"(?m)^  option:[ \t]*\r?$", block)
    line = f"    {key}: {new_uid}"
    if om:
        block = block[:om.end()] + nl + line + block[om.end():]
    else:
        block = block.rstrip(chr(13) + chr(10)) + nl + "  option:" + nl + line + nl
    content = content[:a] + block + content[b:]
    if not content.endswith(nl):
        content += nl
    content += (f"- uid: {new_uid}" + nl + f"  type: {ext_type}" + nl + "  name: null" + nl +
                f"  file: {fname}" + nl + f"  updated: {int(time.time())}" + nl)
    VERGE_PROFILES_YAML.write_text(content, encoding="utf-8")
    return new_uid


CLEAN_MARK = "// cleanup-dangling"

def ensure_cleanup_script(script_file):
    """订阅脚本末尾加一段：把指向已不存在的分组/节点的引用去掉，规则里指向不存在分组的改走“节点选择”"""
    cur = script_file.read_text(encoding="utf-8", errors="ignore") if script_file.exists() else ""
    if CLEAN_MARK in cur:
        if "GROUP_ORDER" in cur:
            return
        # 旧版清理脚本没有“分组顺序”：拆掉旧的包装，重新包一次
        cur = cur[:cur.index(CLEAN_MARK)].rstrip() + chr(10)
        cur = cur.replace("function __origMain(", "function main(", 1)
    if "function main(" not in cur:
        cur = "function main(config) {" + chr(10) + "  return config;" + chr(10) + "}" + chr(10)
    cur = cur.replace("function main(", "function __origMain(", 1)
    cur += chr(10) + CLEAN_MARK + """
var GROUP_ORDER = []; // group-order
function main(config, profileName) {
  var c = __origMain(config, profileName) || config;
  var ok = { 'DIRECT': 1, 'REJECT': 1, 'REJECT-DROP': 1, 'PASS': 1, 'COMPATIBLE': 1 };
  (c.proxies || []).forEach(function (p) { if (p && p.name) ok[p.name] = 1; });
  (c['proxy-groups'] || []).forEach(function (g) { if (g && g.name) ok[g.name] = 1; });
  (c['proxy-groups'] || []).forEach(function (g) {
    if (g && Array.isArray(g.proxies)) g.proxies = g.proxies.filter(function (n) { return ok[n]; });
  });
  if (Array.isArray(c.rules)) {
    c.rules = c.rules.map(function (r) {
      if (typeof r !== 'string') return r;
      var a = r.split(',');
      var i = a[0] === 'MATCH' ? 1 : 2;
      if (a.length > i && !ok[a[i].trim()]) a[i] = '节点选择';
      return a.join(',');
    });
  }
  if (GROUP_ORDER.length && Array.isArray(c['proxy-groups'])) {
    var pos = function (n) { var i = GROUP_ORDER.indexOf(n); return i < 0 ? 1e6 : i; };
    c['proxy-groups'] = c['proxy-groups'].map(function (g, k) { return [g, k]; })
      .sort(function (a, b) { return (pos(a[0].name) - pos(b[0].name)) || (a[1] - b[1]); })
      .map(function (x) { return x[0]; });
  }
  return c;
}
"""
    script_file.write_text(cur, encoding="utf-8")


def _script_file_for(uid):
    t = residential_target(uid)
    if not t:
        return None
    su = t.get("script") or ensure_profile_ext(uid, "script", "script", "js")
    return VERGE_PROFILES_DIR / f"{su}.js"

def get_group_order(uid):
    sf = _script_file_for(uid) if residential_target(uid) and residential_target(uid).get("script") else None
    if not sf or not sf.exists():
        return []
    m = re.search(r"var GROUP_ORDER = (\[.*?\]); // group-order", sf.read_text(encoding="utf-8", errors="ignore"))
    try:
        return json.loads(m.group(1)) if m else []
    except Exception:
        return []

def set_group_order(uid, order):
    order = [str(x) for x in order if isinstance(x, str)]
    sf = _script_file_for(uid)
    if not sf:
        return False
    ensure_cleanup_script(sf)
    txt = sf.read_text(encoding="utf-8", errors="ignore")
    line = "var GROUP_ORDER = " + json.dumps(order, ensure_ascii=False) + "; // group-order"
    new, n = re.subn(r"var GROUP_ORDER = \[.*?\]; // group-order", lambda _m: line, txt, count=1)
    if not n:
        return False
    shutil.copy2(sf, BACKUP_DIR / f"{sf.stem}_{datetime.now():%Y%m%d_%H%M%S}.js")
    sf.write_text(new, encoding="utf-8")
    return True


def set_custom_group(name, keep):
    """全局脚本只留核心分组；网页上新建的分组要记进去，不然会被一起去掉"""
    if name in ("节点选择", "Google 专线", "Claude 专线", "搭载"):
        return
    f = VERGE_PROFILES_DIR / "Script.js"
    if not f.exists():
        return
    txt = f.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"var customGroups = (\[.*?\]); // custom-groups", txt)
    if not m:
        return
    cur = json.loads(m.group(1))
    if keep and name not in cur:
        cur.append(name)
    elif not keep and name in cur:
        cur.remove(name)
    else:
        return
    line = "var customGroups = " + json.dumps(cur, ensure_ascii=False) + "; // custom-groups"
    f.write_text(txt.replace(m.group(0), line, 1), encoding="utf-8")

def ensure_global_script():
    """首次运行：Verge 的全局脚本为空或还是默认内容时，装上项目自带的 Script.js；用户写过的脚本不覆盖"""
    dst, src = VERGE_PROFILES_DIR / "Script.js", BASE_DIR / "Script.js"
    if not VERGE_PROFILES_DIR.exists() or not src.exists():
        return
    old = dst.read_text(encoding="utf-8", errors="ignore") if dst.exists() else ""
    if "masterGoldenRules" in old or len(old.strip()) > 300:
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copy2(dst, BACKUP_DIR / f"Script_before_install_{datetime.now().strftime('%Y%m%d_%H%M%S')}.js")
    shutil.copy2(src, dst)

KERNEL_CANDIDATES = [
    Path.home() / "Clash Verge" / "verge-mihomo-alpha.exe",
    Path.home() / "Clash Verge" / "verge-mihomo.exe",
    Path(r"C:\Program Files\Clash Verge\verge-mihomo-alpha.exe"),
    Path(r"C:\Program Files\Clash Verge\verge-mihomo.exe"),
]
_chain_lock = threading.Lock()

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def _exit_via(port, timeout=8):
    """经本地代理端口查出口 IP；失败返回 None"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({
        "http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}))
    for url, pick in (
        ("https://ipinfo.io/json", lambda d: (d.get("ip"), d.get("country"), d.get("city"), d.get("org"))),
        ("http://ip-api.com/json/?fields=query,countryCode,city,isp", lambda d: (d.get("query"), d.get("countryCode"), d.get("city"), d.get("isp"))),
    ):
        t0 = time.time()
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
            ip, country, city, org = pick(d)
            if ip:
                return {"ip": ip, "country": country or "", "city": city or "", "org": org or "", "ms": int((time.time() - t0) * 1000)}
        except Exception:
            continue
    return None

def _kernel_get(path, timeout=3):
    """只读：向 Verge 正在运行的内核发 GET。连不上返回 None，否则返回 (状态码, json)"""
    return _kernel_req("GET", path, None, timeout)

def _kernel_req(method, path, body=None, timeout=3):
    box = {}
    def work():
        rt = yaml.safe_load((VERGE_APP_DIR / "clash-verge.yaml").read_text(encoding="utf-8", errors="ignore")) or {}
        # 配置里写的管道名和实际的可能不同（sidecar / production），以系统里实际存在的为准
        names = [n for n in os.listdir("\\\\.\\pipe\\") if n.startswith("verge-mihomo-")]
        if not names:
            return
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        req = (f"{method} {path} HTTP/1.0\r\nHost: x\r\nAuthorization: Bearer {rt.get('secret') or ''}\r\n"
               f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n").encode("utf-8") + data
        buf = b""
        f = None
        for _ in range(40):
            try:
                f = open("\\\\.\\pipe\\" + names[0], "r+b", buffering=0)
                break
            except OSError:
                time.sleep(0.05)
        if f is None:
            return
        with f:
            f.write(req)
            try:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    buf += chunk
                    head, sep, rest = buf.partition(b"\r\n\r\n")
                    m = re.search(rb"content-length:\s*(\d+)", head, re.I)
                    if sep and m and len(rest) >= int(m.group(1)):
                        break
            except OSError:
                pass
        head, _, rest = buf.partition(b"\r\n\r\n")
        code = int(head.split(b" ", 2)[1])
        try:
            box["r"] = (code, json.loads(rest.decode("utf-8", "ignore")))
        except Exception:
            box["r"] = (code, {})
    def safe():
        try:
            work()
        except Exception:
            pass
    th = threading.Thread(target=safe, daemon=True)
    th.start()
    th.join(timeout)
    return box.get("r")

def _kernel_proxy(name):
    return f"/proxies/{urllib.parse.quote(name, safe='')}"

def _kernel_now(group):
    """Verge 内核里某个组当前选中的节点。组不存在返回 ""，连不上内核返回 None"""
    r = _kernel_get(_kernel_proxy(group))
    if r is None:
        return None
    return (r[1].get("now") or "") if r[0] == 200 else ""

def _live_chain():
    """Verge 此刻真正在用的链路，全部以运行中的内核为准。带 _ 的字段含密码，不能发给页面"""
    if _kernel_get("/version") is None:
        return {"reachable": False}
    cur = next((i for i in parse_yaml_profiles()["items"] if i["is_current"]), None) or {}
    out = {"reachable": True, "exists": False, "uid": cur.get("uid", ""), "profile": re.sub(r"\.ya?ml$", "", str(cur.get("name", "")).strip(" \"'\\"))}
    try:
        rt = yaml.safe_load((VERGE_APP_DIR / "clash-verge.yaml").read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception:
        return out
    proxies = [p for p in (rt.get("proxies") or []) if isinstance(p, dict)]
    res = next((p for p in proxies if p.get("dialer-proxy")), None)
    if not res:
        return out
    r = _kernel_get(_kernel_proxy(res["name"]))
    if not r or r[0] != 200:
        return out
    # 顺着组一路找到真正的节点
    carrier = res["dialer-proxy"]
    for _ in range(5):
        r = _kernel_get(_kernel_proxy(carrier))
        now = r[1].get("now") if r and r[0] == 200 else None
        if not now:
            break
        carrier = now
    out.update(exists=True, residential=res["name"], server=res.get("server"), port=res.get("port"), carrier=carrier,
               _res=res, _carrier=next((p for p in proxies if p.get("name") == carrier), None))
    return out

def _public(live):
    return {k: v for k, v in live.items() if not k.startswith("_")}

def _kernel_delay(name):
    """让运行中的内核真实走一遍这个节点（和 Verge 里点测速一样，不切换任何选择）"""
    r = _kernel_get(_kernel_proxy(name) + "/delay?timeout=6000&url=" + urllib.parse.quote("https://www.gstatic.com/generate_204", safe=""), timeout=8)
    if r is None:
        return None             # 内核没回话，不代表节点不通
    return (r[1].get("delay") or 0) if r[0] == 200 else 0

def _watch_chains(port, stop, out):
    """请求进行时盯着内核的连接表，记下从这个测试端口进来的流量实际走了哪些节点"""
    while not stop.is_set():
        r = _kernel_get("/connections", timeout=2)
        for c in ((r[1].get("connections") or []) if r and r[0] == 200 else []):
            md = c.get("metadata") or {}
            if str(md.get("inboundPort")) == str(port) and c.get("chains"):
                out["chains"] = c["chains"]
                out["rule"] = c.get("rule")
        time.sleep(0.05)

def _watch_direct(host, stop, out):
    """盯着本机的连接：如果电脑直接连了住宅服务器，说明没有经过搭载节点"""
    try:
        ip = socket.gethostbyname(str(host))
    except OSError:
        return
    while not stop.is_set():
        try:
            txt = subprocess.run(["netstat", "-n", "-p", "TCP"], capture_output=True, text=True, errors="ignore", timeout=3,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            out["checked"] = True
            if re.search(r"\s" + re.escape(ip) + r":\d+\s", txt):
                out["direct"] = True
        except Exception:
            pass
        time.sleep(0.1)

def _real_probe(port):
    stop, seen = threading.Event(), {}
    th = threading.Thread(target=_watch_chains, args=(port, stop, seen), daemon=True)
    th.start()
    try:
        res = _exit_via(port, timeout=8)
    finally:
        stop.set()
        th.join(3)
    if res:
        res["chains"] = seen.get("chains") or []
    return res

def _live_probes(carrier_via, residential, res_server=None):
    """让 Verge 正在运行的内核临时多开两个本机测试端口，发真实请求，测完关掉。
    不改配置文件，也不切换任何选择。"""
    rt_text = (VERGE_APP_DIR / "clash-verge.yaml").read_text(encoding="utf-8")
    cfg = yaml.safe_load(rt_text) or {}
    pc, pr = _free_port(), _free_port()
    listener = lambda name, p, via: {"name": name, "type": "mixed", "listen": "127.0.0.1", "port": p, "proxy": via}
    cfg["listeners"] = (cfg.get("listeners") or []) + [listener("vg-test-carrier", pc, carrier_via), listener("vg-test-res", pr, residential)]
    before = _selections()
    r = _kernel_req("PUT", "/configs?force=false", {"payload": yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)}, timeout=20)
    if not r or r[0] not in (200, 204):
        raise RuntimeError((r[1].get("message") if r else "") or "内核没开测试端口")
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", pr), timeout=0.3).close()
                socket.create_connection(("127.0.0.1", pc), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.1)
        stop, direct = threading.Event(), {}
        watcher = threading.Thread(target=_watch_direct, args=(res_server, stop, direct), daemon=True)
        watcher.start()
        try:
            with ThreadPoolExecutor(2) as ex:
                fc, fr = ex.submit(_real_probe, pc), ex.submit(_real_probe, pr)
                c_exit, r_exit = fc.result(), fr.result()
        finally:
            stop.set()
            watcher.join(4)
        if r_exit:
            r_exit["direct_checked"] = bool(direct.get("checked"))
            r_exit["direct"] = bool(direct.get("direct"))
        return c_exit, r_exit
    finally:
        # 无论结果如何都把测试端口关掉，失败就再试一次
        for _ in range(2):
            r = _kernel_req("PUT", "/configs?force=false", {"payload": rt_text}, timeout=20)
            if r and r[0] in (200, 204):
                break
            time.sleep(0.5)
        after = _selections() or {}
        for g, now in (before or {}).items():
            if g in after and after[g] != now:
                _kernel_req("PUT", _kernel_proxy(g), {"name": now}, timeout=5)

def test_chain():
    """实测 Verge 此刻真正在用的链路：真实请求经运行中的内核走一遍，出口 IP 是外网看到的结果"""
    if not _chain_lock.acquire(blocking=False):
        return {"success": False, "error": "上一次测试还没结束"}
    try:
        live = _live_chain()
        if not live.get("reachable"):
            return {"success": False, "error": "连不上 Verge 内核，确认 Verge 开着"}
        if not live.get("exists"):
            return {"success": False, "error": "Verge 里没有住宅链路，点“写入”后生效", **_public(live)}
        with ThreadPoolExecutor(3) as ex:
            fc = ex.submit(_kernel_delay, live["carrier"])
            fr = ex.submit(_kernel_delay, live["residential"])
            c_ms, r_ms = fc.result(), fr.result()
        if c_ms is None or r_ms is None:
            return {"success": False, "error": "读 Verge 内核超时，再试一次", **_public(live)}
        with _apply_lock:
            try:
                c_exit, r_exit = _live_probes(live["_res"]["dialer-proxy"], live["residential"], live.get("server"))
            except Exception as e:
                return {"success": False, "error": f"实测没跑成：{e}"[:200], **_public(live)}
        if not c_exit:
            status = "carrier_fail"
        elif not r_exit:
            status = "res_fail"
        elif r_exit["ip"] == c_exit["ip"]:
            status = "same"
        elif r_exit.get("direct"):
            status = "direct"
        else:
            status = "ok"
        tun = False
        try:
            vy = yaml.safe_load((VERGE_APP_DIR / "verge.yaml").read_text(encoding="utf-8", errors="ignore")) or {}
            tun = bool(vy.get("enable_tun_mode"))
        except Exception:
            pass
        return {"success": True, "status": status, "carrier_ms": c_ms, "res_ms": r_ms, "carrier_exit": c_exit,
                "exit": r_exit, "tun": tun, **_public(live)}
    finally:
        _chain_lock.release()

_apply_lock = threading.Lock()

def _build_runtime(item, base):
    """按 Verge 的顺序算出最终配置：订阅 -> 扩展 -> 全局脚本 -> 订阅脚本；端口、DNS、TUN 等沿用 base"""
    sub = yaml.safe_load((VERGE_PROFILES_DIR / item["file"]).read_text(encoding="utf-8", errors="ignore")) or {}
    px = _load_ext(VERGE_PROFILES_DIR / f"{item['proxies']}.yaml") if item.get("proxies") else {}
    gr = _load_ext(VERGE_PROFILES_DIR / f"{item['groups']}.yaml") if item.get("groups") else {}
    ru = _load_ext(VERGE_PROFILES_DIR / f"{item['rules']}.yaml") if item.get("rules") else {}
    names = lambda seq: {x if isinstance(x, str) else (x or {}).get("name") for x in (seq or [])}
    dp, dg, dr = names(px.get("delete")), names(gr.get("delete")), set(ru.get("delete") or [])
    sub["proxies"] = (px.get("prepend") or []) + [p for p in (sub.get("proxies") or []) if p.get("name") not in dp] + (px.get("append") or [])
    sub["proxy-groups"] = (gr.get("prepend") or []) + [g for g in (sub.get("proxy-groups") or []) if g.get("name") not in dg] + (gr.get("append") or [])
    sub["rules"] = (ru.get("prepend") or []) + [r for r in (sub.get("rules") or []) if r not in dr] + (ru.get("append") or [])
    runner = (
        "const fs=require('fs');const [,,sp,ip,op,name]=process.argv;"
        "const main=new Function(fs.readFileSync(sp,'utf8')+';return main')();"
        "fs.writeFileSync(op,JSON.stringify(main(JSON.parse(fs.readFileSync(ip,'utf8')),name)));"
    )
    tmp = tempfile.mkdtemp(prefix="verge_apply_")
    try:
        rp, ip, op = Path(tmp) / "r.js", Path(tmp) / "i.json", Path(tmp) / "o.json"
        rp.write_text(runner, encoding="utf-8")
        scripts = [VERGE_PROFILES_DIR / "Script.js"]
        if item.get("script"):
            scripts.append(VERGE_PROFILES_DIR / f"{item['script']}.js")
        for sc in scripts:
            ip.write_text(json.dumps(sub, ensure_ascii=False), encoding="utf-8")
            subprocess.run(["node", str(rp), str(sc), str(ip), str(op), str(item.get("name") or "")], check=True, timeout=20,
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            sub = json.loads(op.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = dict(base)
    out["proxies"], out["proxy-groups"], out["rules"] = sub.get("proxies") or [], sub.get("proxy-groups") or [], sub.get("rules") or []
    for k in ("proxy-providers", "rule-providers"):
        if sub.get(k):
            out[k] = sub[k]
        else:
            out.pop(k, None)
    return out

def _kernel_check(text):
    """把配置交给内核检查一遍，返回 None 表示通过，否则返回错误信息。临时目录里有密码，用完就删"""
    kernel = next((k for k in KERNEL_CANDIDATES if k.exists()), None)
    if not kernel:
        return "没找到 Verge 内核"
    tmp = tempfile.mkdtemp(prefix="verge_check_")
    try:
        for f in list(VERGE_APP_DIR.glob("*.mmdb")) + list(VERGE_APP_DIR.glob("*.dat")):
            try:
                os.link(f, Path(tmp) / f.name)
            except OSError:
                shutil.copy2(f, tmp)
        # 只查节点、分组、规则；DNS、TUN、控制通道不进检查，否则内核可能去下载地理数据或一直等
        full = yaml.safe_load(text) or {}
        slim = {k: full[k] for k in ("proxies", "proxy-groups", "rules", "proxy-providers", "rule-providers") if k in full}
        slim["log-level"] = "silent"
        cfg = Path(tmp) / "c.yaml"
        cfg.write_text(yaml.safe_dump(slim, allow_unicode=True, sort_keys=False), encoding="utf-8")
        r = subprocess.run([str(kernel), "-t", "-d", tmp, "-f", str(cfg)], capture_output=True, text=True, encoding="utf-8", errors="ignore",
                           timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return None
        out = r.stdout + r.stderr
        m = re.findall(r'level=(?:error|fatal) msg="([^"]+)"', out)
        return (m[-1] if m else "配置检查没通过")[:200]
    except subprocess.TimeoutExpired:
        return "内核检查超时"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _selections():
    r = _kernel_get("/proxies", timeout=5)
    if not r or r[0] != 200:
        return None
    return {k: v.get("now") for k, v in (r[1].get("proxies") or {}).items() if v.get("type") == "Selector"}

def apply_current(uid=None):
    """让 Verge 正在用的订阅马上生效，不用去 Verge 刷新。只有 uid 正好是正在用的订阅才动内核。"""
    with _apply_lock:
        items = parse_yaml_profiles()["items"]
        cur = next((i for i in items if i["is_current"]), None)
        if not cur:
            return {"applied": False, "apply_error": "Verge 没有正在用的订阅"}
        if uid and uid != cur["uid"]:
            name = re.sub(r"\.ya?ml$", "", str(cur.get("name") or "").strip(" \"'\\"))
            return {"applied": False, "apply_note": f"已保存。Verge 正在用 {name}，在 Verge 里切到这个订阅才生效"}
        if not shutil.which("node"):
            return {"applied": False, "apply_note": "已保存。这台电脑没有 Node.js，到 Verge 刷新订阅后生效"}
        for mf in [VERGE_PROFILES_DIR / "Merge.yaml"] + ([VERGE_PROFILES_DIR / f"{parse_merge_uid(cur)}.yaml"] if parse_merge_uid(cur) else []):
            if set(_load_ext(mf).keys()) - {"profile", "prepend", "append", "delete"}:
                return {"applied": False, "apply_note": "已保存。Merge 里有自定义内容，到 Verge 刷新订阅后生效"}
        rt_path = VERGE_APP_DIR / "clash-verge.yaml"
        try:
            old_text = rt_path.read_text(encoding="utf-8")
            new_cfg = _build_runtime(cur, yaml.safe_load(old_text) or {})
            new_text = yaml.safe_dump(new_cfg, allow_unicode=True, sort_keys=False)
        except Exception as e:
            return {"applied": False, "apply_error": f"生成配置失败：{type(e).__name__}"}
        err = _kernel_check(new_text)
        if err:
            return {"applied": False, "apply_error": f"配置有问题，没有应用：{err}"}
        before = _selections()
        if before is None:
            return {"applied": False, "apply_note": "已保存。连不上 Verge 内核，开着 Verge 后到里面刷新订阅"}
        (BACKUP_DIR / "clash-verge_last.yaml").write_text(old_text, encoding="utf-8")
        rt_path.write_text(new_text, encoding="utf-8")
        # 直接把内容发给内核（发路径会被内核的安全目录限制拒绝）
        r = _kernel_req("PUT", "/configs?force=false", {"payload": new_text}, timeout=20)
        if not r or r[0] not in (200, 204):
            rt_path.write_text(old_text, encoding="utf-8")
            why = (r[1].get("message") if r else "") or ""
            return {"applied": False, "apply_error": f"内核没接受新配置，已恢复原配置 {why}".strip()[:200]}
        # 重新加载后保持原来选的节点
        restored = 0
        after = _selections() or {}
        for g, now in before.items():
            if g in after and after[g] != now:
                if _kernel_req("PUT", _kernel_proxy(g), {"name": now}, timeout=5):
                    restored += 1
        return {"applied": True, "restored": restored}

def parse_merge_uid(item):
    try:
        pdata = yaml.safe_load(VERGE_PROFILES_YAML.read_text(encoding="utf-8", errors="ignore")) or {}
        raw = next((i for i in pdata.get("items", []) if isinstance(i, dict) and i.get("uid") == item["uid"]), {})
        return (raw.get("option") or {}).get("merge") or ""
    except Exception:
        return ""

def _with_apply(result, uid=None):
    if isinstance(result, dict) and result.get("success"):
        result.update(apply_current(uid))
    return result

TEMPLATE_RE = re.compile(r"(var masterGoldenRules = \[)(.*?)(\n  \];)", re.S)

def _template_file():
    return VERGE_PROFILES_DIR / "Script.js"

def get_template_rules():
    """全局脚本里的通用模板规则"""
    f = _template_file()
    if not f.exists():
        return []
    m = TEMPLATE_RE.search(f.read_text(encoding="utf-8", errors="ignore"))
    if not m:
        return []
    return re.findall(r"""(?m)^\s*['"]([^'"\n]+)['"],?\s*(?://.*)?$""", m.group(2))

def update_template(rules):
    """用这份规则覆盖通用模板。各订阅在 Verge 刷新后生效"""
    if not isinstance(rules, list) or not rules:
        return {"success": False, "error": "当前没有规则，模板没动"}
    clean, seen = [], set()
    for r in rules:
        rule_type = str((r or {}).get("type") or "DOMAIN-SUFFIX").strip()
        payload = str((r or {}).get("payload") or "").strip()
        target = str((r or {}).get("target") or "节点选择").strip()
        if not payload or not re.fullmatch(r"[A-Z0-9-]+", rule_type) or re.search(r"[,'\"\r\n\\]", payload + target):
            return {"success": False, "error": f"规则不合法：{payload or rule_type}"}
        if (rule_type, payload) not in seen:      # 同一个域名只留排前面的
            seen.add((rule_type, payload))
            clean.append(f"{rule_type},{payload},{target}")
    f = _template_file()
    if not f.exists():
        return {"success": False, "error": "没找到全局脚本"}
    src = f.read_text(encoding="utf-8")
    if not TEMPLATE_RE.search(src):
        return {"success": False, "error": "全局脚本里没找到模板"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, BACKUP_DIR / f"Script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.js")
    body = chr(10) + ("," + chr(10)).join("    " + json.dumps(x, ensure_ascii=False) for x in clean)
    new = TEMPLATE_RE.sub(lambda m: m.group(1) + body + m.group(3), src, count=1)
    f.write_text(new, encoding="utf-8")
    return {"success": True, "count": len(clean)}

def residential_target(uid):
    info = parse_yaml_profiles()
    t = next((i for i in info["items"] if i["uid"] == uid), None)
    return t

def get_residential(uid):
    t = residential_target(uid)
    if not t:
        return {"error": "未找到订阅"}
    pf = t.get("proxies")
    node = None
    if pf:
        d = _load_ext(VERGE_PROFILES_DIR / f"{pf}.yaml")
        for n in d.get("prepend", []) or []:
            if isinstance(n, dict) and n.get("dialer-proxy"):
                node = n
                break
    if not node:
        return {"exists": False, "ready": bool(pf and t.get("groups") and t.get("script"))}
    carrier = ""
    if t.get("groups"):
        gd = _load_ext(VERGE_PROFILES_DIR / f"{t['groups']}.yaml")
        cg = next((g for g in (gd.get("prepend") or []) if isinstance(g, dict) and g.get("name") == CARRIER_GROUP), None)
        if cg and cg.get("proxies"):
            carrier = cg["proxies"][0]
    return {"exists": True, "name": node.get("name"), "type": node.get("type"), "server": node.get("server"),
            "port": node.get("port"), "username": node.get("username", ""), "has_password": bool(node.get("password")),
            "carrier": carrier, "ready": True,
            "live_carrier": _kernel_now(CARRIER_GROUP) if t.get("is_current") else None}

def setup_residential(data):
    uid = data.get("uid")
    name = (data.get("name") or "").strip() or "🏠 住宅节点"
    server = (data.get("server") or "").strip()
    port = data.get("port")
    username = data.get("username") or ""
    password = data.get("password") or ""
    carrier = (data.get("carrier") or "").strip()
    ptype = data.get("type") or "socks5"
    if ptype not in ("socks5", "http"):
        return {"success": False, "error": "类型只支持 socks5 / http"}
    try:
        port = int(port)
    except Exception:
        return {"success": False, "error": "端口不对"}
    if not uid or not server or not (0 < port < 65536):
        return {"success": False, "error": "请填 IP 和端口"}
    if not re.fullmatch(r"[A-Za-z0-9._:\-\[\]]+", server):
        return {"success": False, "error": "IP 或域名里有不合法字符"}
    t = residential_target(uid)
    if not t:
        return {"success": False, "error": "未找到订阅"}
    pf, gf, sf = t.get("proxies"), t.get("groups"), t.get("script")
    try:
        if not pf:
            pf = ensure_profile_ext(uid, "proxies", "proxies", "yaml")
        if not gf:
            gf = ensure_profile_ext(uid, "groups", "groups", "yaml")
        if not sf:
            sf = ensure_profile_ext(uid, "script", "script", "js")
    except Exception as e:
        return {"success": False, "error": f"自动创建扩展文件失败：{e}"}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pfile, gfile, sfile = (VERGE_PROFILES_DIR / f"{pf}.yaml", VERGE_PROFILES_DIR / f"{gf}.yaml", VERGE_PROFILES_DIR / f"{sf}.js")
    for f in (pfile, gfile, sfile):
        if f.exists():
            shutil.copy2(f, BACKUP_DIR / f"{f.stem}_{ts}{f.suffix}")

    # 1. 住宅节点
    pd = _load_ext(pfile)
    prepend = [n for n in (pd.get("prepend") or []) if isinstance(n, dict)]
    old = next((n for n in prepend if n.get("name") == name), None) or next((n for n in prepend if n.get("dialer-proxy")), None)
    if old and not password:
        password = old.get("password", "")
        if not username:
            username = old.get("username", "")
    node = {"name": name, "type": ptype, "server": server, "port": port}
    if username:
        node["username"] = username
    if password:
        node["password"] = password
    node["dialer-proxy"] = CARRIER_GROUP
    node["udp"] = True
    prepend = [n for n in prepend if n.get("name") != name and not (old and n is old)]
    prepend.insert(0, node)
    pd["prepend"] = prepend
    pd.setdefault("append", [])
    pd.setdefault("delete", [])
    pfile.write_text(_yaml_dump(pd), encoding="utf-8")

    # 2. 搭载组：订阅里所有机场节点（不含住宅和提示节点），所选搭载节点排第一
    nodes = [n["name"] for n in get_profile_nodes(t["file"]) if not n.get("is_info")]
    res_names = {n.get("name") for n in prepend if n.get("dialer-proxy")}
    members = [n for n in nodes if n not in res_names]
    if carrier in members:
        members.remove(carrier)
        members.insert(0, carrier)
    elif carrier:
        return {"success": False, "error": "搭载节点不在订阅里"}
    gd = _load_ext(gfile)
    groups = [g for g in (gd.get("prepend") or []) if isinstance(g, dict) and g.get("name") != CARRIER_GROUP]
    groups.insert(0, {"name": CARRIER_GROUP, "type": "select", "proxies": members})
    gd["prepend"] = groups
    gd.setdefault("append", [])
    dele = [x for x in (gd.get("delete") or []) if x != CARRIER_GROUP]
    dele.append(CARRIER_GROUP)
    gd["delete"] = dele
    gfile.write_text(_yaml_dump(gd), encoding="utf-8")

    # 3. 脚本：没有住宅处理逻辑时才写入通用的
    cur = sfile.read_text(encoding="utf-8", errors="ignore") if sfile.exists() else ""
    m = re.search(r"var targetNode = '[^']*';", cur)
    if m:
        safe = name.replace(chr(92), chr(92)*2).replace("'", chr(92) + "'")
        sfile.write_text(cur.replace(m.group(0), "var targetNode = '" + safe + "';"), encoding="utf-8")
    elif "dialer-proxy" not in cur:
        sfile.write_text(RES_SCRIPT, encoding="utf-8")
    return {"success": True, "name": name, "members": len(members), "carrier": members[0] if members else ""}


class VergeAPIHandler(BaseHTTPRequestHandler):
    def _from_local_page(self, check_origin=False):
        """只接受本机页面的请求：别的网页不能读节点，也不能改配置"""
        local = re.compile(r"(https?://)?(127\.0\.0\.1|localhost)(:\d+)?$")
        origin = self.headers.get("Origin")
        if local.match(self.headers.get("Host", "")) and not (check_origin and origin and not local.match(origin)):
            return True
        self.send_json({"success": False, "error": "只能从本机页面调用"}, 403)
        return False

    def do_GET(self):
        if not self._from_local_page():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/status":
            self.send_json({
                "verge_installed": VERGE_PROFILES_YAML.exists(),
                "profiles_dir": str(VERGE_PROFILES_DIR),
                "profiles_yaml": str(VERGE_PROFILES_YAML),
                "workspace_dir": str(USER_WORKSPACE_DIR)
            })
            return

        if path == "/api/profiles":
            data = parse_yaml_profiles()
            self.send_json(data)
            return

        if path == "/api/nodes":
            uid = params.get("uid", [""])[0]
            profiles_info = parse_yaml_profiles()
            target = next((item for item in profiles_info["items"] if item["uid"] == uid), None)
            if not target:
                self.send_json({"error": "Profile not found"}, status=404)
                return

            nodes = get_profile_nodes(target["file"])
            groups_file_name = f"{target.get('groups', '')}.yaml" if target.get("groups") else ""
            override_info = get_current_groups_override(groups_file_name, target["file"], bool(target.get("is_current")))

            # 如果「节点选择」组尚无明确选定列表，默认勾选当前订阅的所有有效物理节点
            for g in override_info.get("custom_groups", []):
                if g["name"] == "节点选择" and len(g["proxies"]) == 0:
                    valid_nodes = [n["name"] for n in nodes if not n.get("is_info_card")]
                    g["proxies"] = valid_nodes
                    g["count"] = len(valid_nodes)

            self.send_json({
                "profile": target,
                "nodes": nodes,
                "total_nodes": len(nodes),
                "override": override_info
            })
            return

        if path == "/api/group-order":
            self.send_json({"order": get_group_order(params.get("uid", [""])[0])})
            return

        if path == "/api/template":
            self.send_json({"rules": get_template_rules()})
            return

        if path == "/api/live-chain":
            self.send_json(_public(_live_chain()))
            return

        if path == "/api/residential":
            self.send_json(get_residential(params.get("uid", [""])[0]))
            return

        if path == "/api/launch-verge":
            success = launch_clash_verge()
            self.send_json({"success": success, "message": "Clash Verge 已唤起打开" if success else "未找到客户端安装路径"})
            return

        if path == "/api/rules":
            uid = params.get("uid", [""])[0]
            profiles_info = parse_yaml_profiles()
            target = next((item for item in profiles_info["items"] if item["uid"] == uid), None)
            if not target:
                self.send_json({"error": "Profile not found"}, status=404)
                return

            rules_uid = target.get("rules")
            rules_list = []
            if rules_uid:
                rf = VERGE_PROFILES_DIR / f"{rules_uid}.yaml"
                if rf.exists():
                    lines = rf.read_text(encoding="utf-8").splitlines()
                    in_prepend = False
                    for line in lines:
                        l = line.strip()
                        if l == "prepend:":
                            in_prepend = True
                            continue
                        elif l.endswith(":") and not l.startswith("-"):
                            in_prepend = False
                        if in_prepend and l.startswith("-"):
                            rule_str = re.sub(r"^-\s*['\"]?(.*?)['\"]?\s*$", r"\1", l)
                            parts = [p.strip() for p in rule_str.split(",")]
                            if len(parts) >= 3:
                                rules_list.append({
                                    "raw": rule_str,
                                    "type": parts[0],
                                    "payload": parts[1],
                                    "target": parts[2]
                                })
                            elif len(parts) == 2:
                                rules_list.append({
                                    "raw": rule_str,
                                    "type": parts[0],
                                    "payload": parts[1],
                                    "target": "DIRECT"
                                })

            # 这个订阅还没有自己的规则（比如新订阅）：显示正在生效的通用模板
            from_template = not rules_list
            if from_template:
                for rule_str in get_template_rules():
                    parts = [p.strip() for p in rule_str.split(",")]
                    if len(parts) >= 3:
                        rules_list.append({"raw": rule_str, "type": parts[0], "payload": parts[1], "target": parts[2]})

            # 提取当前所有可用的策略组 (包含核心四大分类：DIRECT、节点选择、Claude 专线、Google 专线等)
            gl = get_current_groups_override(f"{target['groups']}.yaml" if target.get("groups") else "", target["file"], bool(target.get("is_current")))
            available_groups = [g["name"] for g in gl["custom_groups"]]

            self.send_json({
                "profile": target,
                "rules_uid": rules_uid,
                "rules": rules_list,
                "total": len(rules_list),
                "available_groups": available_groups
            })
            return

        if path == "/api/test-rule":
            domain = params.get("domain", [""])[0]
            uid = params.get("uid", [""])[0]
            if not domain:
                self.send_json({"error": "Missing domain parameter"}, status=400)
                return
            h, root = extract_host_and_root(domain)
            res = simulate_rule_match(h, uid=uid)
            res["root_domain"] = root
            self.send_json(res)
            return

        # 静态文件版本号：web 里任何 .html/.js/.css 变了，这个值就变，页面弹“点这里刷新”
        if path == "/api/page-version":
            parts = []
            for p in sorted(WEB_DIR.rglob("*")):
                if p.is_file() and p.suffix in (".html", ".js", ".css"):
                    st = p.stat()
                    parts.append(f"{p.relative_to(WEB_DIR)}:{int(st.st_mtime)}:{st.st_size}")
            self.send_json({"v": hashlib.md5("|".join(parts).encode()).hexdigest()[:12]})
            return

        # 静态文件服务
        if path == "/" or path == "":
            path = "/index.html"
        file_path = WEB_DIR / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            content_type = "text/html; charset=utf-8"
            if file_path.suffix == ".css": content_type = "text/css"
            elif file_path.suffix == ".js": content_type = "application/javascript"
            elif file_path.suffix == ".json": content_type = "application/json"
            elif file_path.suffix == ".png": content_type = "image/png"
            
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        if not self._from_local_page(check_origin=True):
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/refresh-sub":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            uid = data.get("uid")
            result = refresh_remote_subscription(uid)
            self.send_json(result)
            return

        if parsed.path == "/api/save-group":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            result = self.handle_save_group(data)
            self.send_json(_with_apply(result, data.get("uid")))
            return

        if parsed.path == "/api/group-order":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json({"success": False, "error": "请求格式不对"}, 400)
                return
            ok = set_group_order(body.get("uid"), body.get("order") or [])
            self.send_json(_with_apply({"success": ok, "error": "" if ok else "保存顺序失败"}, body.get("uid")))
            return

        if parsed.path == "/api/setup-residential":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json({"success": False, "error": "请求格式不对"}, 400)
                return
            self.send_json(_with_apply(setup_residential(body), body.get("uid")))
            return

        if parsed.path == "/api/update-template":
            # 会改所有订阅共用的全局脚本，只接受本机页面发来的请求
            local = re.compile(r"(https?://)?(127\.0\.0\.1|localhost)(:\d+)?$")
            origin = self.headers.get("Origin")
            if not local.match(self.headers.get("Host", "")) or (origin and not local.match(origin)):
                self.send_json({"success": False, "error": "只能从本机页面调用"}, 403)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json({"success": False, "error": "请求格式不对"}, 400)
                return
            self.send_json(_with_apply(update_template(body.get("rules"))))
            return

        if parsed.path == "/api/test-chain":
            # 会用订阅节点和住宅账号连外网，只接受本机页面发来的请求
            local = re.compile(r"(https?://)?(127\.0\.0\.1|localhost)(:\d+)?$")
            origin = self.headers.get("Origin")
            if not local.match(self.headers.get("Host", "")) or (origin and not local.match(origin)):
                self.send_json({"success": False, "error": "只能从本机页面调用"}, 403)
                return
            self.send_json(test_chain())
            return

        if parsed.path == "/api/delete-group":
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except Exception:
                data = {}
            self.send_json(_with_apply(self.handle_delete_group(data), data.get("uid")))
            return

        if parsed.path == "/api/save-rules":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            result = self.handle_save_rules(data)
            self.send_json(_with_apply(result, data.get("uid")))
            return

        if parsed.path == "/api/test-rule":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            domain = data.get("domain", "")
            uid = data.get("uid", "")
            rules = data.get("rules", None)
            if not domain:
                self.send_json({"error": "Missing domain parameter"}, status=400)
                return
            h, root = extract_host_and_root(domain)
            res = simulate_rule_match(h, uid=uid, custom_rules=rules)
            res["root_domain"] = root
            self.send_json(res)
            return

        self.send_response(404)
        self.end_headers()

    def handle_save_rules(self, data):
        """保存自定义规则覆写并生成时间戳双重备份"""
        uid = data.get("uid")
        rules = data.get("rules", [])
        if not uid or not isinstance(rules, list):
            return {"success": False, "error": "缺少必要参数（订阅UID或规则列表）"}

        profiles_info = parse_yaml_profiles()
        target = next((item for item in profiles_info["items"] if item["uid"] == uid), None)
        if not target:
            return {"success": False, "error": "未找到指定的订阅配置"}

        rules_uid = target.get("rules")
        if not rules_uid:
            rules_uid = f"rules_{uid[:8]}"
            self.bind_profile_option(uid, "rules", rules_uid)

        rules_file = VERGE_PROFILES_DIR / f"{rules_uid}.yaml"
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        if rules_file.exists():
            backup_file = BACKUP_DIR / f"{rules_uid}_{now_str}.yaml"
            backup_file.write_bytes(rules_file.read_bytes())

        yaml_lines = [
            "# Profile Enhancement Rules Template for Clash Verge",
            f"# Generated by Antigravity VIP Rules Manager at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "prepend:"
        ]
        for r in rules:
            if isinstance(r, dict):
                rule_type = (r.get("type") or "DOMAIN-SUFFIX").strip()
                rule_payload = (r.get("payload") or "").strip()
                rule_target = (r.get("target") or "节点选择").strip()
                if rule_payload:
                    raw = f"{rule_type},{rule_payload},{rule_target}"
                else:
                    raw = r.get("raw", "").strip()
            elif isinstance(r, str):
                raw = r.strip()
            else:
                raw = ""

            if raw:
                escaped = raw.replace("'", "''")
                yaml_lines.append(f"  - '{escaped}'")

        yaml_lines.extend(["", "append: []", ""])
        content = "\n".join(yaml_lines)
        rules_file.write_text(content, encoding="utf-8")

        # 同步备份至工作区目录
        try:
            USER_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            (USER_WORKSPACE_DIR / f"{rules_uid}.yaml").write_text(content, encoding="utf-8")
        except Exception:
            pass

        # 深度全量同步：将本次保存的所有前置规则实时置顶注入当前运行态 clash-verge.yaml
        runtime_updated = False
        try:
            runtime_yaml = VERGE_APP_DIR / "clash-verge.yaml"
            if runtime_yaml.exists():
                rt_dict = yaml.safe_load(runtime_yaml.read_text(encoding="utf-8", errors="ignore"))
                if rt_dict and isinstance(rt_dict, dict) and "rules" in rt_dict:
                    current_rules = rt_dict.get("rules", [])
                    new_prepend_rules = []
                    for r in rules:
                        if isinstance(r, dict):
                            rule_type = (r.get("type") or "DOMAIN-SUFFIX").strip()
                            rule_payload = (r.get("payload") or "").strip()
                            rule_target = (r.get("target") or "节点选择").strip()
                            raw = f"{rule_type},{rule_payload},{rule_target}" if rule_payload else r.get("raw", "").strip()
                        elif isinstance(r, str):
                            raw = r.strip()
                        else:
                            raw = ""
                        if raw and raw not in new_prepend_rules:
                            new_prepend_rules.append(raw)

                    # 过滤掉已存在的旧规则并把新规则置顶
                    filtered_rules = [cr for cr in current_rules if cr not in new_prepend_rules]
                    rt_dict["rules"] = new_prepend_rules + filtered_rules
                    
                    # 确保四大分类代理组健全
                    groups = rt_dict.get('proxy-groups', [])
                    gnames = [g.get('name') for g in groups if isinstance(g, dict)]
                    for need_group in ['Google 专线', 'Claude 专线']:
                        if need_group not in gnames:
                            groups.append({
                                'name': need_group,
                                'type': 'select',
                                'proxies': ['节点选择', 'DIRECT']
                            })
                    rt_dict['proxy-groups'] = groups

                    runtime_yaml.write_text(yaml.dump(rt_dict, allow_unicode=True, sort_keys=False), encoding="utf-8")
                    runtime_updated = True
        except Exception as e:
            print(f"[ERROR] Failed to inject runtime clash-verge.yaml: {e}")

        return {
            "success": True,
            "message": f"成功保存 {len(rules)} 条分流规则！" + (" (已即刻同步写入当前运行时)" if runtime_updated else ""),
            "rules_file": str(rules_file),
            "total_rules": len(rules),
            "hint": "规则已同步写入当前运行态！若客户端连接未切换，请在 Clash Verge 中右键点击当前订阅选择【使用】以重载内核！"
        }

    PROTECTED_GROUPS = ("节点选择", "Google 专线", "Claude 专线", "搭载")

    def handle_delete_group(self, data):
        """从订阅的分组覆写文件里删掉一个分组（先备份），并同步清掉运行态里的该分组及对它的引用"""
        uid = data.get("uid")
        name = (data.get("group_name") or "").strip()
        if not uid or not name:
            return {"success": False, "error": "缺少订阅或分组名称"}
        if name in self.PROTECTED_GROUPS:
            return {"success": False, "error": f"「{name}」是核心分组，不能删除"}
        target = next((i for i in parse_yaml_profiles()["items"] if i["uid"] == uid), None)
        if not target:
            return {"success": False, "error": "未找到指定的订阅配置"}
        groups_uid = target.get("groups")
        groups_file = VERGE_PROFILES_DIR / f"{groups_uid}.yaml" if groups_uid else None
        set_custom_group(name, False)

        def strip(groups):
            out = []
            for g in groups or []:
                if not isinstance(g, dict) or g.get("name") == name:
                    continue
                if isinstance(g.get("proxies"), list):
                    g["proxies"] = [p for p in g["proxies"] if p != name]
                out.append(g)
            return out

        if groups_file and groups_file.exists():
            shutil.copy2(groups_file, BACKUP_DIR / f"{groups_uid}_{datetime.now():%Y%m%d_%H%M%S}.yaml")
            gdata = yaml.safe_load(groups_file.read_text(encoding="utf-8")) or {}
            gdata["prepend"] = strip(gdata.get("prepend"))
            gdata["append"] = strip(gdata.get("append"))
            dels = [d for d in (gdata.get("delete") or []) if d != name]
            gdata["delete"] = dels + [name]          # 订阅自带的同名分组也一并去掉
            body = yaml.safe_dump({k: gdata.get(k, []) for k in ("prepend", "append", "delete")},
                                  allow_unicode=True, sort_keys=False, default_flow_style=False)
            groups_file.write_text("# Profile Enhancement Groups Template for Clash Verge" + chr(10) + body, encoding="utf-8")

        try:
            su = target.get("script")
            if not su:
                su = ensure_profile_ext(uid, "script", "script", "js")
            ensure_cleanup_script(VERGE_PROFILES_DIR / f"{su}.js")
        except Exception as e:
            print(f"[WARN] 清理脚本写入失败: {e}")

        rt_file = VERGE_APP_DIR / "clash-verge.yaml"
        if rt_file.exists() and target.get("is_current"):
            try:
                rt = yaml.safe_load(rt_file.read_text(encoding="utf-8", errors="ignore")) or {}
                rt["proxy-groups"] = strip(rt.get("proxy-groups"))
                rt_file.write_text(yaml.safe_dump(rt, allow_unicode=True, sort_keys=False), encoding="utf-8")
            except Exception as e:
                print(f"[WARN] 同步运行态失败: {e}")
        return {"success": True}

    def handle_save_group(self, data):
        """保存并生成分组与增强配置"""
        uid = data.get("uid")
        group_name = data.get("group_name", "").strip()
        group_type = data.get("group_type", "select")
        selected_nodes = data.get("selected_nodes", [])
        mount_to_selector = data.get("mount_to_selector", True)
        clean_info_cards = data.get("clean_info_cards", True)
        link_media_groups = data.get("link_media_groups", True)

        if not uid or not group_name or not selected_nodes:
            return {"success": False, "error": "缺少必要参数（订阅UID、分组名称或所选节点）"}

        profiles_info = parse_yaml_profiles()
        target = next((item for item in profiles_info["items"] if item["uid"] == uid), None)
        if not target:
            return {"success": False, "error": "未找到指定的订阅配置"}

        # 确定 groups 文件
        groups_uid = target.get("groups")
        if not groups_uid:
            # 自动生成一个 groups uid 并绑定
            groups_uid = f"groups_{uid[:8]}"
            self.bind_profile_option(uid, "groups", groups_uid)
        
        groups_file = VERGE_PROFILES_DIR / f"{groups_uid}.yaml"
        
        # 1. 备份原文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if groups_file.exists():
            shutil.copy2(groups_file, BACKUP_DIR / f"{groups_uid}_{timestamp}.yaml")
            shutil.copy2(groups_file, VERGE_PROFILES_DIR / f"{groups_uid}.yaml.bak-{timestamp}")

        # 2. 用 YAML 读写分组文件：只替换正在保存的这一组，其他组（搭载等）原样保留
        ext_doc = _load_ext(groups_file)
        old_groups = [g for g in (ext_doc.get("prepend") or []) if isinstance(g, dict)]
        old = next((g for g in old_groups if g.get("name") == group_name), None)
        # 搭载组排第一的节点是默认搭载，保存勾选时不能把它换掉
        if group_name == CARRIER_GROUP and old and old.get("proxies") and old["proxies"][0] in selected_nodes:
            selected_nodes = [old["proxies"][0]] + [n for n in selected_nodes if n != old["proxies"][0]]
        new_group = dict(old or {}, name=group_name, type=group_type, proxies=list(selected_nodes))
        if old:
            ext_doc["prepend"] = [new_group if g is old else g for g in old_groups]
        else:
            ext_doc["prepend"] = [new_group] + old_groups
        ext_doc.setdefault("append", [])
        dele = [x for x in (ext_doc.get("delete") or []) if x != group_name] + [group_name]
        ext_doc["delete"] = dele
        groups_file.write_text(_yaml_dump(ext_doc), encoding="utf-8")
        set_custom_group(group_name, True)

        # 4. 同步更新/检查扩展脚本（支持净化与港台/Steam联动）
        script_uid = target.get("script")
        if not script_uid:
            script_uid = f"script_{uid[:8]}"
            self.bind_profile_option(uid, "script", script_uid)

        script_file = VERGE_PROFILES_DIR / f"{script_uid}.js"
        if script_file.exists():
            shutil.copy2(script_file, BACKUP_DIR / f"{script_uid}_{timestamp}.js")

        cur_script = script_file.read_text(encoding="utf-8", errors="ignore") if script_file.exists() else ""
        if "targetNode" not in cur_script and "dialer-proxy" not in cur_script:
            script_code = self.generate_script_code(clean_info_cards, link_media_groups)
            script_file.write_text(script_code, encoding="utf-8")

        # 4.5 同步更新/确保 rules 规则覆写中包含置顶 AI 规则
        rules_uid = target.get("rules")
        if not rules_uid:
            rules_uid = f"rules_{uid[:8]}"
            self.bind_profile_option(uid, "rules", rules_uid)
        rules_file = VERGE_PROFILES_DIR / f"{rules_uid}.yaml"

        # 5. 同步备份到工作区
        USER_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(groups_file, USER_WORKSPACE_DIR / f"{groups_uid}.yaml")
        shutil.copy2(script_file, USER_WORKSPACE_DIR / f"{script_uid}.js")

        # 6. 深度同步运行态：直接把新策略组结构写入当前运行态 clash-verge.yaml
        try:
            runtime_yaml = VERGE_APP_DIR / "clash-verge.yaml"
            if runtime_yaml.exists():
                rt_dict = yaml.safe_load(runtime_yaml.read_text(encoding="utf-8", errors="ignore"))
                if rt_dict and isinstance(rt_dict, dict) and "proxy-groups" in rt_dict:
                    groups_list = rt_dict["proxy-groups"]
                    target_g = next((g for g in groups_list if g.get("name") == group_name), None)
                    if target_g:
                        target_g["proxies"] = selected_nodes[:]
                    else:
                        groups_list.append({
                            "name": group_name,
                            "type": group_type,
                            "proxies": selected_nodes[:]
                        })
                    runtime_yaml.write_text(yaml.dump(rt_dict, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:
            print(f"[WARN] Failed to sync runtime clash-verge.yaml: {e}")

        # 7. 自动打开 / 唤起 Clash Verge 客户端窗口！
        launch_clash_verge()

        return {
            "success": True,
            "message": f"成功创建并注入分组【{group_name}】（共 {len(selected_nodes)} 个精选节点）",
            "groups_file": str(groups_file),
            "script_file": str(script_file),
            "total_nodes": len(selected_nodes)
        }

    def generate_script_code(self, clean_info_cards, link_media_groups):
        tpl = """// Define main function (script entry)
// Generated by Antigravity VIP Rules Manager at __DATETIME__

function main(config, profileName) {
  if (config && Array.isArray(config['proxy-groups'])) {
    for (var i = 0; i < config['proxy-groups'].length; i++) {
      var group = config['proxy-groups'][i];
      if (!group || !Array.isArray(group.proxies)) continue;

      // 1. 全局彻底净化：从所有分组中剔除提示型假节点（流量、到期、网络重启等）
      if (__CLEAN_INFO__) {
        group.proxies = group.proxies.filter(function (p) {
          return !/(流量|到期|重置|官网|群组|重启网络|超时)/.test(p);
        });
      }

      // 2. 智能总控联动：将订阅主组（与订阅同名组）及业务组首位接入「节点选择」
      if (__LINK_MEDIA__) {
        var isTargetGroup = (
          group.name === profileName ||
          group.name.indexOf(profileName) !== -1 ||
          group.name === '港台番剧' ||
          group.name === '蒸汽平台' ||
          group.name === '国际媒体' ||
          group.name === '电报代理'
        );
        if (isTargetGroup) {
          var exists = false;
          for (var j = 0; j < group.proxies.length; j++) {
            if (group.proxies[j] === '节点选择') {
              exists = true;
              break;
            }
          }
          if (!exists) {
            group.proxies.unshift('节点选择');
          }
        }
      }
    }
  }
  return config;
}
"""
        return tpl.replace("__DATETIME__", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))\
                  .replace("__LINK_MEDIA__", str(link_media_groups).lower())\
                  .replace("__CLEAN_INFO__", str(clean_info_cards).lower())

    def bind_profile_option(self, profile_uid, option_key, option_val):
        """在 profiles.yaml 中为当前订阅绑定字段"""
        if not VERGE_PROFILES_YAML.exists():
            return
        content = VERGE_PROFILES_YAML.read_text(encoding="utf-8")
        # 简单替换或追加
        pattern = rf"(uid:\s*{re.escape(profile_uid)}[\s\S]*?option:\s*\r?\n(?:[ \t]+[^\r\n]+\r?\n)*)"
        m = re.search(pattern, content)
        if m:
            block = m.group(1)
            if f"{option_key}:" in block:
                new_block = re.sub(rf"({option_key}:\s*)[^\r\n]+", rf"\g<1>{option_val}", block)
            else:
                new_block = block.rstrip() + f"\n    {option_key}: {option_val}\n"
            content = content.replace(block, new_block)
            VERGE_PROFILES_YAML.write_text(content, encoding="utf-8")

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

def run():
    import traceback
    try:
        HTTPServer.allow_reuse_address = True
        print(f"[Clash Verge VIP Manager] 服务启动中...")
        print(f"[Listening] http://127.0.0.1:{PORT}")
        ensure_global_script()
        server = ThreadingHTTPServer(("127.0.0.1", PORT), VergeAPIHandler)
        while True:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\n手动关闭。")
                break
            except Exception as e:
                with open(BASE_DIR / "server.log", "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now()}] Request error: {e}\n{traceback.format_exc()}\n")
                continue
    except Exception as e:
        with open(BASE_DIR / "server_crash.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] Server startup crash: {e}\n{traceback.format_exc()}\n")

if __name__ == "__main__":
    run()