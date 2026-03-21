struct SubscriptionData {
    tier: Int as uint8;
    expiresAt: Int as uint64;
}

message Withdraw {
    amount: Int as coins;
}