#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clash Verge 节点编排与 VIP 分组可视化管理服务
"""

import os
import sys
import json
import re
import shutil
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# Windows 控制台标准输出 UTF-8 兼容性加固
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PORT = 8899
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
BACKUP_DIR = BASE_DIR / "backup"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR.mkdir(parents=True, exist_ok=True)

# 默认 Clash Verge 配置路径
VERGE_PROFILES_DIR = Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev" / "profiles"
VERGE_PROFILES_YAML = Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev" / "profiles.yaml"
USER_WORKSPACE_DIR = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "ChatGPT" / "clash&verge"

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
    """解析 profiles.yaml"""
    if not VERGE_PROFILES_YAML.exists():
        return {"current": "", "items": []}
    content = VERGE_PROFILES_YAML.read_text(encoding="utf-8")
    
    current_match = re.search(r"current:\s*([^\r\n]+)", content)
    current_uid = current_match.group(1).strip() if current_match else ""
    
    # 拆分每个 item
    items = []
    item_blocks = re.split(r"\n-\s+uid:\s*", content)
    for block in item_blocks[1:]:
        lines = block.strip().splitlines()
        uid = lines[0].strip()
        data = {"uid": uid}
        for l in lines[1:]:
            m = re.match(r"^\s*([a-zA-Z0-9_-]+):\s*(.*)$", l)
            if m:
                k, v = m.group(1).strip(), m.group(2).strip()
                data[k] = v
        # 只保留 remote 订阅或 local 配置
        if data.get("type") in ["remote", "local"]:
            items.append({
                "uid": uid,
                "name": data.get("name", uid),
                "type": data.get("type", "remote"),
                "file": data.get("file", f"{uid}.yaml"),
                "is_current": (uid == current_uid),
                "groups": data.get("groups", ""),
                "rules": data.get("rules", ""),
                "script": data.get("script", "")
            })
    return {"current": current_uid, "items": items}

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

def get_current_groups_override(groups_file_name: str):
    """读取当前的分组覆写文件，分析已有自定义分组及其包含的节点列表"""
    file_path = VERGE_PROFILES_DIR / groups_file_name
    if not file_path.exists():
        return {"custom_groups": []}
    
    try:
        content = file_path.read_text(encoding="utf-8")
        custom_groups = []
        block_matches = re.finditer(r"-\s+name:\s*(['\"]?)(.*?)\1\s*\r?\n\s+type:\s*(\w+)\s*\r?\n\s+proxies:\s*\r?\n((?:\s+-\s+.*?\r?\n)*)", content)
        for bm in block_matches:
            g_name = bm.group(2).strip()
            g_type = bm.group(3).strip()
            p_block = bm.group(4)
            p_list = [re.sub(r"^\s*-\s*['\"]?(.*?)['\"]?\s*$", r"\1", l) for l in p_block.splitlines() if l.strip().startswith("-")]
            if g_name != "节点选择":
                custom_groups.append({
                    "name": g_name,
                    "type": g_type,
                    "proxies": p_list,
                    "count": len(p_list)
                })
        return {"custom_groups": custom_groups}
    except Exception:
        return {"custom_groups": []}

class VergeAPIHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
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
            override_info = {}
            if target.get("groups"):
                override_info = get_current_groups_override(f"{target['groups']}.yaml")

            self.send_json({
                "profile": target,
                "nodes": nodes,
                "total_nodes": len(nodes),
                "override": override_info
            })
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

            self.send_json({
                "profile": target,
                "rules_uid": rules_uid,
                "rules": rules_list,
                "total": len(rules_list)
            })
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
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/save-group":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            result = self.handle_save_group(data)
            self.send_json(result)
            return

        if parsed.path == "/api/save-rules":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            result = self.handle_save_rules(data)
            self.send_json(result)
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
            raw = r if isinstance(r, str) else r.get("raw")
            if not raw and isinstance(r, dict):
                raw = f"{r.get('type')},{r.get('payload')},{r.get('target', '节点选择')}"
            if raw:
                escaped = raw.replace("'", "''")
                yaml_lines.append(f"  - '{escaped}'")

        yaml_lines.extend(["", "append: []", ""])
        content = "\n".join(yaml_lines)
        rules_file.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "message": f"成功保存 {len(rules)} 条分流规则！",
            "rules_file": str(rules_file),
            "total_rules": len(rules)
        }

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

        # 2. 读取原 groups 中可能存在的其他已有组
        existing_groups = []
        if groups_file.exists():
            try:
                old_content = groups_file.read_text(encoding="utf-8")
                # 正则解析已有的非「节点选择」组
                block_matches = re.finditer(r"-\s+name:\s*(['\"]?)(.*?)\1\s*\r?\n\s+type:\s*(\w+)\s*\r?\n\s+proxies:\s*\r?\n((?:\s+-\s+.*?\r?\n)*)", old_content)
                for bm in block_matches:
                    g_name = bm.group(2).strip()
                    g_type = bm.group(3).strip()
                    p_block = bm.group(4)
                    p_list = [re.sub(r"^\s*-\s*['\"]?(.*?)['\"]?\s*$", r"\1", l) for l in p_block.splitlines() if l.strip().startswith("-")]
                    if g_name not in ["节点选择", group_name]:
                        existing_groups.append({
                            "name": g_name,
                            "type": g_type,
                            "proxies": p_list
                        })
            except Exception as e:
                pass

        # 3. 构造新的 YAML 内容
        yaml_lines = [
            "# Profile Enhancement Groups Template for Clash Verge",
            f"# Generated by Antigravity VIP Rules Manager at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "prepend:"
        ]

        # 挂载「节点选择」总控台
        if mount_to_selector:
            selector_proxies = [group_name, "自动选择"]
            for eg in existing_groups:
                if eg["name"] not in selector_proxies:
                    selector_proxies.append(eg["name"])

            yaml_lines.extend([
                "  - name: 节点选择",
                "    type: select",
                "    include-all: true",
                "    proxies:"
            ])
            for sp in selector_proxies:
                yaml_lines.append(f"      - {sp}")

        # 挂载新创建的 VIP 分组
        yaml_lines.extend([
            f"  - name: {group_name}",
            f"    type: {group_type}",
            "    proxies:"
        ])
        for node in selected_nodes:
            # 安全转义单引号
            safe_node = node.replace("'", "''")
            yaml_lines.append(f"      - '{safe_node}'")

        # 保留原有的其他自定义组
        for eg in existing_groups:
            yaml_lines.extend([
                f"  - name: {eg['name']}",
                f"    type: {eg['type']}",
                "    proxies:"
            ])
            for p in eg["proxies"]:
                safe_p = p.replace("'", "''")
                yaml_lines.append(f"      - '{safe_p}'")

        yaml_lines.extend([
            "",
            "append: []",
            "",
            "delete:",
            "  - 节点选择",
            f"  - {group_name}"
        ])
        for eg in existing_groups:
            yaml_lines.append(f"  - {eg['name']}")
        yaml_lines.append("")

        new_yaml_text = "\n".join(yaml_lines)
        groups_file.write_text(new_yaml_text, encoding="utf-8")

        # 4. 同步更新/检查扩展脚本（支持净化与港台/Steam联动）
        script_uid = target.get("script")
        if not script_uid:
            script_uid = f"script_{uid[:8]}"
            self.bind_profile_option(uid, "script", script_uid)
        
        script_file = VERGE_PROFILES_DIR / f"{script_uid}.js"
        if script_file.exists():
            shutil.copy2(script_file, BACKUP_DIR / f"{script_uid}_{timestamp}.js")

        script_code = self.generate_script_code(clean_info_cards, link_media_groups)
        script_file.write_text(script_code, encoding="utf-8")

        # 4.5 同步更新/确保 rules 规则覆写中包含置顶 AI 规则
        rules_uid = target.get("rules")
        if not rules_uid:
            rules_uid = f"rules_{uid[:8]}"
            self.bind_profile_option(uid, "rules", rules_uid)
        rules_file = VERGE_PROFILES_DIR / f"{rules_uid}.yaml"
        base_rules_file = VERGE_PROFILES_DIR / "rMgsu6Wt88KH.yaml"
        if base_rules_file.exists():
            if not rules_file.exists() or len(rules_file.read_text(encoding="utf-8", errors="ignore").strip()) < 100:
                shutil.copy2(base_rules_file, rules_file)
                USER_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(base_rules_file, USER_WORKSPACE_DIR / f"{rules_uid}.yaml")

        # 5. 同步备份到工作区
        USER_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(groups_file, USER_WORKSPACE_DIR / f"{groups_uid}.yaml")
        shutil.copy2(script_file, USER_WORKSPACE_DIR / f"{script_uid}.js")

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
    print(f"[Clash Verge VIP Manager] 服务启动中...")
    print(f"[Listening] http://127.0.0.1:{PORT}")
    server = HTTPServer(("127.0.0.1", PORT), VergeAPIHandler)
    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n服务已手动关闭。")
            break
        except Exception as e:
            # 忽略浏览器断开等异常，继续监听
            continue

if __name__ == "__main__":
    run()
