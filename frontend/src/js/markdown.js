function mdEscapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function mdInline(text) {
  let out = mdEscapeHtml(text);
  out = out.replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`);
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, label, href) => {
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  return out;
}

function mdIsTableSeparator(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
}

function mdSplitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);

  return s.split("|").map((c) => c.trim());
}

function renderMarkdown(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let i = 0;
  let listType = null;
  let paragraph = [];

  function flushParagraph() {
    if (paragraph.length) {
      html += `<p>${mdInline(paragraph.join(" "))}</p>`;
      paragraph = [];
    }
  }

  function closeList() {
    if (listType) {
      html += `</${listType}>`;
      listType = null;
    }
  }

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      flushParagraph();
      closeList();
      const lang = fence[1] || "";
      const codeLines = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }

      i++;
      const langClass = lang ? ` class="lang-${mdEscapeHtml(lang)}"` : "";
      html += `<pre><code${langClass}>${mdEscapeHtml(codeLines.join("\n"))}</code></pre>`;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${mdInline(heading[2])}</h${level}>`;
      i++;
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      html += `<blockquote>${mdInline(quote[1])}</blockquote>`;
      i++;
      continue;
    }

    if (line.includes("|") && lines[i + 1] && mdIsTableSeparator(lines[i + 1])) {
      flushParagraph();
      closeList();
      const header = mdSplitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(mdSplitRow(lines[i]));
        i++;
      }

      html += "<table><thead><tr>" + header.map((c) => `<th>${mdInline(c)}</th>`).join("") + "</tr></thead><tbody>";
      for (const row of rows) {
        html += "<tr>" + row.map((c) => `<td>${mdInline(c)}</td>`).join("") + "</tr>";
      }

      html += "</tbody></table>";
      continue;
    }

    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ol || ul) {
      flushParagraph();
      const wantType = ol ? "ol" : "ul";
      if (listType !== wantType) {
        closeList();
        html += `<${wantType}>`;
        listType = wantType;
      }

      html += `<li>${mdInline((ol || ul)[1])}</li>`;
      i++;
      continue;
    }
    closeList();

    if (line.trim() === "") {
      flushParagraph();
      i++;
      continue;
    }

    paragraph.push(line.trim());
    i++;
  }

  flushParagraph();
  closeList();
  return html;
}