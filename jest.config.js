module.exports = {
    preset: "ts-jest",
    testEnvironment: "node",
    // SubscriptionTolk.spec.ts is excluded: it targets a PLANNED contract
    // interface (sendWithdraw / exit codes 102-103) that does not exist in
    // tongpt-subscription/contracts/subscription.tolk (ops: Subscribe,
    // ChangeOwner, FeeNotice only) and deploys a mock empty code cell, so it
    // can neither compile nor exercise real TVM logic. Re-enable once the Tolk
    // contract implements withdrawal and a compiled code cell is wired in.
    // (See docs/REMEDIATION_REGISTER.md TOLK-001..003; on-chain polling is
    // gated OFF at launch per docs/FINAL_FIX_REPORT.md.)
    testPathIgnorePatterns: ["/node_modules/", "/dist/", "SubscriptionTolk.spec.ts"],
    // Keep the haste crawl away from huge non-JS trees (python venv, frontends).
    modulePathIgnorePatterns: ["<rootDir>/myenv", "<rootDir>/miniapp", "<rootDir>/miniapp-v2", "<rootDir>/TonGPT", "<rootDir>/logs", "<rootDir>/data", "<rootDir>/build"],
};
