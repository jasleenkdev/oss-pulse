// The base path matches the GitHub Pages project URL. Override it for a custom domain.
export default {
  title: "OSS Pulse",
  root: "src",
  base: process.env.DASHBOARD_BASE ?? "/oss-pulse/",
  style: "style.css",
  pages: [
    {name: "Friendliest repos", path: "/repos"},
    {name: "Response times", path: "/response-times"},
    {name: "Good first issues", path: "/good-first-issues"},
    {name: "Trends", path: "/trends"},
    {name: "Pipeline health", path: "/health"}
  ],
  head: '<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><circle cx=%228%22 cy=%228%22 r=%226%22 fill=%22%232a78d6%22/></svg>">',
  footer: "Built from GH Archive. Figures come from gold extracts committed to the repository.",
  toc: false,
  pager: false,
  search: false,
  sidebar: true
};
