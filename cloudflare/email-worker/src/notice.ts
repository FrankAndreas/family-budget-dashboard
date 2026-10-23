// The note that goes to the fallback address next to the forwarded mail: forward() can't change
// the forwarded mail itself, only add X- headers nobody sees.

function base64(text: string): string {
    const bytes = new TextEncoder().encode(text);
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
}

// RFC 2047 encoded word, so umlauts survive in the subject
function encodeHeader(text: string): string {
    return `=?UTF-8?B?${base64(text)}?=`;
}

export interface NoticeInput {
    from: string; // an address of the routed domain, e.g. the one the mail was sent to
    to: string;
    reason: string;
    originalFrom: string;
    originalSubject: string;
    appUrl: string;
    date?: Date;
    id?: string;
}

/** The raw MIME text of the note. */
export function buildNotice(input: NoticeInput): string {
    const domain = input.from.split('@')[1] ?? 'localhost';
    const id = input.id ?? crypto.randomUUID();
    const app = input.appUrl || 'Family Budget';
    const body = [
        `Die Budget-App (${app}) war nicht erreichbar oder hat eine Beleg-Mail nicht angenommen.`,
        '',
        `Grund: ${input.reason}`,
        '',
        'Die Mail kommt dir separat weitergeleitet zu:',
        `  Von:     ${input.originalFrom}`,
        `  Betreff: ${input.originalSubject || '(ohne Betreff)'}`,
        '',
        `Leite sie an ${input.from} weiter, sobald die App wieder läuft. Dann landet sie dort wie gewohnt.`,
    ].join('\r\n');
    const lines = base64(body).match(/.{1,76}/g) ?? [];
    return [
        `From: Belege <${input.from}>`,
        `To: ${input.to}`,
        `Subject: ${encodeHeader('Belege: Mail weitergeleitet, App nicht erreichbar')}`,
        `Message-ID: <${id}@${domain}>`,
        `Date: ${(input.date ?? new Date()).toUTCString()}`,
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=utf-8',
        'Content-Transfer-Encoding: base64',
        '',
        ...lines,
        '',
    ].join('\r\n');
}
