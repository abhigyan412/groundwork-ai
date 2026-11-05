/*!
 * Assistant chat button (optional JS embed; the iframe embed is the primary option).
 *
 *   <script src="https://YOUR-HOST/embed.js" data-assistant="https://YOUR-HOST/a/TOKEN" async></script>
 *
 * Optional: data-label="Ask HR" (button text), data-position="left" (default right).
 * Renders inside a Shadow DOM, so the host page's CSS can't break it and it can't leak styles.
 * The widget iframe is only created on first open.
 */
(function () {
  "use strict";
  var script =
    document.currentScript || document.querySelector("script[data-assistant][src*='embed.js']");
  if (!script || window.__assistantEmbedLoaded) return;
  var url = script.getAttribute("data-assistant") || "";
  if (!/^https?:\/\/[^\s]+\/a\/[\w-]+$/.test(url)) {
    console.warn("[assistant embed] data-assistant must be the assistant link, e.g. https://host/a/<token>");
    return;
  }
  window.__assistantEmbedLoaded = true;
  var label = script.getAttribute("data-label") || "Ask a question";
  var side = script.getAttribute("data-position") === "left" ? "left" : "right";

  var css =
    ":host{all:initial}" +
    ".btn{position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;display:flex;align-items:center;gap:8px;" +
    "height:48px;padding:0 18px;border:0;border-radius:999px;background:#16202E;color:#fff;cursor:pointer;" +
    "font:600 14px/1 'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif;" +
    "box-shadow:0 8px 28px rgba(22,32,46,.14),0 1px 3px rgba(22,32,46,.08)}" +
    ".btn:hover{background:#26324a}" +
    ".btn:focus-visible{outline:2px solid #0F6B66;outline-offset:3px}" +
    ".btn svg{width:18px;height:18px;flex:none}" +
    ".panel{position:fixed;bottom:80px;" + side + ":20px;z-index:2147483000;width:400px;height:600px;" +
    "max-width:calc(100vw - 40px);max-height:calc(100vh - 100px);border:1px solid #DDE2E8;border-radius:14px;" +
    "overflow:hidden;background:#fff;box-shadow:0 8px 28px rgba(22,32,46,.14),0 1px 3px rgba(22,32,46,.08)}" +
    ".panel[hidden]{display:none}" +
    ".panel iframe{width:100%;height:100%;border:0;display:block}" +
    "@media (max-width:480px){.panel{top:8px;left:8px;right:8px;bottom:76px;width:auto;height:auto;" +
    "max-width:none;max-height:none}}" +
    "@media (prefers-reduced-motion:no-preference){.panel{animation:in .16s ease-out}}" +
    "@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}";

  var chat =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var close =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" ' +
    'aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  function mount() {
    var host = document.createElement("div");
    host.setAttribute("data-assistant-embed", "");
    document.body.appendChild(host);
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    var style = document.createElement("style");
    style.textContent = css;
    var panel = document.createElement("div");
    panel.className = "panel";
    panel.id = "assistant-panel";
    panel.hidden = true;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.setAttribute("aria-controls", "assistant-panel");
    var frame = null;

    function render(open) {
      button.setAttribute("aria-expanded", String(open));
      button.innerHTML = (open ? close : chat) + "<span></span>";
      button.lastChild.textContent = open ? "Close" : label;
    }

    function setOpen(open) {
      if (open && !frame) {
        frame = document.createElement("iframe");
        frame.src = url;
        frame.title = label;
        frame.setAttribute("allow", "clipboard-write");
        panel.appendChild(frame);
      }
      panel.hidden = !open;
      render(open);
      if (open && frame) frame.focus();
    }

    button.addEventListener("click", function () {
      setOpen(panel.hidden);
    });
    function closeAndRefocus() {
      if (panel.hidden) return;
      setOpen(false);
      button.focus();
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAndRefocus();
    });
    // Focus is inside the widget iframe while it's open, so Escape there arrives as a message.
    // Only messages from our own iframe's window count.
    window.addEventListener("message", function (e) {
      if (frame && e.source === frame.contentWindow && e.data && e.data.type === "assistant:close") {
        closeAndRefocus();
      }
    });

    render(false);
    root.appendChild(style);
    root.appendChild(panel);
    root.appendChild(button);
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
