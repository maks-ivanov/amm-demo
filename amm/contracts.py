from pyteal import *


def approval_program():
    creator_key = Bytes("creator")
    token_a_key = Bytes("token_a_key")
    token_b_key = Bytes("token_b_key")
    pool_token_key = Bytes("pool_token_key")
    fee_bps_key = Bytes("fee_bps_key")
    min_increment_key = Bytes("min_increment_key")
    ratio_key = Bytes("ratio_key")
    tokens_outstanding_key = Bytes("tokens_outstanding_key")
    scaling_factor = Int(10 ** 13)

    @Subroutine(TealType.uint64)
    def xMulYDivZ(a, b, c) -> Expr:
        return WideRatio([a, b, scaling_factor], [c, scaling_factor])

    @Subroutine(TealType.none)
    def sendToken(token_key, receiver, amount) -> Expr:
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
               {
                   TxnField.type_enum: TxnType.AssetTransfer,
                   TxnField.xfer_asset: App.globalGet(token_key),
                   TxnField.asset_receiver: receiver,
                   TxnField.asset_amount: amount
               }
            ),
            InnerTxnBuilder.Submit())

    @Subroutine(TealType.none)
    def mintAndSendPoolTokens(receiver: Expr, amount) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), App.globalGet(pool_token_key)
        )
        return Seq(
            asset_holding,
            If(asset_holding.hasValue()).Then(
                Seq(
                    sendToken(pool_token_key, receiver, amount),
                    App.globalPut(tokens_outstanding_key, App.globalGet(tokens_outstanding_key) + amount)
                )
            ),
        )

    @Subroutine(TealType.none)
    def withdrawTokenATo(receiver: Expr, pool_token_amount: TealType.uint64) -> Expr:
        pool_tokens_outstanding = App.globalGet(tokens_outstanding_key)
        token_a_holding = AssetHolding.balance(
            Global.current_application_address(), App.globalGet(token_a_key)
        )
        return Seq(
            token_a_holding,
            If(
                And(
                    pool_tokens_outstanding > Int(0),
                    pool_token_amount > Int(0),
                    token_a_holding.hasValue(),
                    token_a_holding.value() > Int(0)
                ))
                .Then(
                Seq(
                    Assert(
                        xMulYDivZ(token_a_holding.value(), pool_token_amount, pool_tokens_outstanding) > Int(0)
                    ),
                    sendToken(token_a_key, receiver,  xMulYDivZ(token_a_holding.value(), pool_token_amount, pool_tokens_outstanding)),
                )
            ),
        )

    @Subroutine(TealType.none)
    def withdrawTokenBTo(receiver: Expr, pool_token_amount: TealType.uint64) -> Expr:
        pool_tokens_outstanding = App.globalGet(tokens_outstanding_key)
        token_b_holding = AssetHolding.balance(
            Global.current_application_address(), App.globalGet(token_b_key)
        )

        return Seq(
            token_b_holding,
            If(
                And(
                    pool_tokens_outstanding > Int(0),
                    pool_token_amount > Int(0),
                    token_b_holding.hasValue(),
                    token_b_holding.value() > Int(0)
                ))
                .Then(
                    Seq(
                        Assert(
                            xMulYDivZ(token_b_holding.value(), pool_token_amount, pool_tokens_outstanding) > Int(0)),
                        sendToken(token_b_key, receiver, xMulYDivZ(token_b_holding.value(), pool_token_amount, pool_tokens_outstanding))
                )
            ),
        )

    on_create = Seq(
        App.globalPut(creator_key, Txn.application_args[0]),
        App.globalPut(token_a_key, Btoi(Txn.application_args[1])),
        App.globalPut(token_b_key, Btoi(Txn.application_args[2])),
        App.globalPut(pool_token_key, Btoi(Txn.application_args[3])),
        App.globalPut(fee_bps_key, Btoi(Txn.application_args[4])),
        App.globalPut(min_increment_key, Btoi(Txn.application_args[5])),
        App.globalPut(ratio_key, Int(0)),
        App.globalPut(tokens_outstanding_key, Int(0)),
        Approve(),
    )
    #
    on_setup = Seq(
        # opt into tokens
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_a_key),
                TxnField.asset_receiver: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_b_key),
                TxnField.asset_receiver: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(pool_token_key),
                TxnField.asset_receiver: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    on_supply_token_b_txn_index = Txn.group_index() - Int(1)
    on_supply_token_a_txn_index = Txn.group_index() - Int(2)

    on_supply_pool_token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(pool_token_key)
    )

    on_supply_token_a_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_a_key)
    )
    on_supply_token_b_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_b_key)
    )

    token_a_before_supply = ScratchVar(TealType.uint64)
    token_b_before_supply = ScratchVar(TealType.uint64)

    b_given_a = ScratchVar(TealType.uint64)
    a_given_b = ScratchVar(TealType.uint64)

    on_supply = Seq(
        on_supply_pool_token_holding,
        on_supply_token_a_holding,
        on_supply_token_b_holding,
        Assert(
            And(
                # amm has pool tokens left
                on_supply_pool_token_holding.hasValue(),
                on_supply_pool_token_holding.value() > Int(0),
                # the token transfer is before the app call
                Gtxn[on_supply_token_a_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_supply_token_a_txn_index].sender() == Txn.sender(),
                Gtxn[on_supply_token_a_txn_index].asset_receiver()
                == Global.current_application_address(),
                Gtxn[on_supply_token_a_txn_index].asset_amount() > App.globalGet(min_increment_key),

                Gtxn[on_supply_token_b_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_supply_token_b_txn_index].sender() == Txn.sender(),
                Gtxn[on_supply_token_b_txn_index].asset_receiver()
                == Global.current_application_address(),
                Gtxn[on_supply_token_b_txn_index].asset_amount() > App.globalGet(min_increment_key),
            )
        ),
        token_a_before_supply.store(on_supply_token_a_holding.value() - Gtxn[on_supply_token_a_txn_index].asset_amount()),
        token_b_before_supply.store(on_supply_token_b_holding.value() - Gtxn[on_supply_token_b_txn_index].asset_amount()),
        If(
            Or(
                Not(on_supply_token_a_holding.hasValue()),
                Not(on_supply_token_b_holding.hasValue()),
                token_a_before_supply.load() == Int(0),
                token_b_before_supply.load() == Int(0)
            )
        ).Then(
            Seq(
                mintAndSendPoolTokens(Txn.sender(), Sqrt(Gtxn[on_supply_token_a_txn_index].asset_amount()
                                                    * Gtxn[on_supply_token_b_txn_index].asset_amount())),
                Approve()
            ),
        )
        .Else(
            Seq(
                b_given_a.store(
                    xMulYDivZ(Gtxn[on_supply_token_a_txn_index].asset_amount(),
                              token_b_before_supply.load(),
                              token_a_before_supply.load())),
                If(Gtxn[on_supply_token_b_txn_index].asset_amount() >= b_given_a.load())
                .Then(
                    Seq(
                        # keep all A, return remainder B
                        sendToken(token_b_key, Txn.sender(), Gtxn[on_supply_token_b_txn_index].asset_amount() - b_given_a.load()),
                        mintAndSendPoolTokens(Txn.sender(), xMulYDivZ(App.globalGet(tokens_outstanding_key),
                                                                      Gtxn[on_supply_token_a_txn_index].asset_amount(),
                                                                      token_a_before_supply.load())),
                        Approve()
                    )
                ).Else(
                    Seq(
                        a_given_b.store(xMulYDivZ(Gtxn[on_supply_token_b_txn_index].asset_amount(),
                                                token_a_before_supply.load(),
                                                token_b_before_supply.load())),
                        If(Gtxn[on_supply_token_a_txn_index].asset_amount() >= a_given_b.load())
                        .Then(
                            Seq(
                                sendToken(token_a_key, Txn.sender(), Gtxn[on_supply_token_a_txn_index].asset_amount() - a_given_b.load()),
                                mintAndSendPoolTokens(Txn.sender(), xMulYDivZ(App.globalGet(tokens_outstanding_key),
                                                                              Gtxn[on_supply_token_b_txn_index].asset_amount(),
                                                                              token_b_before_supply.load())),
                                Approve()
                            )
                        )
                    )
                )
            )
        ),
        Reject()
    )

    on_withdraw_token_a_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_a_key)
    )
    on_withdraw_token_b_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_b_key)
    )

    on_withdraw_pool_token_txn_index = Txn.group_index() - Int(1)
    on_withdraw = Seq(
        on_withdraw_token_a_holding,
        on_withdraw_token_b_holding,
        Assert(
            And(
                # the amm has tokens left
                on_withdraw_token_a_holding.hasValue(),
                on_withdraw_token_a_holding.value() > Int(0),
                on_withdraw_token_b_holding.hasValue(),
                on_withdraw_token_b_holding.value() > Int(0),
                # the pool token transfer is before the app call
                Gtxn[on_withdraw_pool_token_txn_index].type_enum() == TxnType.AssetTransfer,
                Gtxn[on_withdraw_pool_token_txn_index].sender() == Txn.sender(),
                Gtxn[on_withdraw_pool_token_txn_index].asset_receiver()
                == Global.current_application_address()
            )
        ),
        If(
            Gtxn[on_withdraw_pool_token_txn_index].asset_amount() > Int(0)
        ).Then(
            Seq(
                withdrawTokenATo(Txn.sender(), Gtxn[on_withdraw_pool_token_txn_index].asset_amount()),
                withdrawTokenBTo(Txn.sender(), Gtxn[on_withdraw_pool_token_txn_index].asset_amount()),
                App.globalPut(tokens_outstanding_key, App.globalGet(tokens_outstanding_key) - Gtxn[
                    on_withdraw_pool_token_txn_index].asset_amount()),  # concurrency
                Approve()
            ),
        ),
        Reject()
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond([on_call_method == Bytes("setup"), on_setup],
                   [on_call_method == Bytes("supply"), on_supply],
                   [on_call_method == Bytes("withdraw"), on_withdraw])

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        # [
        #     Txn.on_completion() == OnComplete.DeleteApplication, to_delete
        # ],
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
