import { CompilerConfig } from '@ton/blueprint';

export const compile: CompilerConfig = {
    lang: 'tact',
    target: 'contracts/subscription.tact',
    options: {
        debug: true,
    },
};

