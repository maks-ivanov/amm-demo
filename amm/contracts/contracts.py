from amm.contracts.helpers import *
from amm.contracts.config import *


def get_setup_program():
    # if the amm has been set up, pool token id and outstanding value already exists
    pool_token_id = App.globalGetEx(Global.current_application_id(), POOL_TOKEN_KEY)
    pool_tokens_outstanding = App.globalGetEx(
        Global.current_application_id(), POOL_TOKENS_OUTSTANDING_KEY
    )
    return Seq(
        pool_token_id,
        pool_tokens_outstanding,
        # can only set up once
        Assert(Not(pool_token_id.hasValue())),
        Assert(Not(pool_tokens_outstanding.hasValue())),
        createPoolToken(POOL_TOKEN_DEFAULT_AMOUNT),
        optIn(TOKEN_A_KEY),
        optIn(TOKEN_B_KEY),
        Approve(),
    )


token_a_holding = AssetHolding.balance(
    Global.current_application_address(), App.globalGet(TOKEN_A_KEY)
)
token_b_holding = AssetHolding.balance(
    Global.current_application_address(), App.globalGet(TOKEN_B_KEY)
)


def get_supply_program():
    token_a_txn_index = Txn.group_index() - Int(2)
    token_b_txn_index = Txn.group_index() - Int(1)

    pool_token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(POOL_TOKEN_KEY)
    )

    token_a_before_txn: ScratchVar = ScratchVar(TealType.uint64)
    token_b_before_txn: ScratchVar = ScratchVar(TealType.uint64)

    on_supply = Seq(
        pool_token_holding,
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                pool_token_holding.hasValue(),
                pool_token_holding.value() > Int(0),
                validateTokenReceived(token_a_txn_index, TOKEN_A_KEY),
                validateTokenReceived(token_b_txn_index, TOKEN_B_KEY),
                Gtxn[token_a_txn_index].asset_amount()
                >= App.globalGet(MIN_INCREMENT_KEY),
                Gtxn[token_b_txn_index].asset_amount()
                >= App.globalGet(MIN_INCREMENT_KEY),
            )
        ),
        token_a_before_txn.store(
            token_a_holding.value() - Gtxn[token_a_txn_index].asset_amount()
        ),
        token_b_before_txn.store(
            token_b_holding.value() - Gtxn[token_b_txn_index].asset_amount()
        ),
        If(
            Or(
                token_a_before_txn.load() == Int(0),
                token_b_before_txn.load() == Int(0),
            )
        )
        .Then(
            # no liquidity yet, take everything
            Seq(
                mintAndSendPoolToken(
                    Txn.sender(),
                    Sqrt(
                        Gtxn[token_a_txn_index].asset_amount()
                        * Gtxn[token_b_txn_index].asset_amount()
                    ),
                ),
                Approve(),
            ),
        )
        .ElseIf(
            tryTakeAdjustedAmounts(
                Gtxn[token_a_txn_index].asset_amount(),
                token_a_before_txn.load(),
                TOKEN_B_KEY,
                Gtxn[token_b_txn_index].asset_amount(),
                token_b_before_txn.load(),
            )
        )
        .Then(Approve())
        .ElseIf(
            tryTakeAdjustedAmounts(
                Gtxn[token_b_txn_index].asset_amount(),
                token_b_before_txn.load(),
                TOKEN_A_KEY,
                Gtxn[token_a_txn_index].asset_amount(),
                token_a_before_txn.load(),
            ),
        )
        .Then(Approve())
        .Else(Reject()),
    )
    return on_supply


def get_withdraw_program():
    pool_token_txn_index = Txn.group_index() - Int(1)
    on_withdraw = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                token_a_holding.hasValue(),
                token_a_holding.value() > Int(0),
                token_b_holding.hasValue(),
                token_b_holding.value() > Int(0),
                validateTokenReceived(pool_token_txn_index, POOL_TOKEN_KEY),
            )
        ),
        If(Gtxn[pool_token_txn_index].asset_amount() > Int(0)).Then(
            Seq(
                withdrawGivenPoolToken(
                    Txn.sender(),
                    TOKEN_A_KEY,
                    Gtxn[pool_token_txn_index].asset_amount(),
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
                ),
                withdrawGivenPoolToken(
                    Txn.sender(),
                    TOKEN_B_KEY,
                    Gtxn[pool_token_txn_index].asset_amount(),
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
                ),
                App.globalPut(
                    POOL_TOKENS_OUTSTANDING_KEY,
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY)
                    - Gtxn[pool_token_txn_index].asset_amount(),
                ),
                Approve(),
            ),
        ),
        Reject(),
    )

    return on_withdraw


def get_swap_program():
    on_swap_txn_index = Txn.group_index() - Int(1)
    given_token_amt_before_txn = ScratchVar(TealType.uint64)
    other_token_amt_before_txn = ScratchVar(TealType.uint64)

    to_send_key = ScratchVar(TealType.bytes)
    to_send_amount = ScratchVar(TealType.uint64)

    on_swap = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) > Int(0),
                Or(
                    validateTokenReceived(on_swap_txn_index, TOKEN_A_KEY),
                    validateTokenReceived(on_swap_txn_index, TOKEN_B_KEY),
                ),
            )
        ),
        If(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(TOKEN_A_KEY))
        .Then(
            Seq(
                given_token_amt_before_txn.store(
                    token_a_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                other_token_amt_before_txn.store(token_b_holding.value()),
                to_send_key.store(TOKEN_B_KEY),
            )
        )
        .ElseIf(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(TOKEN_B_KEY))
        .Then(
            Seq(
                given_token_amt_before_txn.store(
                    token_b_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                other_token_amt_before_txn.store(token_a_holding.value()),
                to_send_key.store(TOKEN_A_KEY),
            )
        )
        .Else(Reject()),
        to_send_amount.store(
            computeOtherTokenOutputPerGivenTokenInput(
                Gtxn[on_swap_txn_index].asset_amount(),
                given_token_amt_before_txn.load(),
                other_token_amt_before_txn.load(),
                App.globalGet(FEE_BPS_KEY),
            )
        ),
        Assert(
            And(
                to_send_amount.load() > Int(0),
                to_send_amount.load() < other_token_amt_before_txn.load(),
            )
        ),
        sendToken(to_send_key.load(), Txn.sender(), to_send_amount.load()),
        Approve(),
    )

    return on_swap


def approval_program():
    on_create = Seq(
        App.globalPut(CREATOR_KEY, Txn.application_args[0]),
        App.globalPut(TOKEN_A_KEY, Btoi(Txn.application_args[1])),
        App.globalPut(TOKEN_B_KEY, Btoi(Txn.application_args[2])),
        App.globalPut(FEE_BPS_KEY, Btoi(Txn.application_args[3])),
        App.globalPut(MIN_INCREMENT_KEY, Btoi(Txn.application_args[4])),
        Approve(),
    )

    on_setup = get_setup_program()
    on_supply = get_supply_program()
    on_withdraw = get_withdraw_program()
    on_swap = get_swap_program()

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("supply"), on_supply],
        [on_call_method == Bytes("withdraw"), on_withdraw],
        [on_call_method == Bytes("swap"), on_swap],
    )

    on_delete = Seq(
        If(App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) == Int(0)).Then(
            Seq(Assert(Txn.sender() == App.globalGet(CREATOR_KEY)), Approve())
        ),
        Reject(),
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        [Txn.on_completion() == OnComplete.DeleteApplication, on_delete],
        [
            Or(
                Txn.on_completion() == OnComplete.OptIn,
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.UpdateApplication,
            ),
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("amm_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("amm_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
