// Read-only page function. Pass this entire file as the function string to the
// host browser's supported evaluate API. Do not execute it as a Node program.
() => {
  const root = document.querySelector('#js_content');
  const visibleText = element => (element?.innerText || '').trim();
  if (!root || !visibleText(root)) {
    const pageText = visibleText(document.body).slice(0, 4000);
    const verification = /wappoc_appmsgcaptcha/.test(location.pathname) || /环境异常|完成验证|安全验证|验证码/.test(pageText);
    const unavailable = /该内容已被发布者删除|此内容因违规无法查看|内容已删除/.test(pageText);
    return {kind: 'browser', capture: {schema_version: 1,
      state: verification ? 'verification_required' : unavailable ? 'unavailable' : 'not_ready'}};
  }
  // Only copy identity parameters. Never export the page's session query string.
  const url = new URL(location.href);
  const identity = new URLSearchParams();
  for (const key of ['__biz', 'mid', 'idx', 'sn']) {
    if (url.searchParams.has(key)) identity.set(key, url.searchParams.get(key));
  }
  url.search = identity.toString();
  url.hash = '';
  const body = visibleText(root);
  const headings = Array.from(root.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .map(element => ({level: Number(element.tagName.slice(1)), text: visibleText(element)}))
    .filter(item => item.text);
  const images = Array.from(root.querySelectorAll('img')).map(element => ({
    alt: element.getAttribute('alt') || '',
    // A completed 1x1 lazy-loading placeholder is NOT a loaded article image.
    loaded: element.complete && element.naturalWidth > 1 && element.naturalHeight > 1
      && !/^data:/.test(element.currentSrc || element.getAttribute('src') || '')
  }));
  return {kind: 'browser', capture: {schema_version: 1, state: 'ready',
    source: url.href, title: visibleText(document.querySelector('#activity-name')),
    author: visibleText(document.querySelector('#js_author_name')),
    account: visibleText(document.querySelector('#js_name')),
    published_at: visibleText(document.querySelector('#publish_time')),
    body, headings, images,
    evidence: {container: '#js_content', body_utf16_length: body.length,
      end_marker_present: Boolean(document.querySelector('#js_content_end')),
      table_count: root.querySelectorAll('table').length}
  }};
}
