import './ton-buffer';
import { beginCell, Cell, loadMessage, storeMessage } from '@ton/core';

export function commentBoc(memo: string): string {
  return beginCell().storeUint(0, 32).storeStringTail(memo).endCell().toBoc().toString('base64');
}

// TEP-467: this is a MESSAGE hash for RPC lookup, never a transaction hash.
export function normalizedMessageHash(boc: string): string {
  const message = loadMessage(Cell.fromBase64(boc).beginParse());
  if (message.info.type !== 'external-in') throw new Error('Expected an external-in message');
  return beginCell().store(storeMessage({
    ...message, init: null,
    info: { ...message.info, src: undefined, importFee: 0n },
  }, { forceRef: true })).endCell().hash().toString('hex');
}
