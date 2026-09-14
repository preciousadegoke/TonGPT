import { Buffer } from 'buffer';
// @ton/core uses Buffer internally; provide the browser implementation first.
globalThis.Buffer ??= Buffer;
