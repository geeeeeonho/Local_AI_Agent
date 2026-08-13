// proxy-bootstrap.js  (PATCH_ANYTHINGLLM 이 생성 — 직접 수정하지 마세요)
//
// Node 18/20 의 내장 fetch 는 HTTP_PROXY 환경변수를 무시한다.
// (NODE_USE_ENV_PROXY 는 v22.21+/v24+ 전용)
// 설치된 undici 의 ProxyAgent 를 전역 디스패처로 꽂아 강제로 프록시를 태운다.
//
// 중요: NO_PROXY 를 반드시 존중해야 한다. AnythingLLM 의 Ollama 호출도 fetch 를
// 쓰기 때문에, 전부 프록시로 몰면 host.docker.internal 이 프록시 너머에서
// 해석되지 않아 모델 호출이 통째로 죽는다.
(function () {
  try {
    var proxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY ||
                process.env.https_proxy || process.env.http_proxy || '';
    if (!proxy) { return; }
    var bypass = (process.env.NO_PROXY || process.env.no_proxy || '')
      .split(',').map(function (x) { return x.trim().toLowerCase(); })
      .filter(function (x) { return x.length > 0; });

    var undici = null;
    var tried = ['undici',
                 '/app/server/node_modules/undici',
                 '/app/collector/node_modules/undici',
                 '/app/node_modules/undici'];
    for (var i = 0; i < tried.length; i++) {
      try { undici = require(tried[i]); if (undici && undici.ProxyAgent) break; }
      catch (e) { undici = null; }
    }
    if (!undici || !undici.ProxyAgent || !undici.Agent) {
      console.error('[proxy-bootstrap] undici 를 찾지 못했습니다 - fetch 는 직접 나갑니다');
      return;
    }

    var viaProxy = new undici.ProxyAgent(proxy);
    var direct = new undici.Agent();

    function isBypass(origin) {
      var host = '';
      try { host = new URL(origin).hostname.toLowerCase(); } catch (e) { return false; }
      if (host === 'localhost' || host === '127.0.0.1' || host === '::1') { return true; }
      for (var i = 0; i < bypass.length; i++) {
        var b = bypass[i];
        if (b === '*') { return true; }
        if (host === b) { return true; }
        if (b.charAt(0) === '.' && host.slice(-b.length) === b) { return true; }
        if (host.slice(-(b.length + 1)) === ('.' + b)) { return true; }
      }
      return false;
    }

    function pick(opts) {
      var origin = opts && opts.origin ? String(opts.origin) : '';
      return isBypass(origin) ? direct : viaProxy;
    }

    // Dispatcher 를 상속하지 않는다. undici 의 Dispatcher 는 ES class 라
    // ES5 방식으로 상속하면 "cannot be invoked without 'new'" 로 죽는다.
    // Node 내장 fetch 도 undici.setGlobalDispatcher 도 dispatch 함수만 확인한다.
    var router = {
      dispatch: function (opts, handler) {
        return pick(opts).dispatch(opts, handler);
      },
      close: function () {
        return Promise.all([viaProxy.close(), direct.close()]);
      },
      destroy: function (err) {
        return Promise.all([viaProxy.destroy(err), direct.destroy(err)]);
      }
    };
    // Node 내장 fetch 가 읽는 well-known 심볼. setGlobalDispatcher 도 이걸 세운다.
    globalThis[Symbol.for('undici.globalDispatcher.1')] = router;
    try { if (undici.setGlobalDispatcher) { undici.setGlobalDispatcher(router); } }
    catch (e) { /* 심볼 직접 설정으로 충분 */ }

    console.error('[proxy-bootstrap] fetch -> ' + proxy +
                  '  (bypass: ' + bypass.join(',') + ')');
  } catch (e) {
    try { console.error('[proxy-bootstrap] 실패: ' + (e && e.message)); } catch (e2) {}
  }
})();
