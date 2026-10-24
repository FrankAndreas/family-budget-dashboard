import { useRememberedOpen } from '../useRememberedOpen';

interface Props {
    // Remembers whether the section is open, in this browser
    id: string;
    title: string;
    children: React.ReactNode;
}

// A Settings section that folds (issue #89): on a phone they start folded, so Settings is a short list of headings;
// on a wider screen they start open
export default function Section({ id, title, children }: Props) {
    const { open, toggle } = useRememberedOpen(`settings.section.${id}`);
    return (
        <details open={open} onToggle={toggle} className="glass-card group">
            <summary className="p-4 sm:p-6 cursor-pointer list-none flex justify-between items-center gap-3 [&::-webkit-details-marker]:hidden">
                <h2 className="text-xl font-bold">{title}</h2>
                <span aria-hidden="true" className="text-2xl text-slate-400 transition-transform group-open:rotate-90">›</span>
            </summary>
            <div className="px-4 pb-4 sm:px-6 sm:pb-6">{children}</div>
        </details>
    );
}
