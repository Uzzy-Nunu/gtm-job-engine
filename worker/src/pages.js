// HTML for the paste-a-link form (/add) and the bookmarklet page (/bookmarklet).
// The access key is typed once and kept in the browser (localStorage); it is
// never part of a link or the bookmarklet. Prefill from the bookmarklet comes
// in the URL #fragment, which browsers never send to the server.

const STYLE = `
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#5b6472;--line:#d9dde3;--accent:#1f6feb;--accent-text:#fff;
--ok-bg:#e7f6ec;--ok:#116329;--warn-bg:#fff4e0;--warn:#8a5300;--err-bg:#fdecec;--err:#a40e26}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e8eaee;--muted:#a1a9b6;--line:#2c313b;
--accent:#4c8dff;--accent-text:#0b0d12;--ok-bg:#12301d;--ok:#7ee2a1;--warn-bg:#33270f;--warn:#f3c26b;--err-bg:#3a1418;--err:#ff9aa6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:560px;margin:0 auto;padding:20px 16px 40px}h1{font-size:1.35rem;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
label{display:block;font-weight:600;margin:14px 0 6px}label:first-child{margin-top:0}.hint{font-weight:400;color:var(--muted);font-size:.9rem}
input,textarea{width:100%;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
textarea{min-height:150px;resize:vertical}input:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
button{margin-top:18px;width:100%;padding:14px;border:0;border-radius:8px;background:var(--accent);color:var(--accent-text);font:inherit;font-weight:700;cursor:pointer}
button[disabled]{opacity:.6;cursor:wait}.link{background:none;color:var(--accent);padding:0;margin:8px 0 0;width:auto;font-weight:500}
.msg{margin-top:16px;padding:12px 14px;border-radius:8px;display:none}.msg.show{display:block}
.created,.updated{background:var(--ok-bg);color:var(--ok)}.duplicate{background:var(--warn-bg);color:var(--warn)}.error{background:var(--err-bg);color:var(--err)}
code{background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:1px 5px}a.bm{display:inline-block;padding:10px 16px;border-radius:8px;background:var(--accent);color:var(--accent-text);font-weight:700;text-decoration:none}
ol{padding-left:20px}li{margin:6px 0}.foot{margin-top:16px}`;

function page(title, body, nonce, script = "") {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>${title}</title><style nonce="${nonce}">${STYLE}</style></head><body><main>${body}</main>
${script ? `<script nonce="${nonce}">${script}</script>` : ""}</body></html>`;
}

export function addPage(nonce) {
  const body = `
<h1>Add a job</h1>
<p class="sub">Paste a LinkedIn hiring post or a job link. It goes straight into HubSpot's <strong>New</strong> column.</p>
<form class="card" id="f" autocomplete="off">
  <div id="keybox">
    <label for="key">Access key <span class="hint">(saved on this device)</span></label>
    <input id="key" type="password" autocomplete="current-password" required>
  </div>
  <label for="url">Post or job link</label>
  <input id="url" type="url" inputmode="url" placeholder="https://www.linkedin.com/posts/..." required>
  <label for="text">Post text <span class="hint">(recommended: copy and paste the post)</span></label>
  <textarea id="text" placeholder="We're hiring a GTM Engineer..."></textarea>
  <label for="notes">Notes <span class="hint">(optional, only for you)</span></label>
  <input id="notes" type="text" placeholder="e.g. referred by a friend">
  <button id="go" type="submit">Save to HubSpot</button>
  <button id="forget" class="link" type="button" hidden>Use a different access key</button>
  <div id="msg" class="msg" role="status" aria-live="polite"></div>
</form>
<p class="sub foot">On the LinkedIn app: tap <strong>…</strong> on the post, then <strong>Copy link to post</strong>. Short <code>lnkd.in</code> links won't work.</p>`;
  const script = `
const $=id=>document.getElementById(id);const KEY="gtmCaptureKey";
function store(k,v){try{v===null?localStorage.removeItem(k):localStorage.setItem(k,v)}catch(e){}}
function load(k){try{return localStorage.getItem(k)}catch(e){return null}}
function showKey(show){$("keybox").hidden=!show;$("key").required=show;$("forget").hidden=show}
showKey(!load(KEY));
$("forget").onclick=()=>{store(KEY,null);showKey(true);$("key").focus()};
function say(cls,text){const m=$("msg");m.className="msg show "+cls;m.textContent=text}
// Prefill from the capture button. Runs on load AND whenever the button
// reuses this open window with a new link (that only changes the #fragment).
function prefill(){if(!location.hash)return;const h=new URLSearchParams(location.hash.slice(1));
  if(h.has("u")){$("url").value=h.get("u")||"";$("text").value=h.get("t")||"";$("notes").value="";$("msg").className="msg"}
  history.replaceState(null,"",location.pathname);window.focus()}
prefill();window.addEventListener("hashchange",prefill);
$("f").onsubmit=async e=>{e.preventDefault();
  const key=$("key").value||load(KEY);if(!key){showKey(true);return}
  $("go").disabled=true;say("","Saving...");
  try{const r=await fetch("/capture",{method:"POST",headers:{"Content-Type":"application/json","X-Capture-Secret":key},
      body:JSON.stringify({url:$("url").value,text:$("text").value,notes:$("notes").value})});
    const d=await r.json().catch(()=>({status:"error",message:"Unexpected reply ("+r.status+")"}));
    if(r.status===401){store(KEY,null);showKey(true);say("error","That access key isn't right. Please re-enter it.");return}
    if($("key").value){store(KEY,$("key").value);$("key").value="";showKey(false)}
    say(d.status,(d.status==="created"?"Saved. ":"")+d.message+(d.flags&&d.flags.length?" ["+d.flags.join(", ")+"]":""));
    if(d.status==="created"||d.status==="updated"){$("url").value="";$("text").value="";$("notes").value=""}
  }catch(err){say("error","Couldn't reach the server. Check your connection and try again.")}
  finally{$("go").disabled=false}};`;
  return page("Add a job", body, nonce, script);
}

export function bookmarkletCode(origin) {
  // Reads only the page address and the text Peace has highlighted.
  return "javascript:(()=>{const t=String(getSelection()).slice(0,6000);" +
    `window.open('${origin}/add#u='+encodeURIComponent(location.href)+'&t='+encodeURIComponent(t),` +
    "'gtmcapture','width=480,height=760')})()";
}

export function bookmarkletPage(origin, nonce) {
  const code = bookmarkletCode(origin).replace(/"/g, "&quot;");
  const body = `
<h1>Capture button</h1>
<p class="sub">A browser bookmark that sends the post you're reading to the Add a job form.</p>
<div class="card">
  <p><strong>Install (once, on your laptop):</strong></p>
  <ol>
    <li>Show your bookmarks bar: press <code>Ctrl</code> + <code>Shift</code> + <code>B</code>.</li>
    <li>Drag this button onto the bookmarks bar: <a class="bm" href="${code}">+ Capture job</a></li>
  </ol>
  <p><strong>Use it:</strong></p>
  <ol>
    <li>Open the LinkedIn post. For a post in your feed, click its time stamp first so the post opens on its own page.</li>
    <li>Highlight the post text with your mouse.</li>
    <li>Click <strong>+ Capture job</strong>. A small window opens with the link and text filled in. Click <strong>Save to HubSpot</strong>.</li>
  </ol>
  <p class="hint">It only reads the page address and the text you highlighted. Nothing visits LinkedIn on its own.</p>
</div>`;
  return page("Capture button", body, nonce);
}
