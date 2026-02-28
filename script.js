const searchInput = document.getElementById("searchInput");
const quickLinks = document.getElementById("quickLinks");
const categorySidebar = document.getElementById("categorySidebar");
const categoryBlocks = Array.from(document.querySelectorAll(".category-block"));
const emptyState = document.getElementById("emptyState");

function normalize(text) {
  return (text || "").toLowerCase().trim();
}

function applyFilter(keyword = "") {
  const q = normalize(keyword);
  let totalVisibleCards = 0;

  categoryBlocks.forEach((block) => {
    const cards = Array.from(block.querySelectorAll(".site-card"));
    let categoryVisible = 0;

    cards.forEach((card) => {
      const searchable = [
        block.dataset.category,
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

function bindSidebarScroll() {
  const buttons = Array.from(categorySidebar.querySelectorAll("button[data-target]"));

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.target;
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      buttons.forEach((btn) => btn.classList.toggle("active", btn === button));
    });
  });
}

searchInput.addEventListener("input", (event) => {
  applyFilter(event.target.value);
});

bindQuickLinks();
bindSidebarScroll();
applyFilter();
