// Toggle a parsed column between rendered markdown and its raw source.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".md-toggle");
  if (!btn) return;
  const col = btn.closest(".col");
  const rendered = col.querySelector(".parsed");
  const raw = col.querySelector(".raw-md");
  if (!rendered || !raw) return;
  const showRaw = raw.hasAttribute("hidden");
  raw.toggleAttribute("hidden", !showRaw);
  rendered.toggleAttribute("hidden", showRaw);
  btn.textContent = showRaw ? "View rendered" : "View markdown";
  btn.classList.toggle("on", showRaw);
});
