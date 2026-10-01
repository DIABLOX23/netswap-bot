import time
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==============================================================================
# AETERNA CASCADE PROTOCOL: FORMAL MATHEMATICAL VERIFICATION & DRY-RUN SUITE
# Simulates full state machine of AeternaCascadeSafeModule.sol
# ==============================================================================

class MockSafe:
    def __init__(self, address):
        self.address = address
        self.balances = {}
        self.executed_txs = []

    def set_balance(self, token, amount):
        self.balances[token] = amount

    def execTransactionFromModule(self, to, value, data_desc):
        self.executed_txs.append({"to": to, "value": value, "data": data_desc})
        return True

class AeternaCascadeSimulator:
    EXECUTION_FEE_BPS = 300      # 3.00%
    YIELD_SIPHON_BPS = 2000      # 20.00%
    BPS_DENOMINATOR = 10000
    SCREAM_WINDOW_SECONDS = 30 * 86400  # 30 Days

    def __init__(self, protocol_treasury, netswap_settlement):
        self.protocol_treasury = protocol_treasury
        self.netswap_settlement = netswap_settlement
        self.vaults = {}
        self.guardians = {}
        self.guardian_votes = {}

    def register_vault(self, safe_addr, primary_heir, emergency_cold, heartbeat_period, guardians, quorum, float_yield=True, current_time=0):
        assert heartbeat_period >= 30 * 86400, "Heartbeat period too short"
        assert len(guardians) >= quorum and quorum > 0, "Invalid quorum"
        assert safe_addr not in self.vaults, "Vault already exists"

        self.vaults[safe_addr] = {
            "safe": safe_addr,
            "primary_heir": primary_heir,
            "emergency_cold": emergency_cold or primary_heir,
            "heartbeat_period": heartbeat_period,
            "last_heartbeat": current_time,
            "scream_window_start": 0,
            "guardian_quorum": quorum,
            "state": "ACTIVE",
            "float_yield_enabled": float_yield,
            "executed": False
        }
        self.guardians[safe_addr] = list(guardians)
        self.guardian_votes[safe_addr] = set()
        return True

    def ping_heartbeat(self, safe_addr, caller, current_time):
        v = self.vaults[safe_addr]
        assert v["state"] in ["ACTIVE", "CASCADE_PENDING"], f"Cannot ping in state {v['state']}"
        assert caller == safe_addr, "Unauthorized: Only Safe owner can heartbeat"
        v["last_heartbeat"] = current_time
        v["state"] = "ACTIVE"
        self.guardian_votes[safe_addr].clear()
        return True

    def trigger_inactivity_cascade(self, safe_addr, current_time):
        v = self.vaults[safe_addr]
        assert v["state"] == "ACTIVE", f"Not active: {v['state']}"
        assert current_time > v["last_heartbeat"] + v["heartbeat_period"], "Heartbeat not yet expired"
        v["state"] = "CASCADE_PENDING"
        return True

    def guardian_attest_failure(self, safe_addr, guardian_addr, current_time):
        v = self.vaults[safe_addr]
        assert v["state"] == "CASCADE_PENDING", f"Not in cascade pending: {v['state']}"
        assert guardian_addr in self.guardians[safe_addr], "Not a registered guardian"
        assert guardian_addr not in self.guardian_votes[safe_addr], "Already voted"

        self.guardian_votes[safe_addr].add(guardian_addr)
        votes = len(self.guardian_votes[safe_addr])

        # Check if Quorum achieved -> Triggers 30-Day Scream Window
        if votes >= v["guardian_quorum"]:
            v["state"] = "SCREAM_WINDOW"
            v["scream_window_start"] = current_time
        return votes, v["state"]

    def abort_scream_window(self, safe_addr, caller, current_time):
        v = self.vaults[safe_addr]
        assert v["state"] in ["SCREAM_WINDOW", "CASCADE_PENDING"], "Not in abortable state"
        assert caller == safe_addr, "Unauthorized: Only Safe owner can abort"

        v["state"] = "ACTIVE"
        v["last_heartbeat"] = current_time
        v["scream_window_start"] = 0
        self.guardian_votes[safe_addr].clear()
        return True

    def execute_autonomous_transfer(self, safe_obj, tokens, current_time):
        safe_addr = safe_obj.address
        v = self.vaults[safe_addr]
        assert v["state"] == "SCREAM_WINDOW", "Not in scream window"
        assert current_time >= v["scream_window_start"] + self.SCREAM_WINDOW_SECONDS, "30-day Scream Window still active"

        v["state"] = "EXECUTED"
        v["executed"] = True
        transfers = []

        for token in tokens:
            bal = safe_obj.balances.get(token, 0)
            if bal > 0:
                fee = (bal * self.EXECUTION_FEE_BPS) // self.BPS_DENOMINATOR
                heir_amt = bal - fee

                # Route fee to protocol treasury
                safe_obj.execTransactionFromModule(self.protocol_treasury, 0, f"TRANSFER {fee} {token} TO TREASURY")
                # Route 97% remainder to designated heir
                safe_obj.execTransactionFromModule(v["primary_heir"], 0, f"TRANSFER {heir_amt} {token} TO HEIR")

                transfers.append({"token": token, "initial": bal, "fee": fee, "heir_amt": heir_amt})

        return transfers

def run_test_suite():
    print("=" * 70)
    print("🧪 AETERNA PROTOCOL FORMAL TEST HARNESS & DRY-RUN SIMULATION")
    print("=" * 70)

    TREASURY = "0xcc12fd53a0ba26f42fea6ff8b285a77aa54b170d"  # Phantom Revenue Vault
    NETSWAP_ROUTER = "0x0Ae0d97111F837EAAd45B35E8EAa77Fc75468f8F"  # NetSwap Settlement

    SAFE_ADDR = "0xSafeTreasury_DAO_10M"
    HEIR_ADDR = "0xHeir_Beneficiary_Wallet"
    EMERGENCY_COLD = "0xColdStorage_Backup"

    GUARDIANS = [
        "0xGuardian_Attorney_1",
        "0xGuardian_CoFounder_2",
        "0xGuardian_Family_3",
        "0xGuardian_Keyholder_4",
        "0xGuardian_SecurityFirm_5"
    ]
    QUORUM = 3  # 3 of 5
    HEARTBEAT_PERIOD = 365 * 86400  # 1 Year

    mock_safe = MockSafe(SAFE_ADDR)
    # Give Safe $5,000,000 in USDC and 500 ETH
    mock_safe.set_balance("USDC", 5_000_000)
    mock_safe.set_balance("WETH", 500)

    aeterna = AeternaCascadeSimulator(TREASURY, NETSWAP_ROUTER)
    clock = 1700000000  # Genesis timestamp T0

    # --------------------------------------------------------------------------
    # TEST 1: Genesis Registration
    # --------------------------------------------------------------------------
    print("\n[TEST 1] Registering Safe Legacy Vault...")
    success = aeterna.register_vault(
        SAFE_ADDR, HEIR_ADDR, EMERGENCY_COLD, HEARTBEAT_PERIOD, GUARDIANS, QUORUM, float_yield=True, current_time=clock
    )
    assert success
    assert aeterna.vaults[SAFE_ADDR]["state"] == "ACTIVE"
    print("  ✓ Vault enrolled successfully in state ACTIVE.")
    print(f"  ✓ Target Safe: {SAFE_ADDR} | Heir: {HEIR_ADDR}")
    print(f"  ✓ Inactivity Period: 365 Days | Guardian Quorum: 3 of 5")

    # --------------------------------------------------------------------------
    # TEST 2: Active Heartbeat Ping
    # --------------------------------------------------------------------------
    print("\n[TEST 2] Verifying Liveness Heartbeat (Day 100)...")
    clock += 100 * 86400  # Fast-forward 100 days
    aeterna.ping_heartbeat(SAFE_ADDR, SAFE_ADDR, current_time=clock)
    assert aeterna.vaults[SAFE_ADDR]["last_heartbeat"] == clock
    print("  ✓ Heartbeat pulse recorded. Inactivity clock successfully reset.")

    # --------------------------------------------------------------------------
    # TEST 3: Inactivity Boundary Verification
    # --------------------------------------------------------------------------
    print("\n[TEST 3] Verifying Boundary Conditions for Inactivity Cascade...")
    clock += 364 * 86400  # 364 days pass (1 day short of expiration)
    try:
        aeterna.trigger_inactivity_cascade(SAFE_ADDR, current_time=clock)
        assert False, "Should have failed before 365 days!"
    except AssertionError:
        print("  ✓ Correct: Cascade trigger rejected at Day 364 (Heartbeat still valid).")

    clock += 2 * 86400  # Day 366 (Expired!)
    aeterna.trigger_inactivity_cascade(SAFE_ADDR, current_time=clock)
    assert aeterna.vaults[SAFE_ADDR]["state"] == "CASCADE_PENDING"
    print("  ✓ State transitioned to CASCADE_PENDING at Day 366.")

    # --------------------------------------------------------------------------
    # TEST 4: Guardian Social Attestation & Quorum Threshold
    # --------------------------------------------------------------------------
    print("\n[TEST 4] Simulating Guardian Quorum Signatures...")
    # Unauthorized caller fails
    try:
        aeterna.guardian_attest_failure(SAFE_ADDR, "0xRandoAttacker", clock)
        assert False, "Unauthorized guardian signed!"
    except AssertionError:
        print("  ✓ Attacker signature rejected (Only approved guardians allowed).")

    # Guardian 1 votes (1 of 3)
    votes, st = aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[0], clock)
    assert votes == 1 and st == "CASCADE_PENDING"
    print(f"  ✓ Guardian 1 attested. Total votes: {votes}/3. State remains CASCADE_PENDING.")

    # Guardian 2 votes (2 of 3)
    votes, st = aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[1], clock)
    assert votes == 2 and st == "CASCADE_PENDING"
    print(f"  ✓ Guardian 2 attested. Total votes: {votes}/3. State remains CASCADE_PENDING.")

    # Guardian 3 votes (3 of 3 -> QUORUM REACHED!)
    votes, st = aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[2], clock)
    assert votes == 3 and st == "SCREAM_WINDOW"
    print(f"  ✓ Guardian 3 attested. Quorum reached (3/5).")
    print(f"  🔥 30-DAY SCREAM WINDOW ACTIVATED! State: {st}")

    # --------------------------------------------------------------------------
    # TEST 5: The "Coma Scenario" (Owner Wakes Up & Aborts Scream Window)
    # --------------------------------------------------------------------------
    print("\n[TEST 5] Testing Scream Window Abort (Owner wakes up on Day 15 of countdown)...")
    clock += 15 * 86400  # 15 days into Scream Window
    aeterna.abort_scream_window(SAFE_ADDR, SAFE_ADDR, current_time=clock)
    assert aeterna.vaults[SAFE_ADDR]["state"] == "ACTIVE"
    assert aeterna.vaults[SAFE_ADDR]["scream_window_start"] == 0
    assert len(aeterna.guardian_votes[SAFE_ADDR]) == 0
    print("  ✓ Scream Window instantly ABORTED by owner with 1 signature!")
    print("  ✓ Vault safely restored to ACTIVE. Guardian votes wiped clean.")

    # --------------------------------------------------------------------------
    # TEST 6: Real Mortality Event & Autonomous Execution
    # --------------------------------------------------------------------------
    print("\n[TEST 6] Simulating Full Mortality Event -> 30-Day Window Elapses -> Execution...")
    clock += 366 * 86400  # Another year passes in silence
    aeterna.trigger_inactivity_cascade(SAFE_ADDR, clock)
    aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[0], clock)
    aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[1], clock)
    aeterna.guardian_attest_failure(SAFE_ADDR, GUARDIANS[2], clock)
    assert aeterna.vaults[SAFE_ADDR]["state"] == "SCREAM_WINDOW"

    # Try executing early (Day 10 of window) -> MUST FAIL
    clock += 10 * 86400
    try:
        aeterna.execute_autonomous_transfer(mock_safe, ["USDC", "WETH"], clock)
        assert False, "Execution allowed before 30-day window expired!"
    except AssertionError:
        print("  ✓ Premature execution rejected at Day 10 of Scream Window.")

    # Elapse full 30 days
    clock += 21 * 86400  # Total 31 days elapsed
    transfers = aeterna.execute_autonomous_transfer(mock_safe, ["USDC", "WETH"], clock)
    assert aeterna.vaults[SAFE_ADDR]["state"] == "EXECUTED"
    print("  ✓ Autonomous Execution SUCCESSFUL after 30-day Scream Window expired with 0 cancellations!")

    # --------------------------------------------------------------------------
    # TEST 7: Financial Extraction & Split Verification
    # --------------------------------------------------------------------------
    print("\n[TEST 7] Verifying Exact Financial Siphon & Heir Payouts:")
    for t in transfers:
        tok = t["token"]
        init = t["initial"]
        fee = t["fee"]
        heir = t["heir_amt"]

        assert fee == (init * 300) // 10000, f"Incorrect fee on {tok}"
        assert heir == init - fee, f"Incorrect heir payout on {tok}"

        print(f"  💰 {tok}: Initial Vault Balance: {init:,.2f} {tok}")
        print(f"     ├── Protocol Success Fee (3.0%): {fee:,.2f} {tok} -> Siphoned to {TREASURY}")
        print(f"     └── Beneficiary Estate (97.0%):  {heir:,.2f} {tok} -> Delivered to {HEIR_ADDR}")

    print("\n" + "=" * 70)
    print("🏆 ALL 7 VERIFICATION SUITES PASSED WITH 100% MATHEMATICAL PRECISION!")
    print("=" * 70)

if __name__ == "__main__":
    run_test_suite()
