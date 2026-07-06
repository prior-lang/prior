// PRIOR language support: completions, hovers, diagnostics, formatting.
//
// The extension never re-implements the language. Tag data (params,
// defaults, docs) is generated from the reference implementation's
// registry into data/tags.json, and diagnostics/formatting shell out to
// the prior CLI (`pip install prior-lang`) so what you see in the editor
// is exactly what the compiler will say.

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");

const TAG_DATA = require(path.join(__dirname, "data", "tags.json"));

const KIND_ICON = {
  condition: vscode.CompletionItemKind.Function,
  exit: vscode.CompletionItemKind.Event,
  sizing: vscode.CompletionItemKind.Value,
  risk: vscode.CompletionItemKind.Property,
  universe: vscode.CompletionItemKind.Module,
  metric: vscode.CompletionItemKind.Unit,
  option: vscode.CompletionItemKind.Interface,
  management: vscode.CompletionItemKind.Event,
};

const KEYWORDS = [
  "strategy", "universe", "timeframe", "when", "buy", "short", "sell",
  "cover", "hold", "rebalance", "risk", "where", "weighted", "equally",
  "by", "top", "bottom", "and", "or", "at", "above", "below", "crosses",
  "price", "volume", "write", "close", "roll",
];

let diagnostics;
let debounceTimer;

// ── CLI plumbing ─────────────────────────────────────────────────────

function cliCommand() {
  return vscode.workspace.getConfiguration("prior").get("command", "prior");
}

/** Run the prior CLI with `source` on stdin. Tries the configured
 *  command, then falls back to `python3 -m prior_lang.cli`. */
function runCli(args, source) {
  return new Promise((resolve) => {
    const attempts = [
      [cliCommand(), args],
      ["python3", ["-m", "prior_lang.cli", ...args]],
    ];
    const tryNext = (i) => {
      if (i >= attempts.length) return resolve(null);
      const [cmd, argv] = attempts[i];
      const proc = cp.execFile(
        cmd, argv, { timeout: 10000 },
        (err, stdout, stderr) => {
          if (err && (err.code === "ENOENT" || err.code === 127)) return tryNext(i + 1);
          resolve({ code: err ? err.code ?? 1 : 0, stdout, stderr });
        }
      );
      proc.stdin.on("error", () => {}); // EPIPE if the process died early
      proc.stdin.end(source);
    };
    tryNext(0);
  });
}

// ── Diagnostics ──────────────────────────────────────────────────────

async function validate(document) {
  if (document.languageId !== "prior") return;
  const result = await runCli(["validate", "--stdin", "--json"], document.getText());
  if (result === null) {
    // CLI not installed: stay quiet rather than nagging on every keystroke.
    diagnostics.set(document.uri, []);
    return;
  }
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    diagnostics.set(document.uri, []);
    return;
  }
  const items = (report.errors || []).map((e) => {
    const line = Math.max(0, (e.line || 1) - 1);
    const col = Math.max(0, e.col || 0);
    const lineText = line < document.lineCount ? document.lineAt(line).text : "";
    const range = new vscode.Range(line, col, line, Math.max(col + 1, lineText.length));
    let message = e.message;
    if (e.suggestion) message += ` — ${e.suggestion}`;
    const d = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
    d.source = "prior";
    return d;
  });
  diagnostics.set(document.uri, items);
}

function scheduleValidate(document) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => validate(document), 400);
}

// ── Hover ────────────────────────────────────────────────────────────

function tagMarkdown(tag) {
  const md = new vscode.MarkdownString();
  const badge = tag.cloudOnly ? "  ·  *cloud data — validates locally, evaluates hosted*" : "";
  md.appendMarkdown(`**\`[${tag.name}]\`** — ${tag.kind}${badge}\n\n`);
  md.appendMarkdown(tag.description + "\n\n");
  if (tag.params.length) {
    md.appendMarkdown(
      tag.params
        .map((p) => {
          const req = p.required ? "required" : `default ${p.default}`;
          const named = p.named ? ` (named: \`${p.name}=…\`)` : "";
          return `- \`${p.name}\` (${p.kind}, ${req})${named}`;
        })
        .join("\n") + "\n\n"
    );
  }
  const tickers = TAG_DATA.universes[tag.name];
  if (tickers) md.appendMarkdown(`Contents: ${tickers.join(" ")}\n\n`);
  md.appendMarkdown(`Example: \`${tag.example}\``);
  return md;
}

function provideHover(document, position) {
  const range = document.getWordRangeAtPosition(position, /[A-Za-z_][A-Za-z0-9_.]*/);
  if (!range) return null;
  const word = document.getText(range).toLowerCase();
  const tag = TAG_DATA.tags.find((t) => t.name === word);
  if (tag) return new vscode.Hover(tagMarkdown(tag), range);
  if (word === "spread") {
    const md = new vscode.MarkdownString();
    md.appendMarkdown(
      "**`spread($A, $B)`** — pairs trading operand\n\n" +
        "The ratio of two legs' closes (`spread($A, $B, diff)` for the difference). " +
        "Behaves exactly like `price`: every comparison works on it, indicators " +
        "compute on the spread series. Buying the spread is long A / short B in " +
        "equal dollar legs.\n\nExample: `when spread($GLD, $GDX) at [lower_bollinger 60]`"
    );
    return new vscode.Hover(md, range);
  }
  return null;
}

// ── Completions ──────────────────────────────────────────────────────

function tagSnippet(tag) {
  const required = tag.params.filter((p) => p.required && !p.named);
  if (!required.length) return new vscode.SnippetString(tag.name);
  const parts = required.map((p, i) => `\${${i + 1}:${p.name}}`);
  return new vscode.SnippetString(`${tag.name} ${parts.join(" ")}`);
}

function provideCompletions(document, position) {
  const before = document.lineAt(position.line).text.slice(0, position.character);

  // Inside an open [tag — offer the vocabulary.
  const open = before.lastIndexOf("[");
  const close = before.lastIndexOf("]");
  if (open > close) {
    const afterUniverse = /^\s*universe\s*\[/i.test(before);
    return TAG_DATA.tags
      .filter((t) => (afterUniverse ? t.kind === "universe" : t.kind !== "universe"))
      .map((t) => {
        const item = new vscode.CompletionItem(
          t.name,
          KIND_ICON[t.kind] || vscode.CompletionItemKind.Function
        );
        item.detail = `${t.kind}${t.cloudOnly ? " · cloud" : ""}`;
        item.documentation = tagMarkdown(t);
        item.insertText = tagSnippet(t);
        item.sortText = (t.kind === "condition" ? "0" : "1") + t.name;
        return item;
      });
  }

  // Start of a statement — offer keywords.
  if (/^\s*[a-z]*$/i.test(before)) {
    return KEYWORDS.map((k) => {
      const item = new vscode.CompletionItem(k, vscode.CompletionItemKind.Keyword);
      item.sortText = "2" + k;
      return item;
    });
  }
  return undefined;
}

// ── Quick fixes ──────────────────────────────────────────────────────

function provideCodeActions(document, _range, context) {
  const actions = [];
  for (const d of context.diagnostics) {
    if (d.source !== "prior") continue;
    const m = /Did you mean \[([a-z0-9_.]+)\]\?/i.exec(d.message);
    if (!m) continue;
    const wordRange =
      document.getWordRangeAtPosition(d.range.start, /[A-Za-z_][A-Za-z0-9_.]*/) ||
      document.getWordRangeAtPosition(d.range.start.translate(0, 1), /[A-Za-z_][A-Za-z0-9_.]*/);
    if (!wordRange) continue;
    const action = new vscode.CodeAction(`Change to [${m[1]}]`, vscode.CodeActionKind.QuickFix);
    action.edit = new vscode.WorkspaceEdit();
    action.edit.replace(document.uri, wordRange, m[1]);
    action.diagnostics = [d];
    action.isPreferred = true;
    actions.push(action);
  }
  return actions;
}

// ── Formatting ───────────────────────────────────────────────────────

async function provideFormatting(document) {
  const result = await runCli(["fmt", "--stdin"], document.getText());
  if (result === null) {
    vscode.window.showWarningMessage(
      "prior CLI not found — install it with: pip install prior-lang"
    );
    return [];
  }
  if (result.code !== 0) return []; // parse error: diagnostics already show it
  const full = new vscode.Range(
    document.positionAt(0),
    document.positionAt(document.getText().length)
  );
  return [vscode.TextEdit.replace(full, result.stdout)];
}

// ── Activation ───────────────────────────────────────────────────────

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("prior");
  context.subscriptions.push(diagnostics);

  context.subscriptions.push(
    vscode.languages.registerHoverProvider("prior", { provideHover }),
    vscode.languages.registerCompletionItemProvider("prior", { provideCompletionItems: provideCompletions }, "["),
    vscode.languages.registerDocumentFormattingEditProvider("prior", { provideDocumentFormattingEdits: provideFormatting }),
    vscode.languages.registerCodeActionsProvider("prior", { provideCodeActions }, {
      providedCodeActionKinds: [vscode.CodeActionKind.QuickFix],
    }),
    vscode.workspace.onDidOpenTextDocument(validate),
    vscode.workspace.onDidSaveTextDocument(validate),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (vscode.workspace.getConfiguration("prior").get("validateOnType", true)) {
        scheduleValidate(e.document);
      }
    }),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
  );

  vscode.workspace.textDocuments.forEach(validate);
}

function deactivate() {}

module.exports = { activate, deactivate };
