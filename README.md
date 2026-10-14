# Clash Verge VIP 节点编排与总控管理控制台 (VPNrules)

<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows)
![Clash Verge](https://img.shields.io/badge/Clash%20Verge-Rev-06b6d4?logo=ghost)
![License](https://img.shields.io/badge/License-MIT-green)

**告别手动手写 YAML 报错噩梦，用高颜值现代化 Web 界面，直观编排专属 VIP 节点池与一键接管总出口！**

</div>

---

## 🌟 核心特性与亮点

- 🚀 **零依赖轻量架构**：基于纯原生 Python 3 内置库，无需执行 `pip install` 任何第三方包，双击即开；
- 🎨 **深色 / 浅色双主题（Dark & Light Mode）**：
  - 🌙 **暗夜深蓝极客模式**：毛玻璃质感卡片、霓虹蓝荧光高亮，夜间沉浸护眼；
  - ☀️ **苹果风极简明亮模式**：纯净立体卡片、柔和阴影，日间清爽通透；
  - 支持一键平滑秒切，并基于 `localStorage` 自动持久化记忆；
- 📁 **已有 VIP 分组一键回显与增删（Lifecycle Management）**：
  - 自动识别当前订阅已有的自定义 VIP 组；
  - 鼠标点击即可瞬间载入原有节点勾选，随时点掉失效节点、勾选新节点，同名无缝覆盖更新并附带完整时间戳备份；
- 🏷️ **多维智能过滤大厅**：
  - 国旗与地区一键筛选（🇯🇵 日本、🇸🇬 新加坡、🇺🇸 美国、🇭🇰 香港、🇹🇼 台湾、🇰🇷 韩国等）；
  - 专线/协议标签（IEPL、原生IP、家宽、直连）与实时关键词模糊检索；
- 🎯 **一键总控与业务联动**：
  - 自动生成 `groups` 覆写并置顶挂入 `节点选择`（开启全量聚合 `include-all: true`）；
  - 自动前置同步 Gemini、Claude、ChatGPT、Antigravity 等全套 60+ AI 核心规则；
  - 自动将订阅同名主组、港台番剧、Steam 社区接入总控；
- 🧹 **全部分组彻底净化**：
  - 自动剔除“剩余流量”、“套餐到期”、“重启网络”等非代理提示卡片，彻底避免测速误选垃圾节点；
- 🛡️ **双重快照安全备份**：
  - 每次保存均自动在本地 `backup/` 及配置目录生成带精确时间戳的快照备份，安全无忧。

---

## 🚀 极简使用方式 (3 步上手)

1. **双击启动**：
   直接双击运行工程根目录下的 **`启动控制台.bat`**；
2. **浏览器点选**：
   系统会自动在浏览器打开 `http://127.0.0.1:8899`：
   - 顶部选择当前订阅；
   - 点击地区标签（如 `🇯🇵 日本`）快速筛选出所有日本节点；
   - 在心仪的优质节点上打勾，或点击已有分组回显增删；
   - 输入您自定义的分组名字（如 `我的日本VIP专线`）；
   - 点击 **「🚀 一键生成并写入 Clash Verge」**；
3. **客户端刷新生效**：
   回到 Clash Verge 客户端，在左侧 **「订阅」** 页面右键当前订阅卡片，点击 **「重新加载」** 即可！

---

## 📂 项目结构

```
VPNrules/
├── 启动控制台.bat      # 🚀 Windows 一键启动批处理脚本 (自动调起浏览器)
├── server.py           # ⚙️ 本地 Python 轻量 API 服务 (零外部依赖)
├── web/
│   └── index.html      # 🎨 现代化科技风单页 Web 控制台 (支持深浅双色模式)
├── .gitignore          # 🛡️ 严格过滤用户本地备份与配置隐私
└── README.md           # 📖 项目说明文档
```

---

## 📄 License

本项目基于 [MIT License](LICENSE) 开源发布。
