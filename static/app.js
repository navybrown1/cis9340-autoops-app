(function () {
  const HISTORY_KEY = "cis9340_query_history";
  const DRAFT_KEY = "cis9340_saved_sql";
  const toast = document.getElementById("app-toast");

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      toast.classList.remove("visible");
    }, 3200);
  }

  function getEditor() {
    return document.getElementById("sql");
  }

  function readHistory() {
    try {
      const raw = window.localStorage.getItem(HISTORY_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
    } catch (error) {
      return [];
    }
  }

  function writeHistory(history) {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 8)));
  }

  function pushHistory(sql) {
    const cleaned = (sql || "").trim();
    if (!cleaned) return;
    const history = readHistory().filter((entry) => entry !== cleaned);
    history.unshift(cleaned);
    writeHistory(history);
    renderHistory();
  }

  function formatSql(sql) {
    const original = (sql || "").trim();
    if (!original) return "";

    let formatted = original.replace(/\r\n/g, "\n").replace(/[ \t]+/g, " ");
    const keywordGroups = [
      "select",
      "from",
      "where",
      "group by",
      "order by",
      "having",
      "limit",
      "values",
      "set",
      "join",
      "left join",
      "right join",
      "inner join",
      "outer join",
      "on",
      "union all",
      "insert into",
      "update",
      "delete from",
      "create table",
      "alter table",
    ];

    for (const keyword of keywordGroups) {
      const pattern = new RegExp(`\\b${keyword.replace(/ /g, "\\s+")}\\b`, "ig");
      formatted = formatted.replace(pattern, keyword.toUpperCase());
    }

    const breakBefore = [
      "FROM",
      "WHERE",
      "GROUP BY",
      "ORDER BY",
      "HAVING",
      "LIMIT",
      "VALUES",
      "SET",
      "UNION ALL",
      "INSERT INTO",
      "UPDATE",
      "DELETE FROM",
      "CREATE TABLE",
      "ALTER TABLE",
    ];

    for (const keyword of breakBefore) {
      const pattern = new RegExp(`\\s+(${keyword.replace(/ /g, "\\s+")})\\s+`, "ig");
      formatted = formatted.replace(pattern, "\n$1 ");
    }

    return formatted.replace(/\n{3,}/g, "\n\n").trim();
  }

  function connectionCopyText(button) {
    if (button && button.dataset.copyText) {
      return button.dataset.copyText;
    }
    const target = document.querySelector("[data-connection-target]");
    return target ? target.textContent.trim() : "Azure MySQL connection";
  }

  function renderHistory() {
    const list = document.getElementById("query-history-list");
    if (!list) return;

    list.replaceChildren();
    const history = readHistory();

    if (!history.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = "No saved SQL yet. Use Save or Run Query to populate this list.";
      list.appendChild(empty);
      return;
    }

    const editor = getEditor();

    history.forEach((sql, index) => {
      const entry = document.createElement("article");
      entry.className = "history-entry";

      const code = document.createElement("code");
      code.textContent = sql;

      const load = document.createElement("button");
      load.type = "button";
      load.className = "history-entry-load";
      load.textContent = "Load";
      load.addEventListener("click", () => {
        if (!editor) return;
        editor.value = sql;
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        editor.focus();
        showToast(`Loaded query ${index + 1}.`);
      });

      entry.append(code, load);
      list.appendChild(entry);
    });
  }

  async function handleAction(action, button) {
    const editor = getEditor();

    switch (action) {
      case "show-notifications":
        showToast("No alerts. Azure MySQL is connected and the studio is healthy.");
        break;
      case "show-help":
        showToast("Catalog browses tables, Query Lab runs read-only SQL, and Settings tests the live Azure connection.");
        break;
      case "save-query":
        if (!editor || !editor.value.trim()) {
          showToast("Nothing to save yet.");
          return;
        }
        window.localStorage.setItem(DRAFT_KEY, editor.value);
        pushHistory(editor.value);
        showToast("SQL draft saved locally in this browser.");
        break;
      case "format-query":
        if (!editor || !editor.value.trim()) {
          showToast("Add SQL before formatting.");
          return;
        }
        editor.value = formatSql(editor.value);
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        showToast("SQL formatted.");
        break;
      case "toggle-history": {
        const drawer = document.getElementById("query-history-drawer");
        if (!drawer) {
          showToast("Recent query history is only available in Query Lab.");
          return;
        }
        const opening = drawer.hidden;
        drawer.hidden = !drawer.hidden;
        if (opening) {
          renderHistory();
          drawer.scrollIntoView({ behavior: "smooth", block: "start" });
          showToast("Recent query history opened.");
        } else {
          showToast("Query history hidden.");
        }
        break;
      }
      case "refresh-schema":
        window.location.reload();
        break;
      case "test-connection": {
        const originalLabel = button.dataset.originalLabel || button.textContent;
        button.dataset.originalLabel = originalLabel;
        button.disabled = true;
        button.textContent = "Testing...";
        try {
          const response = await window.fetch("/api/connection-check", {
            headers: { Accept: "application/json" },
          });
          const data = await response.json();
          const statusText = document.getElementById("connection-status-text");
          if (statusText && data.message) {
            statusText.textContent = data.message;
          }
          showToast(data.message || "Connection test succeeded.");
        } catch (error) {
          showToast("Connection test failed.");
        } finally {
          button.disabled = false;
          button.textContent = button.dataset.originalLabel || originalLabel;
        }
        break;
      }
      case "copy-connection": {
        const copyText = connectionCopyText(button);
        try {
          await window.navigator.clipboard.writeText(copyText);
          showToast("Connection details copied to clipboard.");
        } catch (error) {
          showToast("Copy failed in this browser.");
        }
        break;
      }
      default:
        break;
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    event.preventDefault();
    handleAction(button.dataset.action, button);
  });

  const editor = getEditor();
  const form = document.getElementById("query-form");

  if (editor) {
    const params = new URLSearchParams(window.location.search);
    const urlSql = params.get("sql");
    const savedDraft = window.localStorage.getItem(DRAFT_KEY);

    if (urlSql) {
      pushHistory(editor.value);
    } else if (savedDraft && !editor.value.trim()) {
      editor.value = savedDraft;
    }

    editor.addEventListener("input", () => {
      window.localStorage.setItem(DRAFT_KEY, editor.value);
    });
  }

  if (form && editor) {
    form.addEventListener("submit", () => {
      if (editor.value.trim()) {
        window.localStorage.setItem(DRAFT_KEY, editor.value);
        pushHistory(editor.value);
      }
    });
  }

  renderHistory();
})();
