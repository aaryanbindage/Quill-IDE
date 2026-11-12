const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const { startLanguageServer } = require('./client');

const cp = require('child_process');

let pythonCache;

// The interpreter that runs the compiler and language server. Honours the quill.python
// setting; otherwise tries python3, python and (Windows) py -3 and keeps the first that works.
function detectPython() {
	const configured = vscode.workspace.getConfiguration('quill').get('python');
	if (configured) { return { cmd: configured, args: [] }; }
	if (pythonCache) { return pythonCache; }
	const candidates = process.platform === 'win32'
		? [['py', '-3'], ['python'], ['python3']]
		: [['python3'], ['python']];
	for (const [cmd, ...args] of candidates) {
		const r = cp.spawnSync(cmd, [...args, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'], { timeout: 8000 });
		if (r.status === 0) { return (pythonCache = { cmd, args }); }
	}
	return { cmd: candidates[0][0], args: candidates[0].slice(1) };
}

function compiler(context) {
	const configured = vscode.workspace.getConfiguration('quill').get('compilerPath');
	if (configured && fs.existsSync(configured)) { return configured; }
	return path.join(context.extensionPath, 'compiler', 'quill.py');
}

// Run a command in the integrated terminal. ShellExecution quotes every argument for the
// shell in use (bash, zsh, PowerShell or cmd), so paths with spaces work on every platform.
async function runInTerminal(name, command, args, cwd) {
	const strong = a => ({ value: a, quoting: vscode.ShellQuoting.Strong });
	const exec = new vscode.ShellExecution(strong(command), args.map(strong), cwd ? { cwd } : undefined);
	const task = new vscode.Task({ type: 'quill' }, vscode.TaskScope.Workspace, name, 'quill', exec);
	task.presentationOptions = { reveal: vscode.TaskRevealKind.Always, panel: vscode.TaskPanelKind.Shared, clear: true, focus: false };
	await vscode.tasks.executeTask(task);
}

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
	const quill = (name, sub, extra = []) => async () => {
		const file = await activeQuillFile();
		if (!file) { return; }
		const py = detectPython();
		await runInTerminal(name, py.cmd, [...py.args, compiler(context), sub, file, ...extra], path.dirname(file));
	};

	const py0 = detectPython();
	startLanguageServer(context, py0);

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
		vscode.commands.registerCommand('quill.run', quill('Quill: run', 'run')),
		vscode.commands.registerCommand('quill.runChecked', quill('Quill: run (memory check)', 'run', ['--check'])),
		vscode.commands.registerCommand('quill.emit', quill('Quill: LLVM IR', 'emit')),
		vscode.commands.registerCommand('quill.hood', quill('Quill: hood', 'hood')),
		vscode.commands.registerCommand('quill.build', async () => {
			const file = await activeQuillFile();
			if (!file) { return; }
			const out = file.replace(/\.ql$/, process.platform === 'win32' ? '.exe' : '');
			const py = detectPython();
			await runInTerminal('Quill: build', py.cmd, [...py.args, compiler(context), 'build', file, '-o', out], path.dirname(file));
		}),
		vscode.commands.registerCommand('quill.newProject', async () => {
			const name = await vscode.window.showInputBox({ prompt: 'Project name' });
			if (!name) { return; }
			const dir = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, openLabel: 'Create here' });
			if (!dir || !dir[0]) { return; }
			const py = detectPython();
			await runInTerminal('Quill: new project', py.cmd, [...py.args, compiler(context), 'new', name], dir[0].fsPath);
		})
	);
}

function deactivate() {}
module.exports = { activate, deactivate };
