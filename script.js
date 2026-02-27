const siteData = [
  {
    id: "chat-models",
    name: "AI 对话与大模型",
    tag: "热门",
    items: [
      { title: "ChatGPT", url: "https://chat.openai.com/", desc: "多用途 AI 助手，适合写作、编程与头脑风暴。", meta: "对话模型" },
      { title: "Claude", url: "https://claude.ai/", desc: "长上下文与文档理解能力强，适合分析整理。", meta: "对话模型" },
      { title: "Gemini", url: "https://gemini.google.com/", desc: "Google 系 AI 助手，支持多模态交互。", meta: "对话模型" },
      { title: "Kimi", url: "https://kimi.moonshot.cn/", desc: "擅长阅读长文与中文场景问答。", meta: "中文 AI" },
      { title: "通义千问", url: "https://tongyi.aliyun.com/", desc: "阿里云推出的中文 AI 助手与模型平台。", meta: "中文 AI" },
      { title: "文心一言", url: "https://yiyan.baidu.com/", desc: "百度大模型应用，适合中文内容创作。", meta: "中文 AI" }
    ]
  },
  {
    id: "image-design",
    name: "AI 绘图与设计",
    tag: "创意",
    items: [
      { title: "Midjourney", url: "https://www.midjourney.com/", desc: "高质量 AI 图像生成，风格表达丰富。", meta: "AI 绘图" },
      { title: "Stable Diffusion", url: "https://stability.ai/", desc: "开源生态强，可私有化部署与精细控制。", meta: "开源" },
      { title: "Adobe Firefly", url: "https://firefly.adobe.com/", desc: "Adobe 生态中的生成式设计工具。", meta: "设计" },
      { title: "Canva", url: "https://www.canva.com/", desc: "在线图形设计平台，模板丰富上手快。", meta: "视觉设计" },
      { title: "Figma", url: "https://www.figma.com/", desc: "产品设计与协作平台，支持插件扩展。", meta: "UI/UX" }
    ]
  },
  {
    id: "dev-tools",
    name: "开发者效率工具",
    tag: "开发",
    items: [
      { title: "GitHub", url: "https://github.com/", desc: "代码托管与开源协作核心平台。", meta: "代码协作" },
      { title: "Vercel", url: "https://vercel.com/", desc: "前端部署平台，适合快速发布静态与全栈应用。", meta: "部署" },
      { title: "Cloudflare", url: "https://www.cloudflare.com/", desc: "CDN、安全与边缘计算服务。", meta: "基础设施" },
      { title: "CodePen", url: "https://codepen.io/", desc: "在线前端代码实验场与灵感社区。", meta: "前端" },
      { title: "Stack Overflow", url: "https://stackoverflow.com/", desc: "程序员问答社区，问题覆盖面广。", meta: "知识库" }
    ]
  },
  {
    id: "learn",
    name: "学习与成长",
    tag: "学习",
    items: [
      { title: "Coursera", url: "https://www.coursera.org/", desc: "全球高校课程，涵盖 AI、编程与商业。", meta: "课程" },
      { title: "DeepLearning.AI", url: "https://www.deeplearning.ai/", desc: "AI 专项课程与实践资源。", meta: "AI 学习" },
      { title: "freeCodeCamp", url: "https://www.freecodecamp.org/", desc: "免费编程学习路径与项目实践。", meta: "编程" },
      { title: "中国大学MOOC", url: "https://www.icourse163.org/", desc: "中文高校公开课程平台。", meta: "中文课程" },
      { title: "B站学习区", url: "https://www.bilibili.com/", desc: "大量免费技术教程与项目实战内容。", meta: "视频学习" }
    ]
  }
];

const cardsArea = document.getElementById("cardsArea");
const sidebar = document.getElementById("categorySidebar");
const quickLinks = document.getElementById("quickLinks");
const searchInput = document.getElementById("searchInput");

function renderSidebar(activeId) {
  sidebar.innerHTML = "";
  siteData.forEach((category) => {
    const btn = document.createElement("button");
    btn.textContent = category.name;
    btn.className = category.id === activeId ? "active" : "";
    btn.addEventListener("click", () => {
      document.getElementById(category.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      renderSidebar(category.id);
    });
    sidebar.appendChild(btn);
  });
}

function renderQuickLinks() {
  quickLinks.innerHTML = "";
  ["热门工具", "绘图设计", "开发提效", "学习资源", "中文友好"].forEach((label) => {
    const chip = document.createElement("a");
    chip.href = "#";
    chip.textContent = label;
    chip.addEventListener("click", (event) => {
      event.preventDefault();
      searchInput.value = label;
      renderCards(label);
    });
    quickLinks.appendChild(chip);
  });
}

function createCard(item) {
  const card = document.createElement("a");
  card.className = "site-card";
  card.href = item.url;
  card.target = "_blank";
  card.rel = "noopener noreferrer";
  card.innerHTML = `
    <h3 class="site-title">${item.title}</h3>
    <p class="site-desc">${item.desc}</p>
    <span class="site-meta">${item.meta}</span>
  `;
  return card;
}

function renderCards(keyword = "") {
  const q = keyword.trim().toLowerCase();
  cardsArea.innerHTML = "";

  let visibleCount = 0;

  siteData.forEach((category) => {
    const filtered = category.items.filter((item) => {
      if (!q) return true;
      return [category.name, item.title, item.desc, item.meta].join(" ").toLowerCase().includes(q);
    });

    if (!filtered.length) return;

    visibleCount += filtered.length;

    const block = document.createElement("section");
    block.className = "category-block";
    block.id = category.id;

    const head = document.createElement("div");
    head.className = "category-head";
    head.innerHTML = `
      <h2>${category.name}</h2>
      <span class="category-tag">${category.tag}</span>
    `;

    const grid = document.createElement("div");
    grid.className = "card-grid";
    filtered.forEach((item) => grid.appendChild(createCard(item)));

    block.append(head, grid);
    cardsArea.appendChild(block);
  });

  if (!visibleCount) {
    cardsArea.innerHTML = `<div class="empty-state">未找到匹配内容，请尝试更换关键词。</div>`;
  }
}

searchInput.addEventListener("input", (event) => {
  renderCards(event.target.value);
});

renderQuickLinks();
renderSidebar(siteData[0]?.id);
renderCards();
