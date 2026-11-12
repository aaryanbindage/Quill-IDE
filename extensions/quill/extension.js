const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

let terminal;

function compiler(context) {
	const cfg = vscode.workspace.getConfiguration('quill');
	const configured = cfg.get('compilerPath');
	if (configured && fs.existsSync(configured)) { return configured; }
	return path.join(context.extensionPath, 'compiler', 'quill.py');
}

function term() {
	if (!terminal || terminal.exitStatus) { terminal = vscode.window.createTerminal('Quill'); }
	terminal.show(true);
	return terminal;
}

const q = s => `"${s.replace(/(["\\$`])/g, '\\$1')}"`;

async function activeQuillFile() {
	const ed = vscode.window.activeTextEditor;
	if (!ed || ed.document.languageId !== 'quill') {
		vscode.window.showWarningMessage('Open a .ql file first.');
		return undefined;
	}
	await ed.document.save();
	return ed.document.fileName;
}

function activate(context) {
	const py = () => vscode.workspace.getConfiguration('quill').get('python') || 'python3';
	const run = (sub, extra = '') => async () => {
		const file = await activeQuillFile();
		if (!file) { return; }
		term().sendText(`${py()} ${q(compiler(context))} ${sub} ${q(file)} ${extra}`.trim());
	};

	const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
	status.text = '$(play) Run';
	status.command = 'quill.run';
	status.tooltip = 'Run the current Quill file';
	const sync = () => {
		const ed = vscode.window.activeTextEditor;
		ed && ed.document.languageId === 'quill' ? status.show() : status.hide();
	};
	sync();

	context.subscriptions.push(
		status,
		vscode.window.onDidChangeActiveTextEditor(sync),
		vscode.commands.registerCommand('quill.run', run('run')),
		vscode.commands.registerCommand('quill.runChecked', run('run', '--check')),
		vscode.commands.registerCommand('quill.emit', run('emit')),
		vscode.commands.registerCommand('quill.hood', run('hood')),
		vscode.commands.registerCommand('quill.build', async () => {
			const file = await activeQuillFile();
			if (!file) { return; }
			const out = file.replace(/\.ql$/, '');
			term().sendText(`${py()} ${q(compiler(context))} build ${q(file)} -o ${q(out)} && echo "Built ${out}"`);
		}),
		vscode.commands.registerCommand('quill.newProject', async () => {
			const name = await vscode.window.showInputBox({ prompt: 'Project name' });
			if (!name) { return; }
			const dir = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, openLabel: 'Create here' });
			if (!dir || !dir[0]) { return; }
			term().sendText(`cd ${q(dir[0].fsPath)} && ${py()} ${q(compiler(context))} new ${q(name)}`);
		})
	);
}

function deactivate() {}
module.exports = { activate, deactivate };
