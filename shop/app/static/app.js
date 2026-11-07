const $ = (id) => document.getElementById(id);

fetch("/api/version").then((r) => r.json()).then((v) => { $("ver").textContent = "version " + v.version; });

document.querySelectorAll(".chips button").forEach((b) =>
  b.addEventListener("click", () => { $("username").value = b.dataset.u; }));

function show(msg, ok) {
  const m = $("msg");
  m.textContent = msg;
  m.className = "msg" + (ok ? " ok" : "");
  m.hidden = false;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("submit").disabled = true;
  $("msg").hidden = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("username").value, password: $("password").value }),
    });
    const body = await res.json();
    if (!res.ok) { show(body.error || "Sign in failed.", false); return; }
    $("signin").hidden = true;
    $("account").hidden = false;
    $("who").hidden = false;
    $("who").textContent = body.user.display_name;
    $("hello").textContent = "Welcome, " + body.user.display_name + "!";
    $("prev").textContent = body.user.previous_login
      ? "Last sign-in: " + new Date(body.user.previous_login).toLocaleString()
      : "This is your first sign-in. Welcome aboard.";
  } catch (err) {
    show("Could not reach the shop. Check your connection.", false);
  } finally {
    $("submit").disabled = false;
  }
});

$("signout").addEventListener("click", () => {
  $("account").hidden = true; $("signin").hidden = false; $("who").hidden = true;
});
