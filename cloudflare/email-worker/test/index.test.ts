import { describe, expect, it, vi } from 'vitest';
import { AUTHSERV_ID, deliver, dmarcPassed, type Env, type InboundMessage } from '../src/index';

const env: Env = {
    APP_URL: 'https://budget-inbound.example.ch/',
    INBOUND_SECRET: 's3cret',
    CF_ACCESS_CLIENT_ID: 'id.access',
    CF_ACCESS_CLIENT_SECRET: 'access-secret',
};

// What Cloudflare put above a GMX mail in the test of 2026-10-23 (addresses replaced)
const CLOUDFLARE_PASS =
    'ARC-Authentication-Results: i=1; mx.cloudflare.net;\r\n' +
    '\tdkim=pass header.i=@example.ch header.s=s31663417 header.b=rCBj+qdn;\r\n' +
    '\tdmarc=pass header.from=example.ch policy.dmarc=quarantine;\r\n' +
    '\tspf=pass (mx.cloudflare.net: domain of mama@example.ch designates 192.0.2.20 as permitted sender)\r\n' +
    ' smtp.mailfrom=mama@example.ch; arc=none smtp.remote-ip=192.0.2.20\r\n';
const MAIL = 'From: Mama <mama@example.ch>\r\nTo: invoice@example.ch\r\nSubject: WG: Bestellung\r\n\r\nTotal 12.50\r\n';

const raw = (top: string, mail = MAIL) => top + mail;

function message(text: string, forward = vi.fn(async () => undefined)) {
    const setReject = vi.fn();
    const headerBlock = text.split('\r\n\r\n')[0];
    const msg: InboundMessage = {
        from: 'mama@example.ch',
        to: 'invoice@example.ch',
        raw: new Response(text).body!,
        rawSize: text.length,
        headers: new Headers({ Subject: 'WG: Bestellung', From: headerBlock.match(/^From: (.*)$/m)?.[1] ?? '' }),
        setReject,
        forward,
    };
    return { msg, setReject, forward };
}

const ok = (async () => new Response('{"status":"stored"}', { status: 200 })) as unknown as typeof fetch;

describe('dmarcPassed', () => {
    const header = (text: string) => text.split('\r\n\r\n')[0];

    it('is Cloudflare', () => expect(AUTHSERV_ID).toBe('mx.cloudflare.net'));

    it('accepts dmarc=pass from Cloudflare for the From domain', () => {
        expect(dmarcPassed(header(raw(CLOUDFLARE_PASS)), 'Mama <mama@example.ch>')).toBe(true);
    });

    it('also reads a plain Authentication-Results header from Cloudflare', () => {
        const plain = 'Authentication-Results: mx.cloudflare.net; dmarc=pass header.from=example.ch\r\n';
        expect(dmarcPassed(header(raw(plain)), 'mama@example.ch')).toBe(true);
    });

    it.each(['fail', 'none', 'temperror'])('rejects dmarc=%s', (result) => {
        const top = CLOUDFLARE_PASS.replace('dmarc=pass', `dmarc=${result}`);
        expect(dmarcPassed(header(raw(top)), 'mama@example.ch')).toBe(false);
    });

    it('rejects a mail without any result', () => {
        expect(dmarcPassed(header(MAIL), 'mama@example.ch')).toBe(false);
    });

    it('rejects a pass for another domain than the From address', () => {
        expect(dmarcPassed(header(raw(CLOUDFLARE_PASS)), 'mama@other.example')).toBe(false);
    });

    it('rejects a result of another server on top', () => {
        const other = CLOUDFLARE_PASS.replace('mx.cloudflare.net;\r\n', 'mx.evil.example;\r\n');
        expect(dmarcPassed(header(raw(other)), 'mama@example.ch')).toBe(false);
    });

    it('ignores a forged pass below the result Cloudflare added', () => {
        const failing = CLOUDFLARE_PASS.replace('dmarc=pass', 'dmarc=fail');
        const forged = 'ARC-Authentication-Results: i=1; mx.cloudflare.net; dmarc=pass header.from=example.ch\r\n';
        expect(dmarcPassed(header(raw(failing, forged + MAIL)), 'mama@example.ch')).toBe(false);
    });

    it('does not take a pass hidden in another header', () => {
        const hidden = 'X-Note: mx.cloudflare.net; dmarc=pass header.from=example.ch\r\n';
        expect(dmarcPassed(header(raw(hidden)), 'mama@example.ch')).toBe(false);
    });
});

describe('deliver', () => {
    it('posts an authentic mail with the secrets', async () => {
        const fetchMock = vi.fn(ok);
        const text = raw(CLOUDFLARE_PASS);
        const { msg, setReject } = message(text);
        await deliver(msg, env, fetchMock as unknown as typeof fetch);

        expect(fetchMock).toHaveBeenCalledOnce();
        const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('https://budget-inbound.example.ch/api/v1/inbound');
        const headers = init.headers as Record<string, string>;
        expect(headers['Content-Type']).toBe('message/rfc822');
        expect(headers['X-Inbound-Secret']).toBe('s3cret');
        expect(headers['CF-Access-Client-Id']).toBe('id.access');
        expect(headers['CF-Access-Client-Secret']).toBe('access-secret');
        expect(init.redirect).toBe('manual');
        expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(text);
        expect(setReject).not.toHaveBeenCalled();
    });

    it('rejects a mail that is not authentic, without posting it', async () => {
        const fetchMock = vi.fn(ok);
        const { msg, setReject, forward } = message(raw(CLOUDFLARE_PASS.replace('dmarc=pass', 'dmarc=fail')));
        await deliver(msg, { ...env, FALLBACK_ADDRESS: 'papa@example.ch' }, fetchMock as unknown as typeof fetch);
        expect(fetchMock).not.toHaveBeenCalled();
        expect(forward).not.toHaveBeenCalled();
        expect(setReject).toHaveBeenCalledWith('Absender nicht bestätigt');
    });

    it('rejects a mail from an unregistered sender, never to the fallback', async () => {
        const { msg, setReject, forward } = message(raw(CLOUDFLARE_PASS));
        const refused = (async () => new Response(null, { status: 403 })) as unknown as typeof fetch;
        await deliver(msg, { ...env, FALLBACK_ADDRESS: 'papa@example.ch' }, refused);
        expect(forward).not.toHaveBeenCalled();
        expect(setReject).toHaveBeenCalledWith('Nicht angenommen');
    });

    // 302: Cloudflare Access redirects to its login page when the service token is wrong
    it.each([500, 413, 401, 302])('rejects the mail when the app answers %i (no fallback)', async (status) => {
        const { msg, setReject } = message(raw(CLOUDFLARE_PASS));
        await deliver(msg, env, (async () => new Response(null, { status })) as unknown as typeof fetch);
        expect(setReject).toHaveBeenCalledOnce();
    });

    it('rejects the mail when the app is unreachable', async () => {
        const { msg, setReject } = message(raw(CLOUDFLARE_PASS));
        const failing = async () => {
            throw new Error('connection refused');
        };
        await deliver(msg, env, failing as unknown as typeof fetch);
        expect(setReject).toHaveBeenCalledWith(expect.stringContaining('nicht erreichbar'));
    });

    it('rejects the mail without calling out when APP_URL is not set', async () => {
        const fetchMock = vi.fn(ok);
        const { msg, setReject } = message(raw(CLOUDFLARE_PASS));
        await deliver(msg, { ...env, APP_URL: '' }, fetchMock as unknown as typeof fetch);
        expect(fetchMock).not.toHaveBeenCalled();
        expect(setReject).toHaveBeenCalledWith(expect.stringContaining('APP_URL'));
    });

    describe('with a fallback address', () => {
        const withFallback: Env = { ...env, FALLBACK_ADDRESS: 'papa@example.ch' };
        const down = (async () => {
            throw new Error('connection refused');
        }) as unknown as typeof fetch;

        it.each([
            ['unreachable', down],
            ['answering 502', (async () => new Response(null, { status: 502 })) as unknown as typeof fetch],
            ['answering 413', (async () => new Response(null, { status: 413 })) as unknown as typeof fetch],
        ])('forwards instead of rejecting when the app is %s', async (_case, fetchImpl) => {
            const { msg, setReject, forward } = message(raw(CLOUDFLARE_PASS));
            await deliver(msg, withFallback, fetchImpl);
            expect(setReject).not.toHaveBeenCalled();
            expect(forward).toHaveBeenCalledOnce();
            const [to, headers] = forward.mock.calls[0] as unknown as [string, Headers];
            expect(to).toBe('papa@example.ch');
            expect(headers.get('X-Family-Budget-Error')).toContain('Family Budget');
        });

        it('does not forward a mail the app took', async () => {
            const { msg, setReject, forward } = message(raw(CLOUDFLARE_PASS));
            await deliver(msg, withFallback, ok);
            expect(forward).not.toHaveBeenCalled();
            expect(setReject).not.toHaveBeenCalled();
        });

        it('rejects the mail when forwarding fails too', async () => {
            const { msg, setReject } = message(
                raw(CLOUDFLARE_PASS),
                vi.fn(async () => {
                    throw new Error('destination address not verified');
                }),
            );
            await deliver(msg, withFallback, down);
            expect(setReject).toHaveBeenCalledWith(expect.stringContaining('Weiterleitung fehlgeschlagen'));
        });

        it('sends a note to the fallback address when the binding is there', async () => {
            const send = vi.fn(async () => undefined);
            const { msg, forward } = message(raw(CLOUDFLARE_PASS));
            await deliver(msg, { ...withFallback, NOTIFY: { send } }, down);
            expect(forward).toHaveBeenCalledOnce();
            expect(send).toHaveBeenCalledOnce();
            const [note] = send.mock.calls[0] as unknown as [{ from: string; to: string; raw: string }];
            expect(note.from).toBe('invoice@example.ch');
            expect(note.to).toBe('papa@example.ch');
        });
    });
});
