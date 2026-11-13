# thoughtly-newsletter

In-app reader for the "Thoughtly Notes" newsletter (formerly "Welcome to Thoughtly"), embedded in the Thoughtly branded Kajabi app.

- `scripts/scrape.py` pulls every issue from https://www.bethoughtly.com/newsletters/thoughtly-notes into `data/posts.json`.
- `.github/workflows/scrape.yml` runs it daily (6:17am AZ) and commits changes. Run it manually from the Actions tab, with "Re-fetch every issue" for a full refresh.
- `index.html` is the reader: list, search, and reading view on one page (hash routing, no navigation, so the app webview never kicks out to the browser).
- Hosted on GitHub Pages at `newsletter.bethoughtly.com` (see `CNAME`).

## Safety
The scraper aborts without writing if it finds no issues or fewer than 80% of what's on file, so a Kajabi layout change can't wipe the archive. A failed run shows up as a failed Action (GitHub emails you).

If Kajabi changes its post layout, update the three selectors at the top of `scrape.py`.

## App embed (Kajabi Branded App, Embed widget)

```html
<div style="position:relative;width:100%;height:calc(100vh - 130px);min-height:480px;overflow:hidden;background:#F8F7F4;border-radius:12px;">
  <div id="tly-nl-loader" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#F8F7F4;z-index:2;">
    <div style="text-align:center;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;">
      <p style="margin:0 0 10px;font-size:20px;color:#E9DAC1;background:transparent;">✦</p>
      <p style="margin:0;font-size:13px;color:rgba(61,64,60,0.40);background:transparent;">Loading…</p>
    </div>
  </div>
  <iframe
    id="tly-nl-frame"
    src="https://newsletter.bethoughtly.com/"
    title="Thoughtly Notes"
    style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;display:block;"
  ></iframe>
</div>
<script>
(function () {
  var frame  = document.getElementById('tly-nl-frame');
  var loader = document.getElementById('tly-nl-loader');
  if (!frame || !loader) return;
  frame.onload = function () { loader.style.display = 'none'; };
})();
</script>
```
