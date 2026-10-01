// Inlines the libraries into app.html and writes ../second-brain.html (a single, offline-capable file).
// Usage: npm install && npm run build
import { build } from "esbuild";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// Read files straight from node_modules (some packages do not "export" their dist bundles).
const read = (p) => fs.readFileSync(path.join(here, "node_modules", p), "utf8");

const sdk = await build({
  stdin: { contents: "export { default as Anthropic } from '@anthropic-ai/sdk';", resolveDir: here },
  bundle: true, format: "iife", globalName: "AnthropicLib", platform: "browser", minify: true, write: false,
});

const libs = {
  anthropic: sdk.outputFiles[0].text,
  pptxgen: read("pptxgenjs/dist/pptxgen.bundle.js"),
  pdfjs: read("pdfjs-dist/build/pdf.min.js"),
  pdfworker: read("pdfjs-dist/build/pdf.worker.min.js"),
};

// Make library code safe to embed inside <script> tags.
const embed = (code) => code
  .replace(/^\/\/# sourceMappingURL=.*$/gm, "")
  .replace(/<\/script/gi, "<\\/script")
  .replace(/<!--/g, "<\\!--");

let html = fs.readFileSync(path.join(here, "app.html"), "utf8");
for (const [name, code] of Object.entries(libs)) {
  const marker = `/*LIB:${name}*/`;
  if (!html.includes(marker)) throw new Error(`missing ${marker} in app.html`);
  html = html.replace(marker, () => embed(code));
}
const out = path.join(here, "..", "second-brain.html");
fs.writeFileSync(out, html);
console.log(`wrote ${out} (${(html.length / 1024 / 1024).toFixed(1)} MB)`);
