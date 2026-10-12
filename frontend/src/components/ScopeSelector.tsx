import type { Scope } from '../family';

interface ScopeSelectorProps {
    scopes: Scope[];
    value: string;
    onChange: (key: string) => void;
}

// Switch between the household and children with own allowance; hidden when there is nothing to choose
export default function ScopeSelector({ scopes, value, onChange }: ScopeSelectorProps) {
    if (scopes.length <= 1) return null;

    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
            aria-label="Whose money to show"
        >
            {scopes.map(scope => (
                <option key={scope.key} value={scope.key}>{scope.label}</option>
            ))}
        </select>
    );
}
