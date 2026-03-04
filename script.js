const searchInput = document.getElementById("searchInput");
const quickLinks = document.getElementById("quickLinks");
const categorySidebar = document.getElementById("categorySidebar");
const emptyState = document.getElementById("emptyState");

function normalize(text) {
  return (text || "").toLowerCase().trim();
}

function getCategoryBlocks() {
  return Array.from(document.querySelectorAll(".category-block"));
}

function slugify(text) {
  return (text || "")
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function ensureBlockIds() {
  getCategoryBlocks().forEach((block, index) => {
    if (!block.id) {
      const label = block.dataset.category || block.querySelector("h2")?.textContent || `category-${index + 1}`;
      block.id = `cat-${slugify(label)}-${index + 1}`;
    }
  });
}

function applyFilter(keyword = "") {
  const q = normalize(keyword);
  let totalVisibleCards = 0;

  getCategoryBlocks().forEach((block) => {
    const cards = Array.from(block.querySelectorAll(".site-card"));
    let categoryVisible = 0;

    cards.forEach((card) => {
      const searchable = [
        block.dataset.category,
        block.querySelector("h2")?.textContent,
        card.querySelector(".site-title")?.textContent,
        card.querySelector(".site-desc")?.textContent,
        card.querySelector(".site-meta")?.textContent,
        card.dataset.keywords
      ]
        .join(" ")
        .toLowerCase();

      const match = !q || searchable.includes(q);
      card.hidden = !match;
      if (match) categoryVisible += 1;
    });

    block.hidden = categoryVisible === 0;
    totalVisibleCards += categoryVisible;
  });

  emptyState.hidden = totalVisibleCards !== 0;
}

function showOnlyCategory(targetId) {
  const blocks = getCategoryBlocks();
  blocks.forEach((block) => {
    const isTarget = block.id === targetId;
    block.hidden = !isTarget;
    block.querySelectorAll(".site-card").forEach((card) => {
      card.hidden = !isTarget ? true : false;
    });
  });
  emptyState.hidden = true;
}

function bindQuickLinks() {
  quickLinks.querySelectorAll("a[data-keyword]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const keyword = link.dataset.keyword || "";
      searchInput.value = keyword;
      applyFilter(keyword);
    });
  });
}

function getCategoryIcon(title = "") {
  const t = title.toLowerCase();
  if (t.includes("写作")) return "✍️";
  if (t.includes("绘图") || t.includes("设计")) return "🎨";
  if (t.includes("视频")) return "🎬";
  if (t.includes("办公") || t.includes("效率")) return "📁";
  if (t.includes("智能体") || t.includes("模型")) return "🧠";
  if (t.includes("聊天") || t.includes("对话")) return "💬";
  if (t.includes("编程") || t.includes("开发")) return "</>";
  if (t.includes("音频")) return "🎵";
  if (t.includes("搜索")) return "🔍";
  if (t.includes("学习")) return "🎓";
  if (t.includes("训练")) return "🧩";
  if (t.includes("评测")) return "👑";
  return "✨";
}

function parseCategoryParts(title = "") {
  const raw = (title || "").trim();
  const parts = raw.split("/").map((item) => item.trim()).filter(Boolean);
  if (parts.length >= 2) {
    return { first: parts[0], second: parts.slice(1).join(" / ") };
  }
  return { first: raw, second: "" };
}

function renderSidebar() {
  categorySidebar.innerHTML = "";

  const groups = [];
  const groupMap = new Map();

  getCategoryBlocks().forEach((block, index) => {
    const title = block.dataset.category || block.querySelector("h2")?.textContent || `分类${index + 1}`;
    const { first, second } = parseCategoryParts(title);
    if (!groupMap.has(first)) {
      const group = { first, parentBlock: null, children: [] };
      groupMap.set(first, group);
      groups.push(group);
    }
    const g = groupMap.get(first);
    if (second) {
      g.children.push({ second, block });
    } else {
      g.parentBlock = block;
    }
  });

  function setActive(targetBtn) {
    categorySidebar.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === targetBtn));
  }

  groups.forEach((group, index) => {
    if (group.children.length === 0) {
      const title = group.first;
      const block = group.parentBlock;
      if (!block) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.target = block.id;

      const icon = document.createElement("span");
      icon.className = "category-sidebar__icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = getCategoryIcon(title);

      const label = document.createElement("span");
      label.className = "category-sidebar__label";
      label.textContent = title;

      btn.append(icon, label);
      if (index === 0) btn.classList.add("active");

      btn.addEventListener("click", () => {
        searchInput.value = "";
        showOnlyCategory(block.id);
        document.getElementById(block.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
        setActive(btn);
      });
      categorySidebar.appendChild(btn);
      return;
    }

    const wrap = document.createElement("div");
    wrap.className = "category-sidebar__group";

    const parentBtn = document.createElement("button");
    parentBtn.type = "button";
    parentBtn.className = "category-sidebar__parent";
    parentBtn.setAttribute("aria-expanded", "false");

    const icon = document.createElement("span");
    icon.className = "category-sidebar__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = getCategoryIcon(group.first);

    const label = document.createElement("span");
    label.className = "category-sidebar__label";
    label.textContent = group.first;

    const caret = document.createElement("span");
    caret.className = "category-sidebar__caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "⌄";

    parentBtn.append(icon, label, caret);

    const subList = document.createElement("div");
    subList.className = "category-sidebar__sublist";
    subList.hidden = true;

    group.children.forEach((item, childIndex) => {
      const childBtn = document.createElement("button");
      childBtn.type = "button";
      childBtn.className = "category-sidebar__child";
      childBtn.dataset.target = item.block.id;
      childBtn.textContent = item.second;

      childBtn.addEventListener("click", () => {
        searchInput.value = "";
        showOnlyCategory(item.block.id);
        document.getElementById(item.block.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
        setActive(childBtn);
      });

      if (index === 0 && childIndex === 0) {
        childBtn.classList.add("active");
        subList.hidden = false;
        wrap.classList.add("is-open");
        parentBtn.setAttribute("aria-expanded", "true");
      }

      subList.appendChild(childBtn);
    });

    parentBtn.addEventListener("click", () => {
      const opening = subList.hidden;
      subList.hidden = !opening;
      wrap.classList.toggle("is-open", opening);
      parentBtn.setAttribute("aria-expanded", opening ? "true" : "false");
    });

    wrap.append(parentBtn, subList);
    categorySidebar.appendChild(wrap);
  });
}

searchInput.addEventListener("input", (event) => {
  applyFilter(event.target.value);
});

ensureBlockIds();
bindQuickLinks();
renderSidebar();
applyFilter();
