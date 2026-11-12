// Tokenizes Quill source with the real TextMate engine and checks scopes.
// Run: NODE_PATH=<vscode>/node_modules node tests/test_grammar.js
const fs = require('fs'), path = require('path');
const vsctm = require('vscode-textmate'), onig = require('vscode-oniguruma');
const wasm = fs.readFileSync(require.resolve('vscode-oniguruma/release/onig.wasm')).buffer;
const lib = onig.loadWASM(wasm).then(() => ({
	createOnigScanner: s => new onig.OnigScanner(s), createOnigString: s => new onig.OnigString(s) }));
const reg = new vsctm.Registry({ onigLib: lib, loadGrammar: async () =>
	vsctm.parseRawGrammar(fs.readFileSync(path.join(__dirname, '../extensions/quill/syntaxes/quill.tmLanguage.json'), 'utf8'), 'g.json') });

const SRC = `bring shapes.round as r
native link "m"

abstract class Shape < Base, Named[T]:
    private weak owner: Owner
    def area(self, scale: float, items: List[int]) -> float:
        total: int = 0x1F + 2
        s = "a\\n\\q"
        d = new Dog("Rex")
        d.fetch(3)
        self.name = self.size
        if x instanceof Dog and not y:  # note
            return MAX_SIZE
        return Math.sqrt(2.5)
`;
const expect = [
	['bring', 'keyword.control.import'], ['shapes.round', 'entity.name.namespace'], ['r', 'entity.name.namespace.alias'],
	['native', 'keyword.control.directive'], ['link', 'keyword.other.directive'],
	['abstract', 'storage.modifier'], ['Shape', 'entity.name.type.class'], ['Base', 'entity.other.inherited-class'],
	['Named', 'entity.other.inherited-class'], ['T', 'entity.name.type.parameter'],
	['owner', 'variable.other.readwrite'], ['Owner', 'entity.name.type'],
	['area', 'entity.name.function'], ['scale', 'variable.parameter'], ['float', 'support.type.primitive'],
	['List', 'entity.name.type'], ['->', 'keyword.operator.arrow'],
	['0x1F', 'constant.numeric.hex'], ['\\n', 'constant.character.escape'], ['\\q', 'invalid.illegal.escape'],
	['new', 'keyword.operator.new'], ['Dog', 'entity.name.type'], ['fetch', 'entity.name.function.member'],
	['name', 'variable.other.property'], ['instanceof', 'keyword.operator.word'], ['and', 'keyword.operator.word'],
	['# note', 'comment.line'], ['MAX_SIZE', 'variable.other.constant'], ['sqrt', 'entity.name.function.member'],
	['2.5', 'constant.numeric.float'], ['return', 'keyword.control'], ['self', 'variable.language'],
];
(async () => {
	const g = await reg.loadGrammar('source.quill');
	let stack = vsctm.INITIAL; const seen = [];
	SRC.split('\n').forEach(line => {
		const r = g.tokenizeLine(line, stack); stack = r.ruleStack;
		r.tokens.forEach(t => seen.push([line.slice(t.startIndex, t.endIndex).trim(), t.scopes]));
	});
	let bad = 0;
	for (const [text, scope] of expect) {
		const ok = seen.some(([t, sc]) => t === text && sc.some(s => s.startsWith(scope)));
		console.log((ok ? 'pass ' : 'FAIL ') + JSON.stringify(text) + ' -> ' + scope);
		if (!ok) { bad++; console.log('     got: ' + JSON.stringify(seen.filter(([t]) => t === text).map(x => x[1].slice(1)))); }
	}
	console.log(`\n${bad} failure(s)`); process.exit(bad ? 1 : 0);
})();
