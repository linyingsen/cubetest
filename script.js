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

function renderSidebar() {
  categorySidebar.innerHTML = "";

  getCategoryBlocks().forEach((block, index) => {
    const title = block.dataset.category || block.querySelector("h2")?.textContent || `分类${index + 1}`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.target = block.id;
    btn.textContent = title;
    if (index === 0) btn.classList.add("active");

    btn.addEventListener("click", () => {
      document.getElementById(block.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      categorySidebar.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === btn));
    });

    categorySidebar.appendChild(btn);
  });
}

searchInput.addEventListener("input", (event) => {
  applyFilter(event.target.value);
});

ensureBlockIds();
bindQuickLinks();
renderSidebar();
applyFilter();
