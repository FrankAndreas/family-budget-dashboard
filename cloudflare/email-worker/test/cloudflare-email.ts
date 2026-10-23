// Stand-in for the workerd module 'cloudflare:email' in tests
export class EmailMessage {
    constructor(
        readonly from: string,
        readonly to: string,
        readonly raw: string,
    ) {}
}
