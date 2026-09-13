const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

// Run before Jest loads/transforms the generated wrapper. Compilation failure
// aborts the suite; an older checked-in wrapper must never be a fallback.
module.exports = async function compileSubscription() {
    console.log('Compiling current contracts/subscription.tact (no artifact cache)');
    execFileSync(process.execPath, [
        require.resolve('@tact-lang/compiler/bin/tact.js'),
        '--config', 'tact.config.json', '--project', 'subscription',
    ], { cwd: path.resolve(__dirname, '..'), stdio: 'inherit' });

    // Match the existing package.json postbuild workaround: Tact emits the
    // built-in and contract-specific "Access denied" under the same TS key.
    // Only the reverse error-map label changes; bytecode is untouched.
    const wrapper = path.resolve(__dirname, '../wrappers/subscription_Subscription.ts');
    const source = fs.readFileSync(wrapper, 'utf8');
    fs.writeFileSync(wrapper, source.replace(
        '"Access denied": 49469', '"Access denied (owner)": 49469'
    ).replace(/[ \t]+$/gm, ''));
};
