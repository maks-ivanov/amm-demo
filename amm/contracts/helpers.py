from pyteal import *

from amm.contracts.config import (
    SCALING_FACTOR,
    POOL_TOKENS_OUTSTANDING_KEY,
    POOL_TOKEN_KEY,
)


@Subroutine(TealType.uint64)
def validateTokenReceived(transaction_index: TealType.uint64, token_key):
    return And(
        Gtxn[transaction_index].type_enum() == TxnType.AssetTransfer,
        Gtxn[transaction_index].sender() == Txn.sender(),
        Gtxn[transaction_index].asset_receiver()
        == Global.current_application_address(),
        Gtxn[transaction_index].xfer_asset() == App.globalGet(token_key),
        Gtxn[transaction_index].asset_amount() > Int(0),
    )


@Subroutine(TealType.uint64)
def xMulYDivZ(a, b, c) -> Expr:
    return WideRatio([a, b, SCALING_FACTOR], [c, SCALING_FACTOR])


@Subroutine(TealType.none)
def sendToken(token_key, receiver, amount) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_key),
                TxnField.asset_receiver: receiver,
                TxnField.asset_amount: amount,
            }
        ),
        InnerTxnBuilder.Submit(),
    )


@Subroutine(TealType.none)
def optIn(token_key) -> Expr:
    return sendToken(token_key, Global.current_application_address(), Int(0))


@Subroutine(TealType.none)
def returnRemainder(
    token_key, received_amount: TealType.uint64, to_keep_amount: TealType.uint64
):
    remainder = received_amount - to_keep_amount
    return Seq(
        If(remainder > Int(0)).Then(
            sendToken(
                token_key,
                Txn.sender(),
                remainder,
            )
        ),
    )


@Subroutine(TealType.none)
def withdrawGivenPoolToken(
    receiver: Expr,
    token_key: TealType.bytes,
    pool_token_amount: TealType.uint64,
    pool_tokens_outstanding: TealType.uint64,
) -> Expr:
    token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(token_key)
    )
    return Seq(
        token_holding,
        If(
            And(
                pool_tokens_outstanding > Int(0),
                pool_token_amount > Int(0),
                token_holding.hasValue(),
                token_holding.value() > Int(0),
            )
        ).Then(
            Seq(
                Assert(
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    )
                    > Int(0)
                ),
                sendToken(
                    token_key,
                    receiver,
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    ),
                ),
            )
        ),
    )


@Subroutine(TealType.uint64)
def assessFee(amount: TealType.uint64, fee_bps: TealType.uint64):
    fee_num = Int(10000) - fee_bps
    fee_denom = Int(10000)
    return xMulYDivZ(amount, fee_num, fee_denom)


@Subroutine(TealType.uint64)
def computeOtherTokenOutputPerGivenTokenInput(
    input_amount: TealType.uint64,
    previous_given_token_amount: TealType.uint64,
    previous_other_token_amount: TealType.uint64,
    fee_bps: TealType.uint64,
):
    k = previous_given_token_amount * previous_other_token_amount
    amount_sub_fee = assessFee(input_amount, fee_bps)
    to_send = previous_other_token_amount - k / (
        previous_given_token_amount + amount_sub_fee
    )
    return to_send


@Subroutine(TealType.none)
def mintAndSendPoolTokens(receiver: Expr, amount) -> Expr:
    return Seq(
        sendToken(POOL_TOKEN_KEY, receiver, amount),
        App.globalPut(
            POOL_TOKENS_OUTSTANDING_KEY,
            App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) + amount,
        ),
    )
