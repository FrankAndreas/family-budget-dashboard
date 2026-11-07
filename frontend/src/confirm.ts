// The app's own question before something that can't be undone, instead of the browser's confirm(): styled like the
// app, a red button for deleting, Escape or the backdrop cancels. `await ask(...)` from anywhere; <ConfirmHost /> is
// mounted once (App)
export interface Options {
    // The button that goes ahead: "Delete" unless given
    confirmLabel?: string;
    // Red for deleting and removing (the default); false for other questions
    danger?: boolean;
}
export interface ConfirmRequest extends Options { message: string; resolve: (yes: boolean) => void }

let show: ((request: ConfirmRequest) => void) | null = null;

// The dialog (components/ConfirmDialog) registers itself; the returned function unregisters it
export function register(open: (request: ConfirmRequest) => void): () => void {
    show = open;
    return () => { if (show === open) show = null; };
}

export function ask(message: string, options: Options = {}): Promise<boolean> {
    // Not mounted (should not happen): the browser's own question still protects the data
    if (!show) return Promise.resolve(window.confirm(message));
    const open = show;
    return new Promise(resolve => open({ message, ...options, resolve }));
}

