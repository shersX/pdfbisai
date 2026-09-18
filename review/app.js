(() => {
  const DEFAULT_CHOICES = ["vl", "flash", "max"];
  const CHOICE_LABEL = {
    vl: "vl",
    flash: "flash",
    max: "max",
    retry: "retry",
  };

  const state = {
    questions: [],
    decisions: {},
    choices: DEFAULT_CHOICES.slice(),
    filter: "pending",
    index: 0,
  };

  const el = {
    main: document.getElementById("main"),
    progress: document.getElementById("progress"),
    bucket: document.getElementById("bucket"),
    filter: document.getElementById("filter"),
    filterLabel: document.getElementById("filterLabel"),
    btnPrev: document.getElementById("btnPrev"),
    btnNext: document.getElementById("btnNext"),
    footer: document.getElementById("footerHint"),
  };

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function bucketLabel(b) {
    return b === "majority" ? "多数" : b === "split" ? "分歧" : b || "";
  }

  function stripThousands(s) {
    return String(s).replaceAll(",", "").replaceAll("，", "").trim();
  }

  function cleanNumberString(s) {
    let t = stripThousands(s);
    if (!/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(t)) return t;
    if (t.includes(".")) t = t.replace(/\.?0+$/, "").replace(/\.$/, "");
    return t || "0";
  }

  function scalarsEqual(a, b) {
    const sa = String(a).trim();
    const sb = String(b).trim();
    if (cleanNumberString(sa) === cleanNumberString(sb)) return true;
    const fa = Number(stripThousands(sa));
    const fb = Number(stripThousands(sb));
    if (!Number.isFinite(fa) || !Number.isFinite(fb)) return sa === sb;
    if (fa === fb) return true;
    const scale = Math.max(1, Math.abs(fa), Math.abs(fb));
    return Math.abs(fa - fb) <= Math.max(1e-6, 1e-9 * scale);
  }

  function valuesEqual(a, b) {
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      return a.every((x, i) => valuesEqual(x, b[i]));
    }
    if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
      const ka = Object.keys(a).sort();
      const kb = Object.keys(b).sort();
      if (ka.length !== kb.length || ka.some((k, i) => k !== kb[i])) return false;
      return ka.every((k) => valuesEqual(a[k], b[k]));
    }
    return scalarsEqual(a, b);
  }

  function parseAnswer(ans) {
    const s = String(ans ?? "").trim();
    if (!s) return "";
    if (s[0] === "{" || s[0] === "[") {
      try {
        return JSON.parse(s);
      } catch {
        return s;
      }
    }
    return s;
  }

  function answersEqual(a, b) {
    if (!a && !b) return true;
    if (!a || !b) return false;
    return valuesEqual(parseAnswer(a), parseAnswer(b));
  }

  /** @returns {{ pairs: string[][], sameKeys: Set<string>, label: string }} */
  function compareInfo(q) {
    const keys = state.choices.filter((k) => String(q.answers?.[k]?.answer ?? "").trim() !== "");
    const pairs = [];
    for (let i = 0; i < keys.length; i++) {
      for (let j = i + 1; j < keys.length; j++) {
        const a = q.answers[keys[i]].answer;
        const b = q.answers[keys[j]].answer;
        if (answersEqual(a, b)) pairs.push([keys[i], keys[j]]);
      }
    }
    const sameKeys = new Set(pairs.flat());
    const n = state.choices.length;
    let label = `${n} 方内容均不同`;
    if (keys.length < 2) {
      label = "有效答案不足，无法比较";
    } else if (sameKeys.size === keys.length && pairs.length >= keys.length - 1) {
      label = `${keys.length} 方内容相同（含数值格式归一）`;
    } else if (pairs.length === 1) {
      const [x, y] = pairs[0];
      const others = keys.filter((k) => k !== x && k !== y).join("/");
      label = `${x} 与 ${y} 相同，其余不同${others ? `（${others}）` : ""}`;
    } else if (pairs.length > 1) {
      label = `相同组合：${pairs.map(([x, y]) => `${x}=${y}`).join("；")}`;
    }
    return { pairs, sameKeys, label };
  }

  function filteredList() {
    if (state.filter === "all") return state.questions;
    if (state.filter === "done") {
      return state.questions.filter((q) => state.decisions[String(q.id)]);
    }
    return state.questions.filter((q) => !state.decisions[String(q.id)]);
  }

  function currentQuestion() {
    const list = filteredList();
    if (!list.length) return null;
    if (state.index < 0) state.index = 0;
    if (state.index >= list.length) state.index = list.length - 1;
    return list[state.index];
  }

  function updateChrome() {
    const list = filteredList();
    const done = Object.keys(state.decisions).length;
    const total = state.questions.length;
    const q = currentQuestion();
    el.progress.textContent = `已审 ${done}/${total}　当前列表 ${list.length ? state.index + 1 : 0}/${list.length}`;
    el.filterLabel.textContent =
      state.filter === "pending" ? "队列：未审" : state.filter === "done" ? "队列：已审" : "队列：全部";

    if (q) {
      el.bucket.textContent = bucketLabel(q.bucket);
      el.bucket.className = `pill ${q.bucket || ""}`;
    } else {
      el.bucket.textContent = "";
      el.bucket.className = "pill";
    }

    el.btnPrev.disabled = !list.length || state.index <= 0;
    el.btnNext.disabled = !list.length || state.index >= list.length - 1;

    if (el.footer) {
      const keys = state.choices.map((k, i) => `${i + 1}=${CHOICE_LABEL[k] || k}`).join("　");
      el.footer.textContent = `快捷键：${keys}　←上一项　→下一项　判定后自动跳到下一未审题`;
    }
  }

  function render() {
    updateChrome();
    const q = currentQuestion();
    if (!q) {
      el.main.innerHTML = `<div class="empty">当前筛选下没有题目。可切换筛选或继续审核。</div>`;
      return;
    }

    const decision = state.decisions[String(q.id)];
    const info = compareInfo(q);
    const tipClass =
      info.sameKeys.size >= 2 && info.pairs.length === 1
        ? "tip-majority"
        : info.sameKeys.size >= state.choices.length
          ? "tip-same"
          : "tip-split";

    const rows = state.choices.map((key) => {
      const item = q.answers[key] || { model: key, answer: "" };
      const selected = decision && decision.choice === key;
      const inPair = info.sameKeys.has(key) && info.pairs.length >= 1;
      const rowClass = [
        selected ? "selected" : "",
        inPair && info.pairs.length === 1 ? "same-majority" : "",
        info.sameKeys.size >= state.choices.length ? "same-all" : "",
      ]
        .filter(Boolean)
        .join(" ");
      return `
        <tr class="${rowClass}" data-choice="${key}">
          <td class="col-id">${escapeHtml(q.id)}</td>
          <td class="col-file">${escapeHtml(q.file_name)}</td>
          <td class="col-type">${escapeHtml(q.question_type)}</td>
          <td class="col-question">${escapeHtml(q.question)}</td>
          <td class="col-model">
            <span class="model-key ${key}">${CHOICE_LABEL[key] || key}</span>
            ${inPair && info.pairs.length === 1 ? '<span class="badge-same">相同</span>' : ""}
            <div class="model-name">${escapeHtml(item.model || "")}</div>
          </td>
          <td class="col-answer"><pre>${escapeHtml(item.answer || "")}</pre></td>
          <td class="col-action">
            <button type="button" class="pick ${key} ${selected ? "active" : ""}" data-choice="${key}">
              选 ${CHOICE_LABEL[key] || key}${selected ? " ✓" : ""}
            </button>
          </td>
        </tr>`;
    }).join("");

    el.main.innerHTML = `
      <div class="majority-tip ${tipClass}">${escapeHtml(info.label)}</div>
      <div class="table-wrap">
        <table class="sheet">
          <thead>
            <tr>
              <th>id</th>
              <th>file_name</th>
              <th>question_type</th>
              <th>question</th>
              <th>model</th>
              <th>answer</th>
              <th>判定</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;

    el.main.querySelectorAll("button.pick").forEach((node) => {
      node.addEventListener("click", () => choose(node.getAttribute("data-choice")));
    });
  }

  async function choose(choice) {
    const q = currentQuestion();
    if (!q || !state.choices.includes(choice)) return;

    const res = await fetch("/api/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: q.id, choice }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "保存失败");
      return;
    }

    state.decisions[String(q.id)] = data.decision;

    if (state.filter === "pending") {
      const list = filteredList();
      if (!list.length) state.index = 0;
      else if (state.index >= list.length) state.index = list.length - 1;
    } else {
      const list = filteredList();
      if (state.index < list.length - 1) state.index += 1;
    }
    render();
  }

  function goPrev() {
    if (state.index > 0) {
      state.index -= 1;
      render();
    }
  }

  function goNext() {
    const list = filteredList();
    if (state.index < list.length - 1) {
      state.index += 1;
      render();
    }
  }

  function inferChoices(qData) {
    if (Array.isArray(qData.choices) && qData.choices.length) {
      return qData.choices.slice();
    }
    const first = (qData.questions || [])[0];
    if (first && first.answers) {
      const order = ["vl", "flash", "max", "retry"];
      return order.filter((k) => k in first.answers);
    }
    return DEFAULT_CHOICES.slice();
  }

  async function boot() {
    const [qRes, dRes] = await Promise.all([
      fetch("/api/questions"),
      fetch("/api/decisions"),
    ]);
    const qData = await qRes.json();
    const dData = await dRes.json();
    if (!qRes.ok) {
      el.main.innerHTML = `<div class="empty">${escapeHtml(qData.error || "加载失败")}</div>`;
      return;
    }
    state.questions = qData.questions || [];
    state.choices = inferChoices(qData);
    state.decisions = dData || {};
    state.index = 0;
    document.title = state.choices.includes("retry") ? "分歧四轮审核" : "多数/分歧题审核";
    render();
  }

  el.filter.addEventListener("change", () => {
    state.filter = el.filter.value;
    state.index = 0;
    render();
  });
  el.btnPrev.addEventListener("click", goPrev);
  el.btnNext.addEventListener("click", goNext);

  window.addEventListener("keydown", (e) => {
    if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    const num = Number(e.key);
    if (num >= 1 && num <= state.choices.length) {
      choose(state.choices[num - 1]);
      return;
    }
    if (e.key === "ArrowLeft") goPrev();
    else if (e.key === "ArrowRight") goNext();
  });

  boot();
})();
