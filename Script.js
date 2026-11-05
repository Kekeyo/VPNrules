// Clash Verge 四大分类黄金架构扩展脚本
// Master Template: Google 专线 + Claude 专线 + 节点选择 + 国内直连 (DIRECT)

function main(config, profileName) {
  if (!config) return config;

  // 1. 提取所有可用物理代理节点
  var allProxies = [];
  if (Array.isArray(config.proxies)) {
    allProxies = config.proxies.map(function (p) { return p.name; }).filter(Boolean);
  }
  // 过滤无效/通知类节点
  var validProxies = allProxies.filter(function (p) {
    return !/(剩余|套餐|到期|官网|建议|群|重置|超时|请重启|维护)/.test(p);
  });
  if (validProxies.length === 0) {
    validProxies = allProxies.slice();
  }

  // 2. 筛选纯日台超低延迟节点池 (Google 专线)
  var jpTwProxies = validProxies.filter(function (p) {
    return /(日本|JP|Japan|东京|大阪|软银|樱花|台湾|TW|Taiwan|台北|新北)/i.test(p);
  });
  if (jpTwProxies.length === 0) {
    jpTwProxies = validProxies.slice();
  }

  // 3. 筛选韩国SK家宽 + 美西专线节点池 (Claude 专线)
  var krUsProxies = validProxies.filter(function (p) {
    return /(韩国|KR|Korea|首尔|SK|家宽|美国|US|United States|美·|美西|洛杉矶|硅谷|波特兰|盐湖城|凤凰城)/i.test(p);
  });
  if (krUsProxies.length === 0) {
    krUsProxies = validProxies.slice();
  }

  // 4. 重构/注入四大核心代理组 (保持无环拓扑 DAG)
  if (!Array.isArray(config['proxy-groups'])) {
    config['proxy-groups'] = [];
  }

  // 4.1 确保「节点选择」总控台存在且只包含物理节点 (杜绝 loop detected)
  var hasNodeSelect = false;
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    var g = config['proxy-groups'][i];
    if (g && g.name === '节点选择') {
      hasNodeSelect = true;
      // 清除可能导致循环引用的专线组
      if (Array.isArray(g.proxies)) {
        g.proxies = g.proxies.filter(function(name) {
          return name !== 'Google 专线' && name !== 'Claude 专线';
        });
      }
      break;
    }
  }
  if (!hasNodeSelect) {
    config['proxy-groups'].unshift({
      name: '节点选择',
      type: 'select',
      proxies: validProxies.slice()
    });
  }

  // 分组覆写里已经选好节点就用选好的（网页“写入”的结果），否则用默认节点池
  function chosenOrPool(name, pool) {
    for (var k = 0; k < config['proxy-groups'].length; k++) {
      var eg = config['proxy-groups'][k];
      if (eg && eg.name === name && Array.isArray(eg.proxies)) {
        var real = eg.proxies.filter(function (n) { return validProxies.indexOf(n) !== -1; });
        if (real.length) return real;
      }
    }
    return pool.slice();
  }

  // 4.2 构建 Google 专线 (日台极速，内嵌 节点选择 与 DIRECT)
  var googleGroupProxies = chosenOrPool('Google 专线', jpTwProxies);
  if (googleGroupProxies.indexOf('节点选择') === -1) googleGroupProxies.push('节点选择');
  if (googleGroupProxies.indexOf('DIRECT') === -1) googleGroupProxies.push('DIRECT');

  var googleGroupIdx = -1;
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    if (config['proxy-groups'][i].name === 'Google 专线') {
      googleGroupIdx = i;
      break;
    }
  }
  var googleGroupObj = {
    name: 'Google 专线',
    type: 'select',
    proxies: googleGroupProxies
  };
  if (googleGroupIdx >= 0) {
    config['proxy-groups'][googleGroupIdx] = googleGroupObj;
  } else {
    config['proxy-groups'].splice(1, 0, googleGroupObj);
  }

  // 4.3 构建 Claude 专线 (韩国AI/美西，内嵌 节点选择 与 DIRECT)
  var cloudGroupProxies = chosenOrPool('Claude 专线', krUsProxies);
  if (cloudGroupProxies.indexOf('节点选择') === -1) cloudGroupProxies.push('节点选择');
  if (cloudGroupProxies.indexOf('DIRECT') === -1) cloudGroupProxies.push('DIRECT');

  var cloudGroupIdx = -1;
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    if (config['proxy-groups'][i].name === 'Claude 专线') {
      cloudGroupIdx = i;
      break;
    }
  }
  var cloudGroupObj = {
    name: 'Claude 专线',
    type: 'select',
    proxies: cloudGroupProxies
  };
  if (cloudGroupIdx >= 0) {
    config['proxy-groups'][cloudGroupIdx] = cloudGroupObj;
  } else {
    config['proxy-groups'].splice(2, 0, cloudGroupObj);
  }

  // 4.4 「搭载」组：放订阅里全部机场节点；带 dialer-proxy 的住宅节点要去掉，否则住宅节点借自己搭载会成环
  var resNames = (Array.isArray(config.proxies) ? config.proxies : [])
    .filter(function (p) { return p && p['dialer-proxy']; })
    .map(function (p) { return p.name; });
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    var cg = config['proxy-groups'][i];
    if (cg && cg.name === '搭载') {
      // 排第一的是网页上选的搭载节点，要保持在第一位（没切换过时默认选它）
      var firstCarrier = Array.isArray(cg.proxies) ? cg.proxies[0] : null;
      cg.proxies = validProxies.filter(function (n) { return resNames.indexOf(n) === -1; });
      if (firstCarrier && cg.proxies.indexOf(firstCarrier) > 0) {
        cg.proxies.splice(cg.proxies.indexOf(firstCarrier), 1);
        cg.proxies.unshift(firstCarrier);
      }
    }
  }
  // 4.5 只留核心分组。Verge 的顺序是：分组覆写 -> 全局脚本 -> 订阅脚本，所以这里能看到覆写里的分组。
  //     订阅自带的分组都去掉，指向它们的规则改走「节点选择」；网页上新建的分组记在下面这行（服务端维护）
  var customGroups = []; // custom-groups
  var coreGroups = ['节点选择', 'Google 专线', 'Claude 专线', '搭载'].concat(customGroups);
  var removedGroups = {};
  config['proxy-groups'] = config['proxy-groups'].filter(function (g) {
    if (g && coreGroups.indexOf(g.name) !== -1) return true;
    if (g && g.name) removedGroups[g.name] = 1;
    return false;
  });
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    var ng = config['proxy-groups'][i];
    if (ng.name === '节点选择') {
      ng.type = 'select';
      var realNodes = (ng.proxies || []).filter(function (n) { return validProxies.indexOf(n) !== -1; });
      ng.proxies = realNodes.length ? realNodes : validProxies.slice();
    }
  }
  if (Array.isArray(config.rules)) {
    config.rules = config.rules.map(function (r) {
      if (typeof r !== 'string') return r;
      var a = r.split(',');
      var at = a[0] === 'MATCH' ? 1 : 2;
      if (a.length > at && removedGroups[a[at].trim()]) a[at] = '节点选择';
      return a.join(',');
    });
  }

  // 5. 注入前置分流黄金规则 (置顶最高优先级)
  var masterGoldenRules = [
    // 1. Google 全生态与 Gemini 核心 (锁定: Google 专线)
    'DOMAIN,gemini.google.com,Google 专线',
    'DOMAIN,aistudio.google.com,Google 专线',
    'DOMAIN,generativelanguage.googleapis.com,Google 专线',
    'DOMAIN,ai.google.dev,Google 专线',
    'DOMAIN,bard.google.com,Google 专线',
    'DOMAIN-SUFFIX,antigravity.google,Google 专线',
    'DOMAIN-SUFFIX,antigravity-unleash.goog,Google 专线',
    'DOMAIN-SUFFIX,google.com,Google 专线',
    'DOMAIN-SUFFIX,googleapis.com,Google 专线',
    'DOMAIN-SUFFIX,google.dev,Google 专线',
    'DOMAIN-SUFFIX,googleusercontent.com,Google 专线',
    'DOMAIN-SUFFIX,gstatic.com,Google 专线',
    'DOMAIN-SUFFIX,google.ai,Google 专线',
    'DOMAIN-SUFFIX,g.co,Google 专线',
    'DOMAIN-SUFFIX,youtube.com,Google 专线',
    'DOMAIN-SUFFIX,ytimg.com,Google 专线',
    'DOMAIN-SUFFIX,ggpht.com,Google 专线',

    // 2. 海外顶级 AI 大类 (锁定: Claude 专线)
    'DOMAIN-SUFFIX,anthropic.com,Claude 专线',
    'DOMAIN-SUFFIX,claude.ai,Claude 专线',
    'DOMAIN-KEYWORD,anthropic,Claude 专线',
    'DOMAIN-KEYWORD,claude,Claude 专线',
    'DOMAIN-SUFFIX,openai.com,Claude 专线',
    'DOMAIN-SUFFIX,chatgpt.com,Claude 专线',
    'DOMAIN-SUFFIX,oaistatic.com,Claude 专线',
    'DOMAIN-SUFFIX,oaiusercontent.com,Claude 专线',
    'DOMAIN-KEYWORD,openai,Claude 专线',
    'DOMAIN-SUFFIX,muse.ai,Claude 专线',

    // 3. 国内核心大模型与常见直连 (锁定: DIRECT)
    'DOMAIN-SUFFIX,deepseek.com,DIRECT',
    'DOMAIN-SUFFIX,doubao.com,DIRECT',
    'DOMAIN-SUFFIX,volces.com,DIRECT',
    'DOMAIN-SUFFIX,moonshot.cn,DIRECT',
    'DOMAIN-SUFFIX,kimi.ai,DIRECT',
    'DOMAIN-SUFFIX,baichuan-ai.com,DIRECT',
    'DOMAIN-SUFFIX,chatglm.cn,DIRECT',
    'DOMAIN-SUFFIX,minimax.chat,DIRECT',
    'DOMAIN-SUFFIX,baidu.com,DIRECT',
    'DOMAIN-SUFFIX,qq.com,DIRECT',
    'DOMAIN-SUFFIX,bilibili.com,DIRECT',
    'DOMAIN-SUFFIX,taobao.com,DIRECT',
    'DOMAIN-SUFFIX,jd.com,DIRECT',
    'DOMAIN-SUFFIX,163.com,DIRECT'
  ];

  if (!Array.isArray(config.rules)) {
    config.rules = [];
  }

  // 模板里指向本订阅没有的分组（如网页新建的分组、搭载）时改走「节点选择」，否则内核起不来
  var knownTargets = { DIRECT: 1, REJECT: 1, 'REJECT-DROP': 1, PASS: 1 };
  for (var i = 0; i < config['proxy-groups'].length; i++) {
    knownTargets[config['proxy-groups'][i].name] = 1;
  }
  masterGoldenRules = masterGoldenRules.map(function (r) {
    var a = r.split(',');
    if (a.length >= 3 && !knownTargets[a[2]]) a[2] = '节点选择';
    return a.join(',');
  });

  // 过滤掉老旧冲突规则后置顶合并
  var newRules = masterGoldenRules.slice();
  for (var r = 0; r < config.rules.length; r++) {
    var ruleStr = config.rules[r];
    if (newRules.indexOf(ruleStr) === -1) {
      newRules.push(ruleStr);
    }
  }
  config.rules = newRules;

  return config;
}
