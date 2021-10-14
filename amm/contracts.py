from pyteal import *
from .contract_helpers import *


def approval_program():
    creator_key = Bytes("creator")
    token_a_key = Bytes("token_a_key")
    token_b_key = Bytes("token_b_key")
    pool_token_key = Bytes("pool_token_key")
    fee_bps_key = Bytes("fee_bps_key")
    min_increment_key = Bytes("min_increment_key")
    pool_tokens_outstanding_key = Bytes("pool_tokens_outstanding_key")

    @Subroutine(TealType.none)
    def mintAndSendPoolTokens(receiver: Expr, amount) -> Expr:
        return Seq(
            sendToken(pool_token_key, receiver, amount),
            App.globalPut(
                pool_tokens_outstanding_key,
                App.globalGet(pool_tokens_outstanding_key) + amount,
            ),
        )

    on_create = Seq(
        # no negative fees allowed
        Assert(Btoi(Txn.application_args[4]) > Int(0)),
        App.globalPut(creator_key, Txn.application_args[0]),
        App.globalPut(token_a_key, Btoi(Txn.application_args[1])),
        App.globalPut(token_b_key, Btoi(Txn.application_args[2])),
        App.globalPut(pool_token_key, Btoi(Txn.application_args[3])),
        App.globalPut(fee_bps_key, Btoi(Txn.application_args[4])),
        App.globalPut(min_increment_key, Btoi(Txn.application_args[5])),
        App.globalPut(pool_tokens_outstanding_key, Int(0)),
        Approve(),
    )
    #
    on_setup = Seq(
        optIn(token_a_key),
        optIn(token_b_key),
        optIn(pool_token_key),
        Approve(),
    )

    token_a_txn_index = Txn.group_index() - Int(2)
    token_b_txn_index = Txn.group_index() - Int(1)

    pool_token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(pool_token_key)
    )

    token_a_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_a_key)
    )
    token_b_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_b_key)
    )

    token_a_before_txn: ScratchVar = ScratchVar(TealType.uint64)
    token_b_before_txn: ScratchVar = ScratchVar(TealType.uint64)

    to_keep = ScratchVar(TealType.uint64)

    on_supply = Seq(
        pool_token_holding,
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                pool_token_holding.hasValue(),
                pool_token_holding.value() > Int(0),
                validateTokenReceived(token_a_txn_index, token_a_key),
                validateTokenReceived(token_b_txn_index, token_b_key),
                Gtxn[token_a_txn_index].asset_amount()
                >= App.globalGet(min_increment_key),
                Gtxn[token_b_txn_index].asset_amount()
                >= App.globalGet(min_increment_key),
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
            Seq(
                mintAndSendPoolTokens(
                    Txn.sender(),
                    Sqrt(
                        Gtxn[token_a_txn_index].asset_amount()
                        * Gtxn[token_b_txn_index].asset_amount()
                    ),
                ),
                Approve(),
            ),
        )
        .Else(
            Seq(
                to_keep.store(
                    xMulYDivZ(
                        Gtxn[token_a_txn_index].asset_amount(),
                        token_b_before_txn.load(),
                        token_a_before_txn.load(),
                    )
                ),
                If(
                    And(
                        to_keep.load() > Int(0),
                        Gtxn[token_b_txn_index].asset_amount() >= to_keep.load(),
                    )
                )
                .Then(
                    Seq(
                        # keep all A, return remainder B
                        returnRemainder(
                            token_b_key,
                            Gtxn[token_b_txn_index].asset_amount(),
                            to_keep.load(),
                        ),
                        mintAndSendPoolTokens(
                            Txn.sender(),
                            xMulYDivZ(
                                App.globalGet(pool_tokens_outstanding_key),
                                Gtxn[token_a_txn_index].asset_amount(),
                                token_a_before_txn.load(),
                            ),
                        ),
                        Approve(),
                    )
                )
                .Else(
                    Seq(
                        to_keep.store(
                            xMulYDivZ(
                                Gtxn[token_b_txn_index].asset_amount(),
                                token_a_before_txn.load(),
                                token_b_before_txn.load(),
                            )
                        ),
                        If(
                            And(
                                to_keep.load() > Int(0),
                                Gtxn[token_a_txn_index].asset_amount()
                                >= to_keep.load(),
                            )
                        ).Then(
                            Seq(
                                # keep all B, return remainder A
                                returnRemainder(
                                    token_a_key,
                                    Gtxn[token_a_txn_index].asset_amount(),
                                    to_keep.load(),
                                ),
                                mintAndSendPoolTokens(
                                    Txn.sender(),
                                    xMulYDivZ(
                                        App.globalGet(pool_tokens_outstanding_key),
                                        Gtxn[token_b_txn_index].asset_amount(),
                                        token_b_before_txn.load(),
                                    ),
                                ),
                                Approve(),
                            )
                        ),
                    )
                ),
            )
        ),
        Reject(),
    )

    on_withdraw_pool_token_txn_index = Txn.group_index() - Int(1)
    on_withdraw = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                # the amm has tokens left
                token_a_holding.hasValue(),
                token_a_holding.value() > Int(0),
                token_b_holding.hasValue(),
                token_b_holding.value() > Int(0),
                validateTokenReceived(on_withdraw_pool_token_txn_index, pool_token_key),
            )
        ),
        If(Gtxn[on_withdraw_pool_token_txn_index].asset_amount() > Int(0)).Then(
            Seq(
                withdrawGivenPoolToken(
                    Txn.sender(),
                    token_a_key,
                    Gtxn[on_withdraw_pool_token_txn_index].asset_amount(),
                    App.globalGet(pool_tokens_outstanding_key),
                ),
                withdrawGivenPoolToken(
                    Txn.sender(),
                    token_b_key,
                    Gtxn[on_withdraw_pool_token_txn_index].asset_amount(),
                    App.globalGet(pool_tokens_outstanding_key),
                ),
                App.globalPut(
                    pool_tokens_outstanding_key,
                    App.globalGet(pool_tokens_outstanding_key)
                    - Gtxn[on_withdraw_pool_token_txn_index].asset_amount(),
                ),
                Approve(),
            ),
        ),
        Reject(),
    )

    on_swap_txn_index = Txn.group_index() - Int(1)
    to_send_key = ScratchVar(TealType.bytes)
    to_send_amount = ScratchVar(TealType.uint64)
    send_limit = ScratchVar(TealType.uint64)

    on_swap = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                App.globalGet(pool_tokens_outstanding_key) > Int(0),
                Or(
                    validateTokenReceived(on_swap_txn_index, token_a_key),
                    validateTokenReceived(on_swap_txn_index, token_b_key),
                ),
            )
        ),
        If(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(token_a_key))
        .Then(
            Seq(
                token_a_before_txn.store(
                    token_a_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                token_b_before_txn.store(token_b_holding.value()),
                to_send_key.store(token_b_key),
                send_limit.store(token_b_holding.value()),
            )
        )
        .ElseIf(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(token_b_key))
        .Then(
            Seq(
                token_a_before_txn.store(token_a_holding.value()),
                token_b_before_txn.store(
                    token_b_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                to_send_key.store(token_a_key),
                send_limit.store(token_a_holding.value()),
            )
        )
        .Else(Reject()),
        to_send_amount.store(
            computeTokenAOutputPerTokenBInput(
                Gtxn[on_swap_txn_index].asset_amount(),
                token_a_before_txn.load(),
                token_b_before_txn.load(),
                App.globalGet(fee_bps_key),
            )
        ),
        Assert(
            And(
                to_send_amount.load() > Int(0),
                to_send_amount.load() < send_limit.load(),
            )
        ),
        sendToken(to_send_key.load(), Txn.sender(), to_send_amount.load()),
        Approve(),
    )

    on_delete = Seq(
        If(App.globalGet(pool_tokens_outstanding_key) == Int(0)).Then(
            Seq(Assert(Txn.sender() == App.globalGet(creator_key)), Approve())
        ),
        Reject(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("supply"), on_supply],
        [on_call_method == Bytes("withdraw"), on_withdraw],
        [on_call_method == Bytes("swap"), on_swap],
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
    with open("auction_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("auction_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
