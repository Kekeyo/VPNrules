/* 页面更新提示 —— 改了前端文件，页面自己弹出“有更新，点这里刷新”，不用手动按 Ctrl+F5。
 *
 * 用法：把这段放进页面（内联或作为 js 引入）。后端需要提供一个返回“静态文件版本号”的接口
 *      （见同目录 page-version.py），地址默认 /api/page-version。
 * 可调：
 *   window.PAGE_VERSION_API  —— 接口地址，默认 '/api/page-version'
 *   window.PAGE_VERSION_MS   —— 轮询间隔，默认 5000 毫秒
 *   window.PAGE_VERSION_TEXT —— 提示文字，默认 '页面有更新，点这里刷新'
 */
(function () {
  var API = window.PAGE_VERSION_API || '/api/page-version';
  var MS = window.PAGE_VERSION_MS || 5000;
  var TEXT = window.PAGE_VERSION_TEXT || '页面有更新，点这里刷新';
  var cur = '';

  function tip() {
    if (document.getElementById('pageUpd')) return;
    var d = document.createElement('div');
    d.id = 'pageUpd';
    d.textContent = TEXT;
    d.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:2147483647;'
      + 'background:#111827;color:#fff;padding:9px 18px;border-radius:20px;cursor:pointer;'
      + 'font:14px/1.4 system-ui,"Microsoft YaHei",sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.45)';
    d.onclick = function () {
      // 先问一句：刷新会丢掉没保存的东西
      if (confirm('重新载入页面，没保存的改动会丢。确定刷新？')) location.reload();
    };
    document.body.appendChild(d);
  }

  function check() {
    if (document.hidden) return;                 // 页面在后台时不查，不浪费
    fetch(API, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var v = j && (j.v || j.version);
        if (!v) return;
        if (!cur) { cur = v; return; }           // 第一次：只记住，不提示
        if (v !== cur) tip();
      })
      .catch(function () {});                    // 没这个接口就安静地什么也不做
  }

  setTimeout(check, 1200);
  setInterval(check, MS);
})();
