// Visible text must come from src/locales (issue #50): reports text written directly in the components.
// Checks JSX text, the attributes people see or hear, string arguments of confirm/alert/setError/errorMessage,
// and label/text/title/placeholder properties.
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'src');
// Every component and page
const CHECKED = fs.readdirSync(SRC, { recursive: true }).filter(file => file.endsWith('.tsx')).sort();
const ATTRIBUTES = new Set(['placeholder', 'aria-label', 'title', 'alt', 'label']);
const CALLS = new Set(['confirm', 'alert', 'setError', 'errorMessage', 'setMessage']);
const PROPERTIES = new Set(['label', 'text', 'title', 'placeholder']);
const WORD = /[A-Za-zÄÖÜäöü]{2,}/;

const problems = [];
for (const file of CHECKED) {
    const full = path.join(SRC, file);
    const source = ts.createSourceFile(full, fs.readFileSync(full, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const report = (node, text) => {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart());
        problems.push(`${file}:${line + 1}: ${text.trim().replace(/\s+/g, ' ').slice(0, 70)}`);
    };
    const literal = (node) => {
        if (!node) return null;
        if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
        if (ts.isTemplateExpression(node)) return [node.head.text, ...node.templateSpans.map(s => s.literal.text)].join(' ');
        return null;
    };
    const visit = (node) => {
        if (ts.isJsxText(node) && WORD.test(node.text)) report(node, node.text);
        if (ts.isJsxAttribute(node) && ATTRIBUTES.has(node.name.getText()) && node.initializer) {
            const value = ts.isJsxExpression(node.initializer) ? node.initializer.expression : node.initializer;
            const text = literal(value);
            if (text && WORD.test(text)) report(node, text);
        }
        if (ts.isJsxExpression(node) && !ts.isJsxAttribute(node.parent)) {
            const text = literal(node.expression);
            if (text && WORD.test(text)) report(node, text);
        }
        if (ts.isCallExpression(node) && CALLS.has(node.expression.getText().split('.').pop())) {
            for (const arg of node.arguments) {
                const text = literal(arg);
                if (text && WORD.test(text)) report(arg, text);
            }
        }
        if (ts.isPropertyAssignment(node) && PROPERTIES.has(node.name.getText())) {
            const text = literal(node.initializer);
            if (text && WORD.test(text)) report(node, text);
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
}
if (problems.length) {
    console.error(`Text outside src/locales (use t()):\n${problems.join('\n')}`);
    process.exit(1);
}
