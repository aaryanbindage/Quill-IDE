// A small Language Server Protocol client (no dependencies): spawns the Quill server
// and maps its answers onto the VS Code language APIs.
const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');

class Rpc {
	constructor(proc, onNotify) {
		this.proc = proc; this.next = 1; this.waiting = new Map(); this.buf = Buffer.alloc(0); this.onNotify = onNotify;
		proc.stdout.on('data', d => { this.buf = Buffer.concat([this.buf, d]); this.drain(); });
	}
	drain() {
		for (;;) {
			const end = this.buf.indexOf('\r\n\r\n');
			if (end < 0) { return; }
			const m = /Content-Length: *(\d+)/i.exec(this.buf.slice(0, end).toString());
			if (!m) { this.buf = this.buf.slice(end + 4); continue; }
			const len = parseInt(m[1], 10), start = end + 4;
			if (this.buf.length < start + len) { return; }
			const msg = JSON.parse(this.buf.slice(start, start + len).toString('utf8'));
			this.buf = this.buf.slice(start + len);
			if (msg.id !== undefined && this.waiting.has(msg.id)) {
				const { resolve } = this.waiting.get(msg.id); this.waiting.delete(msg.id); resolve(msg.result);
			} else if (msg.method) { this.onNotify(msg.method, msg.params); }
		}
	}
	write(obj) {
		const body = Buffer.from(JSON.stringify(obj), 'utf8');
		this.proc.stdin.write(Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`), body]));
	}
	request(method, params) {
		const id = this.next++;
		return new Promise(resolve => { this.waiting.set(id, { resolve }); this.write({ jsonrpc: '2.0', id, method, params }); });
	}
	notify(method, params) { this.write({ jsonrpc: '2.0', method, params }); }
}

const pos = p => ({ line: p.line, character: p.character });
const rng = r => new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character);
const loc = l => l && new vscode.Location(vscode.Uri.parse(l.uri), rng(l.range));
const td = doc => ({ uri: doc.uri.toString() });

function startLanguageServer(context, python) {
	const py = typeof python === 'string' ? { cmd: python, args: [] } : python;
	const server = path.join(context.extensionPath, 'server', 'quill_lsp.py');
	const proc = cp.spawn(py.cmd, [...py.args, server], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
	const log = vscode.window.createOutputChannel('Quill Language Server');
	proc.stderr.on('data', d => log.append(d.toString()));
	proc.on('error', e => vscode.window.showWarningMessage(`Quill language server could not start (${py.cmd}): ${e.message}`));
	const diagnostics = vscode.languages.createDiagnosticCollection('quill');

	const rpc = new Rpc(proc, (method, p) => {
		if (method === 'textDocument/publishDiagnostics') {
			diagnostics.set(vscode.Uri.parse(p.uri), p.diagnostics.map(d => {
				const x = new vscode.Diagnostic(rng(d.range), d.message, vscode.DiagnosticSeverity.Error);
				x.source = 'quill'; return x;
			}));
		}
	});

	const folders = (vscode.workspace.workspaceFolders || []).map(f => ({ uri: f.uri.toString(), name: f.name }));
	rpc.request('initialize', { processId: process.pid, rootUri: folders[0] && folders[0].uri, workspaceFolders: folders, capabilities: {} })
		.then(() => rpc.notify('initialized', {}));

	const isQuill = d => d.languageId === 'quill' && d.uri.scheme === 'file';
	const open = d => isQuill(d) && rpc.notify('textDocument/didOpen', { textDocument: { uri: d.uri.toString(), languageId: 'quill', version: d.version, text: d.getText() } });
	vscode.workspace.textDocuments.forEach(open);

	const sel = { language: 'quill', scheme: 'file' };
	const kinds = [null, vscode.CompletionItemKind.Text, vscode.CompletionItemKind.Method, vscode.CompletionItemKind.Function, vscode.CompletionItemKind.Constructor,
		vscode.CompletionItemKind.Field, vscode.CompletionItemKind.Variable, vscode.CompletionItemKind.Class, vscode.CompletionItemKind.Interface, vscode.CompletionItemKind.Module,
		vscode.CompletionItemKind.Property, vscode.CompletionItemKind.Unit, vscode.CompletionItemKind.Value, vscode.CompletionItemKind.Enum, vscode.CompletionItemKind.Keyword, vscode.CompletionItemKind.Snippet];

	context.subscriptions.push(
		diagnostics, log,
		{ dispose: () => { try { rpc.request('shutdown', null); rpc.notify('exit', {}); proc.kill(); } catch (e) { /* already gone */ } } },
		vscode.workspace.onDidOpenTextDocument(open),
		vscode.workspace.onDidChangeTextDocument(e => isQuill(e.document) &&
			rpc.notify('textDocument/didChange', { textDocument: { uri: e.document.uri.toString(), version: e.document.version }, contentChanges: [{ text: e.document.getText() }] })),
		vscode.workspace.onDidSaveTextDocument(d => isQuill(d) && rpc.notify('textDocument/didSave', { textDocument: td(d) })),
		vscode.workspace.onDidCloseTextDocument(d => { if (isQuill(d)) { rpc.notify('textDocument/didClose', { textDocument: td(d) }); diagnostics.delete(d.uri); } }),

		vscode.languages.registerCompletionItemProvider(sel, {
			async provideCompletionItems(doc, p) {
				const r = await rpc.request('textDocument/completion', { textDocument: td(doc), position: pos(p) });
				return ((r && r.items) || []).map(i => {
					const it = new vscode.CompletionItem(i.label, kinds[i.kind] || vscode.CompletionItemKind.Text);
					it.detail = i.detail; if (i.documentation) { it.documentation = i.documentation; }
					if (i.insertText) { it.insertText = i.insertTextFormat === 2 ? new vscode.SnippetString(i.insertText) : i.insertText; }
					return it;
				});
			}
		}, '.'),
		vscode.languages.registerHoverProvider(sel, {
			async provideHover(doc, p) {
				const r = await rpc.request('textDocument/hover', { textDocument: td(doc), position: pos(p) });
				return r ? new vscode.Hover(new vscode.MarkdownString(r.contents.value), r.range && rng(r.range)) : undefined;
			}
		}),
		vscode.languages.registerDefinitionProvider(sel, {
			async provideDefinition(doc, p) { return loc(await rpc.request('textDocument/definition', { textDocument: td(doc), position: pos(p) })); }
		}),
		vscode.languages.registerDocumentSymbolProvider(sel, {
			async provideDocumentSymbols(doc) {
				const conv = s => { const x = new vscode.DocumentSymbol(s.name, s.detail || '', s.kind - 1, rng(s.range), rng(s.selectionRange)); x.children = (s.children || []).map(conv); return x; };
				return ((await rpc.request('textDocument/documentSymbol', { textDocument: td(doc) })) || []).map(conv);
			}
		}),
		vscode.languages.registerWorkspaceSymbolProvider({
			async provideWorkspaceSymbols(query) {
				return ((await rpc.request('workspace/symbol', { query })) || []).map(s => new vscode.SymbolInformation(s.name, s.kind - 1, s.containerName, loc(s.location)));
			}
		}),
		vscode.languages.registerSignatureHelpProvider(sel, {
			async provideSignatureHelp(doc, p) {
				const r = await rpc.request('textDocument/signatureHelp', { textDocument: td(doc), position: pos(p) });
				if (!r) { return undefined; }
				const h = new vscode.SignatureHelp();
				h.signatures = r.signatures.map(s => { const x = new vscode.SignatureInformation(s.label); x.parameters = (s.parameters || []).map(q => new vscode.ParameterInformation(q.label)); return x; });
				h.activeSignature = r.activeSignature || 0; h.activeParameter = r.activeParameter || 0;
				return h;
			}
		}, '(', ',')
	);
}

module.exports = { startLanguageServer };
